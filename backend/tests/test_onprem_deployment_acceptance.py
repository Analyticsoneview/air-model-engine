from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: str) -> dict:
    with (ROOT / path).open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a YAML object")
    return value


class OnPremDeploymentAcceptanceTests(unittest.TestCase):
    def test_compose_profile_contains_all_mandatory_air_services(self):
        compose = load_yaml("compose.local.yml")
        services = compose["services"]
        required = {"postgres", "redis", "rabbitmq", "air-api", "air-workflow-worker", "air-pwa"}
        self.assertTrue(required.issubset(services), f"Missing Compose services: {required - set(services)}")
        for name in required:
            self.assertEqual(services[name].get("restart"), "unless-stopped", name)

    def test_compose_api_and_worker_use_single_tenant_onprem_profile(self):
        compose = load_yaml("compose.local.yml")
        api_env = compose["services"]["air-api"]["environment"]
        worker_env = compose["services"]["air-workflow-worker"]["environment"]
        for env in (api_env, worker_env):
            self.assertEqual(env["AIR_DEPLOYMENT_PROFILE"], "${AIR_DEPLOYMENT_PROFILE:-onprem-single}")
            self.assertEqual(env["AIR_DEPLOYMENT_MODE"], "${AIR_DEPLOYMENT_MODE:-on_prem}")
            self.assertEqual(env["AIR_TENANCY_MODE"], "${AIR_TENANCY_MODE:-single}")
        self.assertIn("rabbitmq", compose["services"]["air-workflow-worker"]["depends_on"])

    def test_compose_persists_customer_data_and_uses_file_backed_secrets(self):
        compose = load_yaml("compose.local.yml")
        volumes = compose["volumes"]
        self.assertTrue({"air_data", "postgres_data", "redis_data", "rabbitmq_data"}.issubset(volumes))
        self.assertIn("air_data:/var/lib/air", compose["services"]["air-api"]["volumes"])
        self.assertIn("air_data:/var/lib/air", compose["services"]["air-workflow-worker"]["volumes"])
        for name, definition in compose["secrets"].items():
            self.assertTrue(definition["file"].startswith("./.air-secrets/"), name)
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".air-secrets/", gitignore)
        self.assertIn(".air-local.env", gitignore)

    def test_swarm_profile_has_mandatory_services_and_private_overlay_network(self):
        stack = load_yaml("docker-stack.yml")
        services = stack["services"]
        required = {"postgres", "redis", "rabbitmq", "air-api", "air-workflow-worker", "air-pwa", "air-caddy"}
        self.assertTrue(required.issubset(services), f"Missing Swarm services: {required - set(services)}")
        self.assertEqual(stack["networks"]["air_private"]["driver"], "overlay")
        self.assertIn("air_private", services["air-api"]["networks"])
        self.assertIn("air_private", services["air-workflow-worker"]["networks"])
        self.assertIn("air_private", services["air-pwa"]["networks"])

    def test_swarm_api_and_worker_are_single_tenant_and_persistent(self):
        stack = load_yaml("docker-stack.yml")
        for service_name in ("air-api", "air-workflow-worker"):
            service = stack["services"][service_name]
            env = service["environment"]
            self.assertEqual(env["AIR_DEPLOYMENT_PROFILE"], "${AIR_DEPLOYMENT_PROFILE:-onprem-single}")
            self.assertEqual(env["AIR_DEPLOYMENT_MODE"], "${AIR_DEPLOYMENT_MODE:-on_prem}")
            self.assertEqual(env["AIR_TENANCY_MODE"], "${AIR_TENANCY_MODE:-single}")
            self.assertIn("air_data:/var/lib/air", service["volumes"])
        self.assertNotIn("ports", stack["services"]["air-api"])
        self.assertIn("air-api", stack["services"]["air-workflow-worker"]["depends_on"] if isinstance(stack["services"]["air-workflow-worker"].get("depends_on"), dict) else [])

    def test_swarm_declares_external_secrets_and_no_inline_secret_values(self):
        stack = load_yaml("docker-stack.yml")
        required = {
            "air_jwt_secret", "air_credential_key", "air_admin_api_key", "air_admin_mfa_key",
            "air_postgres_password", "air_redis_password", "air_database_url", "air_redis_url",
            "air_rabbitmq_password", "air_telegram_bot_token", "air_smtp_password",
        }
        self.assertTrue(required.issubset(stack["secrets"]))
        for name in required:
            self.assertTrue(stack["secrets"][name].get("external"), name)
        source = (ROOT / "docker-stack.yml").read_text(encoding="utf-8").lower()
        for forbidden in ("password: air", "jwt_secret: ", "credential_key: "):
            self.assertNotIn(forbidden, source)

    def test_one_click_installers_gate_on_full_readiness_and_twelve_month_history(self):
        shell = (ROOT / "AIRSTART.sh").read_text(encoding="utf-8")
        powershell = (ROOT / "AIRSTART.ps1").read_text(encoding="utf-8")
        compose = load_yaml("compose.local.yml")
        self.assertIn("compose.local.yml up -d --build", shell)
        self.assertIn("compose.local.yml up -d --build", powershell)
        self.assertIn("http://localhost:8000/ready", shell)
        self.assertIn("http://localhost:8000/ready", powershell)
        self.assertIn("AIR_NSE_HISTORY_MONTHS", compose["services"]["air-api"]["environment"])
        self.assertEqual(compose["services"]["air-api"]["environment"]["AIR_NSE_HISTORY_MONTHS"], "12")

    def test_swarm_deployer_validates_rendered_stack_and_worker_runtime_heartbeat(self):
        deployer = (ROOT / "deploy/deploy-swarm.sh").read_text(encoding="utf-8")
        self.assertIn("docker stack config --compose-file docker-stack.yml", deployer)
        self.assertIn("workflow-runtime", deployer)
        self.assertIn("rabbitmq_connected", deployer)
        self.assertIn("docker stack deploy", deployer)


if __name__ == "__main__":
    unittest.main()
