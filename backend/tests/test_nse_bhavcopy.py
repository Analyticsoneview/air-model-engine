import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.model_engine_ledger import ModelEngineLedger
from app.nse_bhavcopy import (
    NSEBhavcopyStore, _archive_url, _normalize, _parse_nse_calendar, _subtract_months, _date_range, _configured_history_months, nse_bootstrap_is_ready, _bootstrap_end_date,
)


class NSEBhavcopyTests(unittest.TestCase):
    def test_calendar_month_start_date_handles_short_months(self):
        self.assertEqual(_subtract_months(date(2026, 11, 30), 3), date(2026, 8, 30))
        self.assertEqual(_subtract_months(date(2026, 5, 31), 3), date(2026, 2, 28))


    def test_initial_history_configuration_defaults_to_at_least_twelve_months(self):
        previous = os.environ.get("AIR_NSE_HISTORY_MONTHS")
        try:
            os.environ.pop("AIR_NSE_HISTORY_MONTHS", None)
            self.assertEqual(_configured_history_months(), 12)
            os.environ["AIR_NSE_HISTORY_MONTHS"] = "3"
            self.assertEqual(_configured_history_months(), 12)
            os.environ["AIR_NSE_HISTORY_MONTHS"] = "18"
            self.assertEqual(_configured_history_months(), 18)
            os.environ["AIR_NSE_HISTORY_MONTHS"] = "99"
            self.assertEqual(_configured_history_months(), 60)
            os.environ["AIR_NSE_HISTORY_MONTHS"] = "invalid"
            self.assertEqual(_configured_history_months(), 12)
        finally:
            if previous is None:
                os.environ.pop("AIR_NSE_HISTORY_MONTHS", None)
            else:
                os.environ["AIR_NSE_HISTORY_MONTHS"] = previous

    def test_initial_bootstrap_excludes_current_day_until_eod_window(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ist = ZoneInfo("Asia/Kolkata")
        self.assertEqual(
            _bootstrap_end_date(datetime(2026, 11, 16, 10, 0, tzinfo=ist)),
            date(2026, 11, 15),
        )
        self.assertEqual(
            _bootstrap_end_date(datetime(2026, 11, 16, 21, 0, tzinfo=ist)),
            date(2026, 11, 16),
        )

    def test_readiness_rejects_legacy_three_month_ready_marker(self):
        self.assertFalse(nse_bootstrap_is_ready({"status": "READY"}))
        self.assertFalse(nse_bootstrap_is_ready({
            "status": "READY", "history_months": 3,
            "archive_coverage_pct": 100, "paired_session_coverage_pct": 100,
        }))

    def test_readiness_requires_full_archive_and_paired_session_coverage(self):
        complete = {
            "status": "READY", "history_months": 12,
            "archive_coverage_pct": 100, "paired_session_coverage_pct": 100,
            "universe": {
                "status": "READY",
                "indices": {
                    "NIFTY100": {"status": "READY", "actual_count": 100},
                    "NIFTYMIDCAP150": {"status": "READY", "actual_count": 150},
                    "NIFTYSMALLCAP250": {"status": "READY", "actual_count": 250},
                },
            },
            "symbol_coverage": {
                "status": "READY", "expected_symbols": 500, "missing_count": 0,
            },
            "strategy_run": {"status": "COMPLETED"},
        }
        self.assertTrue(nse_bootstrap_is_ready(complete))
        incomplete = dict(complete, archive_coverage_pct=99.9)
        self.assertFalse(nse_bootstrap_is_ready(incomplete))
        incomplete = dict(complete, paired_session_coverage_pct=99.9)
        self.assertFalse(nse_bootstrap_is_ready(incomplete))
        incomplete = dict(complete, status="PARTIAL")
        self.assertFalse(nse_bootstrap_is_ready(incomplete))
        incomplete = dict(complete, universe={"status": "FAILED", "indices": {}})
        self.assertFalse(nse_bootstrap_is_ready(incomplete))
        incomplete = dict(complete, strategy_run={"status": "FAILED"})
        self.assertFalse(nse_bootstrap_is_ready(incomplete))
        incomplete = dict(complete, symbol_coverage={
            "status": "BLOCKED", "expected_symbols": 500, "missing_count": 1,
        })
        self.assertFalse(nse_bootstrap_is_ready(incomplete))

    def test_per_symbol_coverage_blocks_missing_symbols_and_warns_on_short_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEBhavcopyStore(str(Path(folder) / "nse.sqlite3"))
            for offset in range(50):
                day = date.fromordinal(date(2026, 1, 1).toordinal() + offset).isoformat()
                rows = [{
                    "FinInstrmId": f"A{offset}", "TckrSymb": "AAA", "FinInstrmTp": "STK",
                    "ClsPric": "100", "TtlTradgVol": "1000",
                }]
                if offset < 20:
                    rows.append({
                        "FinInstrmId": f"B{offset}", "TckrSymb": "BBB", "FinInstrmTp": "STK",
                        "ClsPric": "100", "TtlTradgVol": "1000",
                    })
                store.save_rows("CM", day, rows)

            blocked = store.symbol_coverage(
                ["AAA", "BBB", "CCC"], "2026-01-01", "2026-03-01",
                expected_sessions=50, minimum_sessions=45,
            )
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertEqual(blocked["missing_symbols"], ["CCC"])
            self.assertEqual(blocked["below_minimum_symbols"], ["BBB"])

            warning = store.symbol_coverage(
                ["AAA", "BBB"], "2026-01-01", "2026-03-01",
                expected_sessions=50, minimum_sessions=45,
            )
            self.assertEqual(warning["status"], "READY_WITH_WARNINGS")
            self.assertEqual(warning["expected_symbols"], 2)

    def test_nse_calendar_normalizes_cm_and_fo_separately(self):
        calendar = _parse_nse_calendar({
            "CM": [{"tradingDate": "10-Nov-2026", "weekDay": "Tuesday", "description": "Diwali"}],
            "FO": [{"tradingDate": "24-Nov-2026", "weekDay": "Tuesday", "description": "Guru Nanak Jayanti"}],
        }, 2026)
        self.assertEqual(calendar["segments"]["CM"][0]["date"], "2026-11-10")
        self.assertEqual(calendar["segments"]["FO"][0]["date"], "2026-11-24")

    def test_date_range_excludes_nse_holidays(self):
        days = list(_date_range(date(2026, 11, 9), date(2026, 11, 11), {"2026-11-10"}))
        self.assertEqual(days, [date(2026, 11, 9), date(2026, 11, 11)])

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


    def test_session_reconciliation_detects_partial_count_and_cleans_both_markets(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEBhavcopyStore(str(Path(folder) / "nse.sqlite3"))
            day = "2026-11-06"
            cm_rows = [
                {"FinInstrmId": "1", "TckrSymb": "INFY", "FinInstrmTp": "STK"},
                {"FinInstrmId": "2", "TckrSymb": "TCS", "FinInstrmTp": "STK"},
            ]
            fo_rows = [
                {"FinInstrmId": "3", "TckrSymb": "NIFTY", "FinInstrmTp": "OPTIDX",
                 "XpryDt": "2026-11-27", "StrkPric": "26000", "OptnTp": "CE"},
            ]
            store.save_rows("CM", day, cm_rows)
            store.save_rows("FO", day, fo_rows)
            store.set_file_status("CM", day, "IMPORTED", 2, source_record_count=2)
            store.set_file_status("FO", day, "IMPORTED", 1, source_record_count=2)

            result = store.reconcile_session(day, ("CM", "FO"))

            self.assertEqual(result["status"], "PARTIAL")
            self.assertTrue(result["repair_triggered"])
            self.assertEqual(store.actual_record_count("CM", day), 0)
            self.assertEqual(store.actual_record_count("FO", day), 0)
            self.assertEqual(store.file_status("CM", day)["status"], "PARTIAL")
            self.assertEqual(store.file_status("FO", day)["status"], "PARTIAL")

    def test_session_reconciliation_accepts_matching_nse_and_database_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEBhavcopyStore(str(Path(folder) / "nse.sqlite3"))
            day = "2026-11-06"
            rows = [
                {"FinInstrmId": "1", "TckrSymb": "INFY", "FinInstrmTp": "STK"},
                {"FinInstrmId": "2", "TckrSymb": "TCS", "FinInstrmTp": "STK"},
            ]
            store.save_rows("CM", day, rows)
            store.set_file_status("CM", day, "IMPORTED", 2, source_record_count=2)

            result = store.reconcile_session(day, ("CM",))

            self.assertEqual(result["status"], "COMPLETE")
            self.assertFalse(result["repair_triggered"])
            self.assertEqual(store.actual_record_count("CM", day), 2)

    def test_cleanup_expired_fo_removes_expired_contracts_and_preserves_source_count_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEBhavcopyStore(str(Path(folder) / "nse.sqlite3"))
            day = "2026-11-06"
            rows = [
                {"FinInstrmId": "1", "TckrSymb": "NIFTY", "FinInstrmTp": "OPTIDX",
                 "XpryDt": "2026-10-29", "StrkPric": "26000", "OptnTp": "CE"},
                {"FinInstrmId": "2", "TckrSymb": "NIFTY", "FinInstrmTp": "OPTIDX",
                 "XpryDt": "2026-11-26", "StrkPric": "26000", "OptnTp": "PE"},
            ]
            store.save_rows("FO", day, rows)
            store.set_file_status("FO", day, "IMPORTED", 2, source_record_count=2)

            cleanup = store.cleanup_expired_fo(date(2026, 11, 7))

            self.assertEqual(cleanup["removed_records"], 1)
            self.assertEqual(cleanup["removed_contract_keys"], 1)
            active = store.query("FO")
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["expiry"], "2026-11-26")
            status = store.file_status("FO", day)
            self.assertEqual(status["expired_removed_count"], 1)
            integrity = store.reconcile_session(day, ("FO",))
            self.assertEqual(integrity["status"], "COMPLETE")
            self.assertFalse(integrity["repair_triggered"])

    def test_cleanup_snapshots_expired_fo_daily_bars_into_strategy_ledger_before_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            previous_path = os.environ.get("AIR_MODEL_LEDGER_DB_PATH")
            ledger_path = str(Path(folder) / "model-ledger.sqlite3")
            os.environ["AIR_MODEL_LEDGER_DB_PATH"] = ledger_path
            try:
                ledger = ModelEngineLedger(ledger_path)
                ledger.upsert("customer-1", {
                    "signal_id": "EXPIRY78:NIFTY:2026-10-29:26000:CE",
                    "classification": "EXPIRED",
                    "signal_date": "2026-10-27",
                    "entry_date": "2026-10-28",
                    "symbol": "NIFTY",
                    "instrument_type": "INDEX",
                    "option_type": "CE",
                    "expiry": "2026-10-29",
                    "strike": 26000,
                    "entry_price": 5,
                    "quantity": 50,
                    "evidence": {"strategy_memberships": ["EXPIRY78"]},
                })
                ledger.close()

                store = NSEBhavcopyStore(str(Path(folder) / "nse.sqlite3"))
                daily_rows = [
                    {"FinInstrmId": "1", "TckrSymb": "NIFTY", "FinInstrmTp": "OPTIDX",
                     "XpryDt": "2026-10-29", "StrkPric": "26000", "OptnTp": "CE",
                     "OpnPric": "5", "HghPric": "6", "LwPric": "4", "ClsPric": "5.5",
                     "TtlTradgVol": "1000", "UndrlygPric": "26010"},
                    {"FinInstrmId": "1", "TckrSymb": "NIFTY", "FinInstrmTp": "OPTIDX",
                     "XpryDt": "2026-10-29", "StrkPric": "26000", "OptnTp": "CE",
                     "OpnPric": "5.5", "HghPric": "7", "LwPric": "5", "ClsPric": "6.5",
                     "TtlTradgVol": "1500", "UndrlygPric": "26020"},
                ]
                for day, raw in zip(("2026-10-27", "2026-10-28"), daily_rows):
                    store.save_rows("FO", day, [raw])
                    store.set_file_status("FO", day, "IMPORTED", 1, source_record_count=1)

                cleanup = store.cleanup_expired_fo(date(2026, 11, 7))

                self.assertEqual(cleanup["strategy_snapshot"]["status"], "SNAPSHOTTED")
                self.assertEqual(cleanup["strategy_snapshot"]["strategy_rows_updated"], 1)
                self.assertEqual(cleanup["strategy_snapshot"]["daily_bars_attached"], 2)
                self.assertEqual(store.query("FO"), [])
                ledger = ModelEngineLedger(ledger_path)
                try:
                    saved = ledger.list_signals("customer-1")[0]
                    self.assertEqual(len(saved["evidence"]["daily_option_bars"]), 2)
                    self.assertEqual(saved["evidence"]["daily_option_bars"][1]["underlying_close"], 26020.0)
                    self.assertEqual(saved["classification"], "EXPIRED")
                    self.assertEqual(saved["pnl_points"], None)
                finally:
                    ledger.close()
            finally:
                if previous_path is None:
                    os.environ.pop("AIR_MODEL_LEDGER_DB_PATH", None)
                else:
                    os.environ["AIR_MODEL_LEDGER_DB_PATH"] = previous_path


    def test_expired_fo_cleanup_is_idempotent_and_does_not_remove_expiry_day_contracts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEBhavcopyStore(str(Path(folder) / "nse.sqlite3"))
            day = "2026-11-06"
            rows = [
                {"FinInstrmId": "1", "TckrSymb": "BANKNIFTY", "FinInstrmTp": "OPTIDX",
                 "XpryDt": "2026-11-07", "StrkPric": "58000", "OptnTp": "CE"},
            ]
            store.save_rows("FO", day, rows)
            store.set_file_status("FO", day, "IMPORTED", 1, source_record_count=1)

            first = store.cleanup_expired_fo(date(2026, 11, 7))
            second = store.cleanup_expired_fo(date(2026, 11, 7))

            self.assertEqual(first["removed_records"], 0)
            self.assertEqual(second["removed_records"], 0)
            self.assertEqual(store.actual_record_count("FO", day), 1)


    def test_duplicate_instrument_rows_are_counted_once_like_database_primary_key(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEBhavcopyStore(str(Path(folder) / "nse.sqlite3"))
            day = "2026-11-06"
            row = {"FinInstrmId": "1", "TckrSymb": "INFY", "FinInstrmTp": "STK"}
            self.assertEqual(store.save_rows("CM", day, [row, row]), 1)
            self.assertEqual(store.actual_record_count("CM", day), 1)


if __name__ == "__main__":
    unittest.main()
