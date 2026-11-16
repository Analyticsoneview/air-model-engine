from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANAGER = ROOT / "scripts" / "air_manager.py"
RELEASE_SCRIPT = ROOT / "scripts" / "release" / "build_release.py"


class DeploymentManagerTests(unittest.TestCase):
    def run_manager(self, *args):
        env = os.environ.copy()
        env.pop("AWS_REGION", None)
        env.pop("AWS_DEFAULT_REGION", None)
        return subprocess.run(
            [sys.executable, str(MANAGER), *args],
            cwd=ROOT, env=env, text=True, capture_output=True, timeout=30,
        )

    def test_validate_onprem_profile_without_docker_or_aws(self):
        result = self.run_manager("--profile", "onprem-single", "validate")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "VALID")
        self.assertEqual(payload["provider"], "on_prem")
        self.assertEqual(payload["deployment_status"], "READY_FOR_LOCAL_PREFLIGHT")

    def test_validate_aws_profiles_without_aws_credentials(self):
        for profile in ("aws-private-single", "aws-saas-multi"):
            with self.subTest(profile=profile):
                result = self.run_manager("--profile", profile, "validate")
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["status"], "VALID")
                self.assertEqual(payload["deployment_status"], "DEFERRED_UNTIL_AWS_ENVIRONMENT")

    def test_aws_install_reports_deferred_and_creates_no_resources(self):
        result = self.run_manager("--profile", "aws-saas-multi", "install")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "DEFERRED")
        self.assertIn("no AWS resources were created", payload["message"].lower())

    def test_shell_wrapper_defaults_aws_profile_to_validation_only(self):
        result = subprocess.run(
            ["bash", str(ROOT / "AIRDEPLOY.sh"), "aws-private-single"],
            cwd=ROOT, text=True, capture_output=True, timeout=30,
            env={key: value for key, value in os.environ.items() if key not in {"AWS_REGION", "AWS_DEFAULT_REGION"}},
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "VALID")
        self.assertEqual(payload["deployment_status"], "DEFERRED_UNTIL_AWS_ENVIRONMENT")

    def test_installers_expose_noninteractive_upgrade_controls(self):
        shell = (ROOT / "AIRSTART.sh").read_text(encoding="utf-8")
        powershell = (ROOT / "AIRSTART.ps1").read_text(encoding="utf-8")
        self.assertIn("AIR_START_PULL_BASE_IMAGES", shell)
        self.assertIn("AIR_START_SKIP_OPEN", shell)
        self.assertIn("AIR_START_SKIP_PROFILE", shell)
        self.assertIn("AIR_START_PULL_BASE_IMAGES", powershell)
        self.assertIn("AIR_START_SKIP_OPEN", powershell)
        self.assertIn("AIR_START_SKIP_PROFILE", powershell)
        self.assertIn("docker compose -f compose.local.yml config --quiet", shell)
        self.assertIn("docker compose -f compose.local.yml config --quiet", powershell)
        self.assertNotIn("docker run --rm", shell)
        self.assertNotIn("python:3.12-slim", shell)
        self.assertIn("scripts/generate_local_secrets.py", shell)
        self.assertIn("scripts/generate_local_secrets.py", powershell)

    def test_manager_help_exposes_lifecycle_and_diagnostic_actions(self):
        result = subprocess.run(
            [sys.executable, str(MANAGER), "--help"],
            cwd=ROOT, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for action in ("validate", "doctor", "install", "upgrade", "status", "diagnose", "package"):
            self.assertIn(action, result.stdout)


class ReleasePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("air_release_builder", RELEASE_SCRIPT)
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)

    def test_release_bundle_contains_service_inventory_and_checksums_but_no_runtime_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            output = Path(temporary) / "dist"
            root.mkdir()
            for item in self.builder.INCLUDE:
                path = root / item
                if item in {".gitignore", "backend/Dockerfile"} or path.suffix:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"fixture:{item}\n", encoding="utf-8")
                else:
                    path.mkdir(parents=True, exist_ok=True)
                    (path / "placeholder.txt").write_text(f"fixture:{item}\n", encoding="utf-8")
            (root / ".air-secrets").mkdir()
            (root / ".air-secrets" / "jwt_secret").write_text("must-not-package", encoding="utf-8")
            (root / ".air-local.env").write_text("SECRET=value", encoding="utf-8")
            (root / "backend" / "app" / "local.sqlite3").write_bytes(b"database")
            (root / "mobile" / "android").mkdir(parents=True, exist_ok=True)
            (root / "mobile" / "android" / "key.properties").write_text("storePassword=secret", encoding="utf-8")
            (root / "backend" / "app" / "production.env").write_text("SECRET=value", encoding="utf-8")
            (root / "deploy" / "aws" / "terraform").mkdir(parents=True, exist_ok=True)
            (root / "deploy" / "aws" / "terraform" / "production.tfvars").write_text("secret=value", encoding="utf-8")
            (root / "deploy" / ".terraform").mkdir(parents=True)
            (root / "deploy" / ".terraform" / "provider.bin").write_bytes(b"provider")

            archive = self.builder.build_release("test-16.0", output, root=root)
            self.builder.verify_release(archive)
            with tarfile.open(archive, "r:gz") as bundle:
                names = bundle.getnames()
                manifest_name = next(name for name in names if name.endswith("/RELEASE-MANIFEST.json"))
                manifest = json.load(bundle.extractfile(manifest_name))
                self.assertTrue(any(s["name"] == "fastapi" for s in manifest["services"]))
                self.assertTrue(any(s["name"] == "postgresql" for s in manifest["services"]))
                self.assertTrue(any(s["name"] == "redis" for s in manifest["services"]))
                self.assertTrue(any(s["name"] == "rabbitmq" for s in manifest["services"]))
                self.assertTrue(any(s["name"] == "workflow-worker" for s in manifest["services"]))
                self.assertTrue(any(s["name"] == "pwa" for s in manifest["services"]))
                self.assertTrue(any(s["name"] == "caddy" for s in manifest["services"]))
                joined = "\n".join(names)
                self.assertNotIn(".air-secrets", joined)
                self.assertNotIn(".air-local.env", joined)
                self.assertNotIn("local.sqlite3", joined)
                self.assertNotIn("key.properties", joined)
                self.assertNotIn("production.env", joined)
                self.assertNotIn("production.tfvars", joined)
                self.assertNotIn(".terraform", joined)
            self.assertTrue(Path(str(archive) + ".sha256").is_file())


if __name__ == "__main__":
    unittest.main()
