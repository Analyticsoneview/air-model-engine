import unittest

from app.air_qoc_universe import parse_dhan_instrument_master


class DhanUniverseParserTests(unittest.TestCase):
    def test_builds_unique_stock_and_index_underlyings_from_detailed_master(self):
        csv_text = """EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,UNDERLYING_SECURITY_ID,UNDERLYING_SYMBOL,SM_EXPIRY_DATE,LOT_SIZE,OPTION_TYPE
NSE,D,90001,OPTSTK,2885,RELIANCE,2026-11-26,250,CE
NSE,D,90002,OPTSTK,2885,RELIANCE,2026-12-31,250,PE
NSE,D,90003,OPTIDX,13,NIFTY,2026-11-12,65,CE
BSE,D,90004,OPTIDX,51,SENSEX,2026-11-13,20,PE
NSE,E,2885,EQUITY,,,,, 
"""
        result = parse_dhan_instrument_master(csv_text)
        self.assertEqual(result["stock_underlying_count"], 1)
        self.assertEqual(result["index_underlying_count"], 1)
        self.assertEqual(result["total_underlying_count"], 2)
        reliance = next(x for x in result["underlyings"] if x["symbol"] == "RELIANCE")
        self.assertEqual(reliance["security_id"], 2885)
        self.assertEqual(reliance["exchange_segment"], "NSE_EQ")
        self.assertEqual(reliance["expiries"], ["2026-11-26", "2026-12-31"])
        self.assertTrue(reliance["validated"])

    def test_conflicting_underlying_ids_are_flagged_not_silently_accepted(self):
        csv_text = """EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,UNDERLYING_SECURITY_ID,UNDERLYING_SYMBOL,SM_EXPIRY_DATE
NSE,D,1,OPTSTK,2885,RELIANCE,2026-11-26
NSE,D,2,OPTSTK,9999,RELIANCE,2026-12-31
"""
        result = parse_dhan_instrument_master(csv_text)
        item = result["underlyings"][0]
        self.assertTrue(item["id_conflict"])
        self.assertFalse(item["validated"])

    def test_rejects_csv_without_security_id_column(self):
        with self.assertRaises(ValueError):
            parse_dhan_instrument_master("EXCH_ID,SEGMENT,INSTRUMENT\nNSE,D,OPTSTK\n")


if __name__ == "__main__":
    unittest.main()
