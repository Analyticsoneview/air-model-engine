import unittest
from unittest.mock import patch

from app.market_intelligence import build_market_intelligence_pulse


class MarketIntelligencePulseTests(unittest.TestCase):
    @patch("app.market_intelligence.nse_data_rows")
    @patch("app.market_intelligence.nse_data_status")
    def test_aggregates_latest_official_eod_breadth(self, status, rows):
        status.return_value = {
            "markets": {"CM": {"last_date": "2026-11-13"}},
            "updated_at": "2026-11-13T21:00:00+05:30",
        }
        rows.return_value = [
            {"close": 110, "previous_close": 100},
            {"close": 90, "previous_close": 100},
            {"close": 100, "previous_close": 100},
            {"close": None, "previous_close": 100},
        ]

        result = build_market_intelligence_pulse()

        self.assertEqual(result["data_type"], "EOD")
        self.assertEqual(result["as_of"], "2026-11-13")
        self.assertEqual(result["breadth"]["advances"], 1)
        self.assertEqual(result["breadth"]["declines"], 1)
        self.assertEqual(result["breadth"]["unchanged"], 1)
        self.assertEqual(result["breadth"]["total"], 3)
        self.assertEqual(result["breadth"]["advance_decline_ratio"], 1.0)
        self.assertEqual(result["indices"]["status"], "unavailable")
        self.assertEqual(result["sectors"]["status"], "unavailable")
        rows.assert_called_once_with("CM", end_date="2026-11-13", instrument_type="STK", limit=5000)

    @patch("app.market_intelligence.nse_data_rows", return_value=[])
    @patch("app.market_intelligence.nse_data_status", return_value={"markets": {"CM": {}}, "updated_at": None})
    def test_reports_unavailable_when_no_nse_session_is_imported(self, _status, _rows):
        result = build_market_intelligence_pulse()
        self.assertEqual(result["freshness"], "no_imported_session")
        self.assertEqual(result["breadth"]["status"], "unavailable")
        self.assertIsNone(result["breadth"]["advances"])


if __name__ == "__main__":
    unittest.main()
