import unittest

from app.model_engine_settlement_comparison import _broker_signal, _build_rows, _settlement_delta


class SettlementComparisonTests(unittest.TestCase):
    def test_positive_broker_variance_is_sell_watch(self):
        self.assertEqual(_broker_signal(105, 100), (5.0, 5.0, "OPTION CLOSE UP", "SELL WATCH"))

    def test_negative_broker_variance_is_buy_watch(self):
        self.assertEqual(_broker_signal(95, 100), (-5.0, -5.0, "OPTION CLOSE DOWN", "BUY WATCH"))

    def test_equal_or_missing_values_do_not_signal(self):
        self.assertEqual(_broker_signal(100, 100), (0.0, 0.0, "UNCHANGED", "NO SIGNAL"))
        self.assertEqual(_broker_signal(None, 100), (None, None, "DATA MISSING", "NO SIGNAL"))
        self.assertEqual(_broker_signal(100, None), (None, None, "DATA MISSING", "NO SIGNAL"))


    def test_option_ce_and_pe_keep_separate_settlement_history_and_actions(self):
        current = [
            {"symbol": "ABC", "expiry": "2026-11-26", "strike": 100,
             "option_type": "CE", "trade_date": "2026-11-06", "settlement": 10,
             "volume": 100, "open_interest": 200},
            {"symbol": "ABC", "expiry": "2026-11-26", "strike": 100,
             "option_type": "PE", "trade_date": "2026-11-06", "settlement": 12,
             "volume": 100, "open_interest": 200},
        ]
        previous = [
            {"symbol": "ABC", "expiry": "2026-11-26", "strike": 100,
             "option_type": "CE", "trade_date": "2026-11-05", "settlement": 9},
        ]
        rows = _build_rows("FO", current, previous, {
            ("ABC", "2026-11-26", "100", "CE"): 11,
            ("ABC", "2026-11-26", "100", "PE"): 11,
        })
        self.assertEqual(rows[0]["action"], "SELL WATCH")
        self.assertEqual(rows[0]["settlement_direction"], "UP")
        self.assertEqual(rows[1]["action"], "BUY WATCH")
        self.assertEqual(rows[1]["previous_nse_settlement"], None)
        self.assertEqual(rows[1]["settlement_direction"], "DATA MISSING")

    def test_stock_close_is_explicit_cash_market_settlement_reference_when_settlement_missing(self):
        current = [{"symbol": "INFY", "trade_date": "2026-11-06", "close": 1500}]
        previous = [{"symbol": "INFY", "trade_date": "2026-11-05", "close": 1490}]
        rows = _build_rows("CM", current, previous, {("INFY",): 1510})
        self.assertEqual(rows[0]["settlement_direction"], "UP")
        self.assertEqual(rows[0]["nse_settlement_basis"], "NSE CM CLOSE (CASH MARKET REFERENCE)")
        self.assertEqual(rows[0]["action"], "—")
        self.assertEqual(rows[0]["broker_variance"], 10.0)

    def test_previous_settlement_direction_is_separate(self):
        self.assertEqual(_settlement_delta(105, 100), (5.0, "UP"))
        self.assertEqual(_settlement_delta(95, 100), (-5.0, "DOWN"))
        self.assertEqual(_settlement_delta(100, 100), (0.0, "UNCHANGED"))
        self.assertEqual(_settlement_delta(None, 100), (None, "DATA MISSING"))


if __name__ == "__main__":
    unittest.main()
