import unittest

from app.model_engine_settlement_comparison import _broker_signal, _settlement_delta


class SettlementComparisonTests(unittest.TestCase):
    def test_positive_broker_variance_is_sell_watch(self):
        self.assertEqual(_broker_signal(105, 100), (5.0, 5.0, "OPTION CLOSE UP", "SELL WATCH"))

    def test_negative_broker_variance_is_buy_watch(self):
        self.assertEqual(_broker_signal(95, 100), (-5.0, -5.0, "OPTION CLOSE DOWN", "BUY WATCH"))

    def test_equal_or_missing_values_do_not_signal(self):
        self.assertEqual(_broker_signal(100, 100), (0.0, 0.0, "UNCHANGED", "NO SIGNAL"))
        self.assertEqual(_broker_signal(None, 100), (None, None, "DATA MISSING", "NO SIGNAL"))
        self.assertEqual(_broker_signal(100, None), (None, None, "DATA MISSING", "NO SIGNAL"))

    def test_previous_settlement_direction_is_separate(self):
        self.assertEqual(_settlement_delta(105, 100), (5.0, "UP"))
        self.assertEqual(_settlement_delta(95, 100), (-5.0, "DOWN"))
        self.assertEqual(_settlement_delta(100, 100), (0.0, "UNCHANGED"))
        self.assertEqual(_settlement_delta(None, 100), (None, "DATA MISSING"))


if __name__ == "__main__":
    unittest.main()
