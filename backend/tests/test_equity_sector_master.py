import unittest

from app.market_data.instrument_registry import MarketInstrumentDirectory


class EquitySectorMasterTests(unittest.TestCase):
    def test_four_level_classification_is_symbol_keyed_and_effective_dated(self):
        directory = MarketInstrumentDirectory(":memory:")
        try:
            directory.upsert_sector(
                exchange="NSE", symbol="ABC", company_name="ABC Limited",
                macro_sector="Industrials", sector="Capital Goods",
                industry="Electrical Equipment", basic_industry="Heavy Electrical Equipment",
                effective_from="2025-01-01", source="NSE Indices classification",
                classification_status="VERIFIED",
                source_reference="https://www.niftyindices.com/resources/industry-classification",
            )
            old = directory.sector_as_of("NSE", "ABC", "2025-06-01")
            self.assertEqual(old["macro_sector"], "Industrials")
            self.assertEqual(old["industry"], "Electrical Equipment")
            self.assertEqual(old["basic_industry"], "Heavy Electrical Equipment")
            self.assertEqual(old["classification_status"], "VERIFIED")
            self.assertIsNone(directory.sector_as_of("NSE", "UNKNOWN", "2025-06-01"))
        finally:
            directory.close()

    def test_unverified_classification_is_explicit(self):
        directory = MarketInstrumentDirectory(":memory:")
        try:
            row = directory.upsert_sector(
                exchange="NSE", symbol="XYZ", sector="UNVERIFIED",
                effective_from="2026-01-01", source="Pending source verification",
                classification_status="UNVERIFIED",
            )
            self.assertEqual(row["classification_status"], "UNVERIFIED")
        finally:
            directory.close()


if __name__ == "__main__":
    unittest.main()
