import os
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from app.credential_vault import CredentialVault
from app.security import create_access_token, hash_password, verify_password
import jwt


class SecurityFoundationTests(unittest.TestCase):
    def test_password_hash_and_verification(self):
        encoded = hash_password("correct horse battery staple")
        self.assertNotEqual(encoded, "correct horse battery staple")
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong password", encoded))

    def test_jwt_has_expiry_issuer_and_audience(self):
        os.environ["AIR_JWT_SECRET"] = "test-secret-value-that-is-at-least-32-characters"
        token = create_access_token("customer-123")
        payload = jwt.decode(token, os.environ["AIR_JWT_SECRET"], algorithms=["HS256"],
                             issuer="air-model-engine", audience="air-api")
        self.assertEqual(payload["sub"], "customer-123")
        self.assertIn("exp", payload)

    def test_vault_encrypts_and_scopes_credentials(self):
        key = Fernet.generate_key().decode()
        os.environ["AIR_CREDENTIAL_KEY"] = key
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "vault.sqlite3")
            vault = CredentialVault(path)
            vault.put("customer-a", "Dhan", "A001", {"api_key": "secret", "access_token": "token"})
            self.assertEqual(vault.get("customer-a", "dhan", "A001")["api_key"], "secret")
            with self.assertRaises(KeyError):
                vault.get("customer-b", "dhan", "A001")
            vault.close()
            raw = Path(path).read_bytes()
            self.assertNotIn(b"secret", raw)
            self.assertNotIn(b"token", raw)


if __name__ == "__main__":
    unittest.main()
