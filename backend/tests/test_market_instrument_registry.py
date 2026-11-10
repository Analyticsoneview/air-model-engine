import unittest

from app.market_data.instrument_registry import MarketInstrumentDirectory


class MarketInstrumentDirectoryTests(unittest.TestCase):
    def test_provider_account_scoped_mapping_and_search(self):
        directory = MarketInstrumentDirectory(":memory:")
        saved = directory.upsert(
            "zerodha", "AB1234", exchange="NSE", symbol="SBIN",
            token="779521", segment="NSE_EQ",
        )
        self.assertEqual(saved["token"], "779521")
        self.assertEqual(directory.search("zerodha", "AB1234", "sbin")[0]["symbol"], "SBIN")
        self.assertEqual(directory.search("upstox", "AB1234", "sbin"), [])
        self.assertEqual(directory.search("zerodha", "OTHER", "sbin"), [])
        directory.close()

    def test_mapping_can_be_updated_and_removed(self):
        directory = MarketInstrumentDirectory(":memory:")
        directory.upsert(
            "fyers", "FY123", exchange="NSE", symbol="INFY",
            token="NSE:INFY-EQ", segment="NSE_EQ",
        )
        updated = directory.upsert(
            "fyers", "FY123", exchange="NSE", symbol="INFY",
            token="NSE:INFY-EQ", segment="NSE_EQ", lot_size=1,
        )
        self.assertEqual(updated["lot_size"], 1)
        self.assertTrue(directory.delete("fyers", "FY123", "NSE:INFY-EQ"))
        self.assertFalse(directory.delete("fyers", "FY123", "NSE:INFY-EQ"))
        directory.close()


if __name__ == "__main__":
    unittest.main()
