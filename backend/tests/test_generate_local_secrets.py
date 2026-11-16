from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts" / "generate_local_secrets.py"


class GenerateLocalSecretsTests(unittest.TestCase):
    def test_creates_required_secrets_and_preserves_existing_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ".air-secrets"
            root.mkdir()
            (root / "jwt_secret").write_text("existing-jwt-secret", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(GENERATOR), str(root)],
                cwd=ROOT, text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual((root / "jwt_secret").read_text(encoding="utf-8"), "existing-jwt-secret")
            required = (
                "jwt_secret", "credential_key", "admin_api_key", "admin_mfa_key",
                "postgres_password", "redis_password", "rabbitmq_password",
                "database_url", "redis_url", "telegram_bot_token",
            )
            for name in required:
                with self.subTest(name=name):
                    self.assertTrue((root / name).is_file())
            pg = (root / "postgres_password").read_text(encoding="utf-8").strip()
            redis = (root / "redis_password").read_text(encoding="utf-8").strip()
            self.assertIn(f":{pg}@postgres:", (root / "database_url").read_text(encoding="utf-8"))
            self.assertIn(f":{redis}@redis:", (root / "redis_url").read_text(encoding="utf-8"))
            self.assertEqual((root / "telegram_bot_token").read_text(encoding="utf-8"), "")

    def test_missing_argument_defaults_to_repository_local_secret_directory(self):
        source = GENERATOR.read_text(encoding="utf-8")
        self.assertIn('sys.argv[1] if len(sys.argv) > 1 else ".air-secrets"', source)


if __name__ == "__main__":
    unittest.main()
