from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def service_block(source: str, service_name: str) -> str:
    heading = f"  {service_name}:\n"
    start = source.index(heading)
    match = re.search(r"\n  [A-Za-z0-9_-]+:\n", source[start + len(heading):])
    end = start + len(heading) + match.start() if match else len(source)
    return source[start:end]


class OnPremDeploymentAcceptanceTests(unittest.TestCase):
    def test_compose_profile_contains_all_mandatory_air_services(self):
        compose = read("compose.local.yml")
        required = ("postgres:", "redis:", "rabbitmq:", "air-api:", "air-workflow-worker:", "air-pwa:")
        for service in required:
            self.assertIn(f"  {service}", compose)
        for service in required:
            block = service_block(compose, service[:-1])
            self.assertIn("restart: unless-stopped", block)

    def test_compose_api_and_worker_use_single_tenant_onprem_profile(self):
        compose = read("compose.local.yml")
        for key, value in (
            ("AIR_DEPLOYMENT_PROFILE", "${AIR_DEPLOYMENT_PROFILE:-onprem-single}"),
            ("AIR_DEPLOYMENT_MODE", "${AIR_DEPLOYMENT_MODE:-on_prem}"),
            ("AIR_TENANCY_MODE", "${AIR_TENANCY_MODE:-single}"),
        ):
            self.assertIn(f"{key}: {value}", compose)
        worker = service_block(compose, "air-workflow-worker")
        self.assertIn('command: ["python", "-m", "app.workflow_worker"]', worker)
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
        api = service_block(stack, "air-api")
        self.assertNotIn("    ports:", api)
        worker = service_block(stack, "air-workflow-worker")
        self.assertIn('command: ["python", "-m", "app.workflow_worker"]', worker)

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


    def test_nse_bootstrap_can_be_disabled_only_by_explicit_environment_override(self):
        compose = read("compose.local.yml")
        stack = read("docker-stack.yml")
        self.assertIn("AIR_NSE_BOOTSTRAP_ENABLED: ${AIR_NSE_BOOTSTRAP_ENABLED:-true}", compose)
        self.assertIn("AIR_NSE_BOOTSTRAP_ENABLED: ${AIR_NSE_BOOTSTRAP_ENABLED:-true}", stack)
        self.assertIn("AIR_NSE_HISTORY_MONTHS: ${AIR_NSE_HISTORY_MONTHS:-12}", stack)

    def test_ci_compose_smoke_checks_api_pwa_and_rabbitmq_worker_heartbeat(self):
        smoke = read("scripts/ci/onprem-compose-runtime-smoke.sh")
        self.assertIn("AIR_NSE_BOOTSTRAP_ENABLED=false", smoke)
        self.assertIn("docker compose -f compose.local.yml up -d --build", smoke)
        self.assertIn("http://127.0.0.1:8000/health", smoke)
        self.assertIn("http://127.0.0.1:8080/health", smoke)
        self.assertIn("workflow-runtime", smoke)
        self.assertIn("rabbitmq_connected", smoke)
        self.assertIn("docker compose -f compose.local.yml down --volumes", smoke)

    def test_deployment_readme_matches_implemented_aws_profiles_and_deferrals(self):
        docs = read("deploy/README.md")
        self.assertIn("shared RDS PostgreSQL", docs)
        self.assertIn("per-tenant S3 buckets", docs)
        self.assertIn("RabbitMQ vhosts", docs)
        self.assertIn("Live AWS provisioning is deferred", docs)
        self.assertNotIn("adapters are delivered in the subsequent", docs)


if __name__ == "__main__":
    unittest.main()
