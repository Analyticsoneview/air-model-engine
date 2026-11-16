import tempfile
import unittest
from pathlib import Path

from app.nse_universe import INDEX_UNIVERSES, NSEUniverseStore, parse_index_constituents


class NSEUniverseTests(unittest.TestCase):
    def _csv(self, count: int, prefix: str = "") -> str:
        lines = ["Index Name,Index Industry,Symbol,Company Name,Series,ISIN Code"]
        for i in range(count):
            lines.append(f"NIFTY 100,Test Sector,{prefix}STOCK{i:03d},Company {i},EQ,INE{i:010d}")
        return "\n".join(lines)

    def test_official_universe_counts_are_explicit(self):
        self.assertEqual(INDEX_UNIVERSES["NIFTY100"]["expected_count"], 100)
        self.assertEqual(INDEX_UNIVERSES["NIFTYMIDCAP150"]["expected_count"], 150)
        self.assertEqual(INDEX_UNIVERSES["NIFTYSMALLCAP250"]["expected_count"], 250)

    def test_parser_accepts_exact_nifty100_snapshot_and_normalizes_symbols(self):
        rows = parse_index_constituents(self._csv(100), "NIFTY100")
        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[0]["symbol"], "STOCK000")
        self.assertEqual(rows[0]["company_name"], "Company 0")
        self.assertEqual(rows[0]["series"], "EQ")

    def test_parser_fails_closed_on_missing_or_duplicate_constituents(self):
        with self.assertRaisesRegex(ValueError, "expected 100"):
            parse_index_constituents(self._csv(99), "NIFTY100")
        duplicate = self._csv(100).replace("STOCK099", "STOCK000")
        with self.assertRaisesRegex(ValueError, "duplicate symbol"):
            parse_index_constituents(duplicate, "NIFTY100")

    def test_failed_refresh_preserves_last_good_universe_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEUniverseStore(str(Path(folder) / "universe.sqlite3"))
            for code in INDEX_UNIVERSES:
                rows = parse_index_constituents(
                    self._csv(int(INDEX_UNIVERSES[code]["expected_count"]), code), code
                )
                store.save_snapshot(code, rows, "https://nsearchives.nseindia.com/test.csv")

            store.record_failure("NIFTY100", "temporary NSE 503")
            status = store.status()
            self.assertEqual(status["status"], "READY")
            failed_attempt = status["required_indices"]["NIFTY100"]
            self.assertEqual(failed_attempt["status"], "READY")
            self.assertEqual(failed_attempt["last_attempt_status"], "FAILED")
            self.assertIn("temporary NSE 503", failed_attempt["last_attempt_error"])
            self.assertEqual(len(store.symbols()), 500)
            self.assertEqual(store.latest_universe()["status"], "READY")

            refreshed = parse_index_constituents(self._csv(100, "NEW"), "NIFTY100")
            store.save_snapshot("NIFTY100", refreshed, "https://nsearchives.nseindia.com/new.csv")
            success = store.status()["required_indices"]["NIFTY100"]
            self.assertEqual(success["last_attempt_status"], "SUCCEEDED")
            self.assertIsNone(success["last_attempt_error"])
            self.assertEqual(len(store.symbols()), 500)
            self.assertEqual(store.latest_universe()["status"], "READY")

    def test_failed_first_universe_download_does_not_mark_missing_snapshot_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEUniverseStore(str(Path(folder) / "universe.sqlite3"))
            store.record_failure("NIFTY100", "both official sources unavailable")
            status = store.status()["required_indices"]["NIFTY100"]
            self.assertEqual(status["status"], "FAILED")
            self.assertEqual(status["actual_count"], 0)
            self.assertEqual(status["last_attempt_status"], "FAILED")


    def test_store_marks_ready_only_after_all_three_universes_are_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NSEUniverseStore(str(Path(folder) / "universe.sqlite3"))
            self.assertEqual(store.status()["status"], "INCOMPLETE")
            for code in INDEX_UNIVERSES:
                rows = parse_index_constituents(
                    self._csv(int(INDEX_UNIVERSES[code]["expected_count"]), code), code
                )
                store.save_snapshot(code, rows, "https://nsearchives.nseindia.com/test.csv")
            status = store.status()
            self.assertEqual(status["status"], "READY")
            self.assertEqual(len(store.symbols()), 500)
            latest = store.latest_universe()
            self.assertEqual(latest["status"], "READY")
            self.assertEqual(latest["unique_symbol_count"], 500)
            self.assertEqual(set(latest["index_counts"]), {
                "NIFTY100", "NIFTY_MIDCAP150", "NIFTY_SMALLCAP250",
            })
            self.assertTrue(latest["constituents"][0]["index_memberships"])
            self.assertEqual(
                {code: item["actual_count"] for code, item in status["required_indices"].items()},
                {"NIFTY100": 100, "NIFTYMIDCAP150": 150, "NIFTYSMALLCAP250": 250},
            )


if __name__ == "__main__":
    unittest.main()
