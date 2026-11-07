import os
import unittest
from unittest.mock import patch

import jwt

from app.security import create_access_token


class MobileIdentityTokenTests(unittest.TestCase):
    def test_approved_mobile_identity_is_stable_customer_subject(self):
        secret = "test-only-air-jwt-secret-with-at-least-32-bytes"
        mobile = "+919876543210"
        with patch.dict(os.environ, {"AIR_JWT_SECRET": secret}, clear=False):
            token = create_access_token(
                mobile,
                expires_minutes=60,
                session_id="device-session-id",
            )
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer="air-model-engine",
            audience="air-api",
        )
        self.assertEqual(payload["sub"], mobile)
        self.assertEqual(payload["jti"], "device-session-id")


if __name__ == "__main__":
    unittest.main()
