import unittest

from app.account_reporting import AccountReporting


class AccountReportingTests(unittest.TestCase):
    def setUp(self):
        self.service = AccountReporting(":memory:")

    def tearDown(self):
        self.service.close()

    def test_email_verification_requires_valid_code(self):
        sent = []
        original = AccountReporting._send_email
        AccountReporting._send_email = staticmethod(lambda email, subject, body, attachments=None:
                                                    sent.append((email, subject, body)))
        try:
            self.service.request_verification("customer-1", "reports@example.com")
            self.assertEqual(len(sent), 1)
            self.assertFalse(self.service.recipient("customer-1")["verified"])
            # OTP is never stored in plaintext; an invalid code cannot verify it.
            with self.assertRaises(ValueError):
                self.service.confirm_verification("customer-1", "000000")
            self.assertFalse(self.service.recipient("customer-1")["verified"])
        finally:
            AccountReporting._send_email = original

    def test_position_pnl_uses_broker_fields_without_estimation(self):
        summary = self.service._pnl_summary([
            {"realizedProfit": 1200, "unrealizedProfit": -200, "netProfit": 1000},
            {"realizedProfit": 300, "unrealizedProfit": 50, "netProfit": 350},
        ])
        self.assertEqual(summary["realized_pnl"], 1500.0)
        self.assertEqual(summary["unrealized_pnl"], -150.0)
        self.assertEqual(summary["net_pnl"], 1350.0)

    def test_missing_broker_pnl_fields_remain_unavailable(self):
        summary = self.service._pnl_summary([{"tradingsymbol": "NIFTY", "quantity": 50}])
        self.assertIsNone(summary["realized_pnl"])
        self.assertIsNone(summary["unrealized_pnl"])
        self.assertIsNone(summary["net_pnl"])


if __name__ == "__main__":
    unittest.main()
