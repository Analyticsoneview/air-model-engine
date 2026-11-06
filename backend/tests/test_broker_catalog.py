import unittest

from app.brokers.catalog import get_broker_catalog, is_supported_broker


class BrokerCatalogTests(unittest.TestCase):
    def test_all_five_agreed_providers_are_present_and_not_claimed_live(self):
        catalog = get_broker_catalog()
        self.assertEqual(
            {row["code"] for row in catalog},
            {"angelone", "dhan", "zerodha", "upstox", "fyers"},
        )
        self.assertTrue(all(row["authorization_ready"] is False for row in catalog))

    def test_provider_codes_are_normalized(self):
        self.assertTrue(is_supported_broker(" Dhan "))
        self.assertFalse(is_supported_broker("unknown"))


if __name__ == "__main__":
    unittest.main()
