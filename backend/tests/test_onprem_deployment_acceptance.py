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

    def test_one_click_installers_gate_on_full_readiness_and_three_month_history(self):
        shell = read("AIRSTART.sh")
        powershell = read("AIRSTART.ps1")
        compose = read("compose.local.yml")
        self.assertIn("compose.local.yml up -d --build", shell)
        self.assertIn("compose.local.yml up -d --build", powershell)
        self.assertIn("http://localhost:8000/health", shell)
        self.assertIn("http://localhost:8000/ready", shell)
        self.assertIn("http://localhost:8000/health", powershell)
        self.assertIn("http://localhost:8000/ready", powershell)
        self.assertLess(shell.index("http://localhost:8000/ready"), shell.index("http://localhost:8080"))
        self.assertLess(powershell.index("http://localhost:8000/ready"), powershell.index('Start-Process "http://localhost:8080"'))
        self.assertIn("AIR_NSE_HISTORY_MONTHS: ${AIR_NSE_HISTORY_MONTHS:-3}", compose)

    def test_swarm_deployer_validates_rendered_stack_and_worker_runtime_heartbeat(self):
        deployer = read("deploy/deploy-swarm.sh")
        self.assertIn("docker stack config --compose-file docker-stack.yml", deployer)
        self.assertIn("workflow-runtime", deployer)
        self.assertIn("rabbitmq_connected", deployer)
        self.assertIn("docker stack deploy", deployer)
        self.assertIn("http://127.0.0.1:8000/health", deployer)
        self.assertIn("http://127.0.0.1:8000/ready", deployer)
        self.assertIn("AIR_INSTALL_READINESS_TIMEOUT_MINUTES", deployer)


    def test_nse_bootstrap_can_be_disabled_only_by_explicit_environment_override(self):
        compose = read("compose.local.yml")
        stack = read("docker-stack.yml")
        self.assertIn("AIR_NSE_BOOTSTRAP_ENABLED: ${AIR_NSE_BOOTSTRAP_ENABLED:-true}", compose)
        self.assertIn("AIR_NSE_BOOTSTRAP_ENABLED: ${AIR_NSE_BOOTSTRAP_ENABLED:-true}", stack)
        self.assertIn("AIR_NSE_HISTORY_MONTHS: ${AIR_NSE_HISTORY_MONTHS:-3}", stack)

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
        self.assertIn("Shared RDS PostgreSQL", docs)
        self.assertIn("per-tenant S3 buckets", docs)
        self.assertIn("RabbitMQ vhosts", docs)
        self.assertIn("Live AWS provisioning is deferred", docs)
        self.assertNotIn("adapters are delivered in the subsequent", docs)


    def test_windows_installers_fail_on_native_docker_command_errors(self):
        start = read("AIRSTART.ps1")
        deploy = read("AIRDEPLOY.ps1")
        self.assertIn("docker compose version", start)
        self.assertGreaterEqual(start.count("$LASTEXITCODE -ne 0"), 4)
        self.assertIn("docker info", start)
        self.assertIn("$LASTEXITCODE -ne 0", start)
        self.assertIn("scripts/air_manager.py", deploy)

    def test_swarm_guide_has_real_markdown_line_breaks(self):
        guide = read("deploy/DOCKER_SWARM.md")
        self.assertNotIn("\\n\\n", guide)
        self.assertIn("## 2. Create Docker secrets", guide)


    def test_local_pwa_image_builds_customer_and_admin_entrypoints(self):
        dockerfile = read("deploy/pwa.Dockerfile")
        self.assertIn("--target lib/main.dart", dockerfile)
        self.assertIn("--target lib/admin_main.dart", dockerfile)
        self.assertIn('--base-href "/admin/"', dockerfile)
        self.assertIn("/usr/share/nginx/html/admin", dockerfile)
        nginx = read("deploy/nginx-air-pwa.conf")
        self.assertIn("location /admin/", nginx)
        self.assertIn("/admin/index.html", nginx)

    def test_windows_local_startup_backs_up_before_migrations_and_preserves_database_services(self):
        starter = read("scripts/windows/Start-AIR-Local.ps1")
        self.assertIn("pg_dump", starter)
        self.assertIn("pg_restore", starter)
        self.assertIn("Get-FileHash", starter)
        self.assertIn('"--no-deps", "air-api"', starter)
        self.assertIn('"--no-deps", "air-workflow-worker"', starter)
        self.assertIn("check_workflow_runtime.py", starter)
        self.assertIn("check_admin_bootstrap.py", starter)
        self.assertNotIn("down -v", starter.lower())
        self.assertNotIn("system prune", starter.lower())

    def test_windows_local_runtime_waits_for_full_readiness_before_opening_apps(self):
        starter = read("scripts/windows/Start-AIR-Local.ps1")
        self.assertIn('Invoke-RestMethod -Uri "http://localhost:8000/ready"', starter)
        self.assertIn("RabbitMQ-connected worker runtime are ready", starter)
        self.assertLess(
            starter.index('Invoke-RestMethod -Uri "http://localhost:8000/ready"'),
            starter.index('Start-Process "http://localhost:8080/admin/"'),
        )

    def test_initial_admin_bootstrap_is_existing_interactive_totp_flow(self):
        bootstrap = read("backend/scripts/bootstrap_admin.py")
        self.assertIn("verify_totp", bootstrap)
        self.assertIn("store.bootstrap(email, password, secret)", bootstrap)
        self.assertIn("air-admin-mfa-setup.svg", bootstrap)
        self.assertIn("No Super Admin account was created", bootstrap)

    def test_local_pwa_does_not_bake_an_insecure_http_api_url(self):
        compose = read("compose.local.yml")
        pwa = service_block(compose, "air-pwa")
        self.assertIn("dockerfile: deploy/pwa.Dockerfile", pwa)
        self.assertNotIn("AIR_API_BASE_URL: http://", pwa)


    def test_rabbitmq_4_reads_password_from_docker_secret_without_legacy_file_env(self):
        compose = read("compose.local.yml")
        stack = read("docker-stack.yml")
        rabbit_config = read("deploy/rabbitmq.conf")
        self.assertNotIn("RABBITMQ_DEFAULT_PASS_FILE", compose)
        self.assertNotIn("RABBITMQ_DEFAULT_PASS_FILE", stack)
        self.assertIn("RABBITMQ_CONFIG_FILE: /etc/rabbitmq/rabbitmq.conf", compose)
        self.assertIn("RABBITMQ_CONFIG_FILE: /etc/rabbitmq/rabbitmq.conf", stack)
        self.assertIn("rabbitmq_password", compose)
        self.assertIn("air_rabbitmq_password", stack)
        self.assertIn("default_pass = $(AIR_RABBITMQ_DEFAULT_PASSWORD)", rabbit_config)
        self.assertIn("/usr/local/bin/docker-entrypoint.sh rabbitmq-server", compose)
        self.assertIn("/usr/local/bin/docker-entrypoint.sh rabbitmq-server", stack)
        self.assertIn('PASSWORD="$$(cat /run/secrets/rabbitmq_password)', compose)
        self.assertIn('PASSWORD="$$(cat /run/secrets/air_rabbitmq_password)', stack)
        self.assertIn("air_rabbitmq_config", stack)


    def test_readiness_register_separates_code_delivery_from_environment_gates(self):
        register = read("deploy/READINESS_REGISTER.md")
        self.assertIn("Gate 14 — tenant isolation and AWS SaaS provisioning foundation | COMPLETE", register)
        self.assertIn("AWS live infrastructure | DEFERRED", register)
        self.assertIn("Production on-prem installation | DEFERRED", register)
        self.assertIn("PROD-01", register)
        self.assertIn("Do not apply Terraform", register)


if __name__ == "__main__":
    unittest.main()
