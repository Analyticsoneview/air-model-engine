import unittest

from app.brokers.catalog import get_broker_catalog, is_supported_broker


class BrokerCatalogTests(unittest.TestCase):
    def test_all_five_agreed_providers_are_present_and_not_claimed_live(self):
        catalog = get_broker_catalog()
        agreed_providers = {"angelone", "dhan", "zerodha", "upstox", "fyers"}
        by_code = {row["code"]: row for row in catalog}
        self.assertTrue(agreed_providers.issubset(by_code))
        self.assertTrue(all(
            by_code[code]["authorization_ready"] is False
            for code in agreed_providers
        ))

    def test_provider_codes_are_normalized(self):
        self.assertTrue(is_supported_broker(" Dhan "))
        self.assertFalse(is_supported_broker("unknown"))


if __name__ == "__main__":
    unittest.main()
