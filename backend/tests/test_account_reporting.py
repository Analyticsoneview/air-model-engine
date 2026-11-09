import unittest
from unittest.mock import patch

from app.account_reporting import AccountReporting


class AccountReportingTests(unittest.TestCase):
    def setUp(self):
        self.service = AccountReporting(":memory:")

    def tearDown(self):
        self.service.close()

    def test_email_verification_requires_valid_code(self):
        with patch.object(AccountReporting, "_send_email") as send_email:
            self.service.request_verification("customer-1", "reports@example.com")
            self.assertEqual(send_email.call_count, 1)
            self.assertFalse(self.service.recipient("customer-1")["verified"])
            # OTP is never stored in plaintext; an invalid code cannot verify it.
            with self.assertRaises(ValueError):
                self.service.confirm_verification("customer-1", "000000")
            self.assertFalse(self.service.recipient("customer-1")["verified"])

