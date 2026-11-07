import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.main import require_air_operator


class BrokerAccountOperatorAccessTests(unittest.TestCase):
    def test_regular_customer_is_not_an_operator(self):
        with patch.dict("os.environ", {"AIR_OPERATOR_CUSTOMER_IDS": "+919999999999"}):
            with self.assertRaises(HTTPException) as raised:
                require_air_operator("+918888888888")
        self.assertEqual(raised.exception.status_code, 403)

    def test_configured_admin_identity_is_allowed(self):
        admin = "+919999999999"
        with patch.dict("os.environ", {"AIR_OPERATOR_CUSTOMER_IDS": admin}):
            self.assertEqual(require_air_operator(admin), admin)


if __name__ == "__main__":
    unittest.main()
