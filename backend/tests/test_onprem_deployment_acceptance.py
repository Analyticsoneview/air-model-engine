from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def section(source: str, heading: str, next_heading: str | None = None) -> str:
    start = source.index(heading)
    end = source.find(next_heading, start + len(heading)) if next_heading else -1
    return source[start:] if end < 0 else source[start:end]


class OnPremDeploymentAcceptanceTests(unittest.TestCase):
    def test_compose_profile_contains_all_mandatory_air_services(self):
        compose = read("compose.local.yml")
        required = ("postgres:", "redis:", "rabbitmq:", "air-api:", "air-workflow-worker:", "air-pwa:")
        for service in required:
            self.assertIn(f"  {service}", compose)
        for service in required:
            block = section(compose, f"  {service}", "\n  ")
            self.assertIn("restart: unless-stopped", block)

    def test_compose_api_and_worker_use_single_tenant_onprem_profile(self):
        compose = read("compose.local.yml")
        for key, value in (
            ("AIR_DEPLOYMENT_PROFILE", "${AIR_DEPLOYMENT_PROFILE:-onprem-single}"),
            ("AIR_DEPLOYMENT_MODE", "${AIR_DEPLOYMENT_MODE:-on_prem}"),
            ("AIR_TENANCY_MODE", "${AIR_TENANCY_MODE:-single}"),
        ):
            self.assertIn(f"{key}: {value}", compose)
        worker = section(compose, "  air-workflow-worker:", "\n  air-pwa:")
        self.assertIn("python -m app.workflow_worker", worker)
        self.assertIn("rabbitmq:", worker)

    def test_compose_persists_customer_data_and_uses_file_backed_secrets(self):
        compose = read("compose.local.yml")
        for volume in ("air_data:", "postgres_data:", "redis_data:", "rabbitmq_data:"):
            self.assertIn(f"  {volume}", compose)
        self.assertGreaterEqual(compose.count("air_data:/var/lib/air"), 2)
        self.assertIn("file: ./.air-secrets/", compose)
        gitignore = read(".gitignore")
        self.assertIn(".air-secrets/", gitignore)
        self.assertIn(".air-local.env", gitignore)

    def test_swarm_profile_has_mandatory_services_and_private_overlay_network(self):
        stack = read("docker-stack.yml")
        for service in ("postgres:", "redis:", "rabbitmq:", "air-api:", "air-workflow-worker:", "air-pwa:", "air-caddy:"):
            self.assertIn(f"  {service}", stack)
        self.assertIn("driver: overlay", stack)
        self.assertIn("air_private", stack)

    def test_swarm_api_and_worker_are_single_tenant_and_persistent(self):
        stack = read("docker-stack.yml")
        for key, value in (
            ("AIR_DEPLOYMENT_PROFILE", "${AIR_DEPLOYMENT_PROFILE:-onprem-single}"),
            ("AIR_DEPLOYMENT_MODE", "${AIR_DEPLOYMENT_MODE:-on_prem}"),
            ("AIR_TENANCY_MODE", "${AIR_TENANCY_MODE:-single}"),
        ):
            self.assertIn(f"{key}: {value}", stack)
        self.assertGreaterEqual(stack.count("air_data:/var/lib/air"), 2)
        api = section(stack, "  air-api:", "\n  air-pwa:")
        self.assertNotIn("    ports:", api)
        worker = section(stack, "  air-workflow-worker:", "\n  air-api:")
        self.assertIn("python -m app.workflow_worker", worker)

    def test_swarm_declares_external_secrets_and_no_inline_secret_values(self):
        stack = read("docker-stack.yml")
        required = (
            "air_jwt_secret", "air_credential_key", "air_admin_api_key", "air_admin_mfa_key",
            "air_postgres_password", "air_redis_password", "air_database_url", "air_redis_url",
            "air_rabbitmq_password", "air_telegram_bot_token", "air_smtp_password",
        )
        for name in required:
            self.assertIn(f"  {name}:\n    external: true", stack)
        lowered = stack.lower()
        for forbidden in ("password: air", "jwt_secret: ", "credential_key: "):
            self.assertNotIn(forbidden, lowered)

    def test_one_click_installers_gate_on_full_readiness_and_twelve_month_history(self):
        shell = read("AIRSTART.sh")
        powershell = read("AIRSTART.ps1")
        compose = read("compose.local.yml")
        self.assertIn("compose.local.yml up -d --build", shell)
        self.assertIn("compose.local.yml up -d --build", powershell)
        self.assertIn("http://localhost:8000/ready", shell)
        self.assertIn("http://localhost:8000/ready", powershell)
        self.assertIn("AIR_NSE_HISTORY_MONTHS: \"12\"", compose)

    def test_swarm_deployer_validates_rendered_stack_and_worker_runtime_heartbeat(self):
        deployer = read("deploy/deploy-swarm.sh")
        self.assertIn("docker stack config --compose-file docker-stack.yml", deployer)
        self.assertIn("workflow-runtime", deployer)
        self.assertIn("rabbitmq_connected", deployer)
        self.assertIn("docker stack deploy", deployer)


if __name__ == "__main__":
    unittest.main()
