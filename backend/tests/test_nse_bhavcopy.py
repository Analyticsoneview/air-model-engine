import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.nse_bhavcopy import (
    NSEBhavcopyStore, _archive_url, _normalize, _subtract_months,
)


class NSEBhavcopyTests(unittest.TestCase):
    def test_three_calendar_month_start_date_handles_short_months(self):
        self.assertEqual(_subtract_months(date(2026, 11, 30), 3), date(2026, 8, 30))
        self.assertEqual(_subtract_months(date(2026, 5, 31), 3), date(2026, 2, 28))

    def test_official_udiff_archive_urls(self):
        day = date(2026, 11, 6)
        self.assertEqual(
            _archive_url("CM", day),
            "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20261106_F_0000.csv.zip",
        )
        self.assertEqual(
            _archive_url("FO", day),
            "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20261106_F_0000.csv.zip",
        )

    def test_cm_row_normalizes_equity_ohlcv(self):
        row = _normalize("CM", "2026-11-06", {
            "FinInstrmId": "1594", "TckrSymb": "INFY", "FinInstrmTp": "STK",
            "OpnPric": "1500.00", "HghPric": "1520.00", "LwPric": "1490.00",
            "ClsPric": "1510.00", "TtlTradgVol": "123456", "TtlTrfVal": "186500000",
            "ISIN": "INE009A01021",
        })
        self.assertEqual(row["symbol"], "INFY")
        self.assertEqual(row["close"], 1510.0)
        self.assertEqual(row["volume"], 123456.0)
        self.assertEqual(row["market"], "CM")

    def test_fo_row_normalizes_expiry_strike_option_and_oi(self):
        row = _normalize("FO", "2026-11-06", {
            "FinInstrmId": "987654", "TckrSymb": "NIFTY", "FinInstrmTp": "OPTIDX",
            "XpryDt": "2026-11-27", "StrkPric": "26000", "OptnTp": "CE",
            "ClsPric": "120.50", "TtlTradgVol": "45678",
            "OpnIntrst": "234567", "ChngInOpnIntrst": "1234",
        })
        self.assertEqual(row["symbol"], "NIFTY")
        self.assertEqual(row["instrument_type"], "OPTIDX")
        self.assertEqual(row["expiry"], "2026-11-27")
        self.assertEqual(row["strike"], 26000.0)
        self.assertEqual(row["option_type"], "CE")
        self.assertEqual(row["open_interest"], 234567.0)

    def test_store_queries_by_market_symbol_and_instrument_type(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEBhavcopyStore(str(Path(folder) / "nse.sqlite3"))
            cm = [{
                "FinInstrmId": "1594", "TckrSymb": "INFY", "FinInstrmTp": "STK",
                "OpnPric": "1500", "HghPric": "1520", "LwPric": "1490",
                "ClsPric": "1510", "TtlTradgVol": "123456",
            }]
            fo = [
                {"FinInstrmId": "1", "TckrSymb": "NIFTY", "FinInstrmTp": "OPTIDX",
                 "XpryDt": "2026-11-27", "StrkPric": "26000", "OptnTp": "CE",
                 "ClsPric": "120", "TtlTradgVol": "500", "OpnIntrst": "1000"},
                {"FinInstrmId": "2", "TckrSymb": "NIFTY", "FinInstrmTp": "FUTIDX",
                 "XpryDt": "2026-11-27", "ClsPric": "26050", "TtlTradgVol": "700",
                 "OpnIntrst": "2000"},
            ]
            store.save_rows("CM", "2026-11-06", cm)
            store.save_rows("FO", "2026-11-06", fo)
            self.assertEqual(len(store.query("CM", symbol="INFY")), 1)
            self.assertEqual(len(store.query("FO", symbol="NIFTY", instrument_type="OPT")), 1)
            self.assertEqual(len(store.query("FO", symbol="NIFTY", instrument_type="FUT")), 1)


if __name__ == "__main__":
    unittest.main()
