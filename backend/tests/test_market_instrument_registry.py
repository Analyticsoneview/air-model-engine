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


    def test_dated_lot_size_snapshots_survive_current_master_replacement(self):
        directory = MarketInstrumentDirectory(":memory:")
        first = [{
            "exchange": "NSE", "symbol": "ABC27JAN100CE", "underlying_symbol": "ABC",
            "token": "101", "segment": "NSE_FO", "expiry": "2027-01-28",
            "strike": "100", "option_type": "CE", "lot_size": 50,
            "instrument_type": "OPTSTK",
        }]
        second = [{**first[0], "lot_size": 25}]
        directory.replace_snapshot("zerodha", "A1", first,
                                   effective_date="2026-10-01", source="official-master-v1")
        directory.replace_snapshot("zerodha", "A1", second,
                                   effective_date="2026-11-01", source="official-master-v2")
        old = directory.lot_size_as_of(
            "zerodha", "A1", symbol="ABC27JAN100CE", expiry="2027-01-28",
            strike="100", option_type="CE", as_of="2026-10-15")
        new = directory.lot_size_as_of(
            "zerodha", "A1", symbol="ABC27JAN100CE", expiry="2027-01-28",
            strike="100", option_type="CE", as_of="2026-11-15")
        self.assertEqual(old["lot_size"], 50)
        self.assertEqual(new["lot_size"], 25)
        self.assertEqual(directory.list_all("zerodha", "A1")[0]["lot_size"], 25)
        directory.close()

    def test_sector_mapping_is_effective_dated_and_source_attributed(self):
        directory = MarketInstrumentDirectory(":memory:")
        directory.upsert_sector(
            exchange="NSE", symbol="ABC", sector="Industrials",
            effective_from="2025-01-01", source="NSE sector classification",
            source_reference="sector-file-2025")
        directory.upsert_sector(
            exchange="NSE", symbol="ABC", sector="Capital Goods",
            effective_from="2026-01-01", source="NSE sector classification",
            source_reference="sector-file-2026")
        self.assertEqual(directory.sector_as_of("NSE", "ABC", "2025-06-01")["sector"],
                         "Industrials")
        current = directory.sector_as_of("NSE", "ABC", "2026-06-01")
        self.assertEqual(current["sector"], "Capital Goods")
        self.assertEqual(current["source_reference"], "sector-file-2026")
        self.assertIsNone(directory.sector_as_of("NSE", "UNKNOWN", "2026-06-01"))
        directory.close()


if __name__ == "__main__":
    unittest.main()
