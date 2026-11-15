import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.air_qoc_qualification import qualify_option_observations

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=IST)


def observation(at, *, spot, premium, volume, oi, bid, ask, bid_qty=100, ask_qty=120):
    return {
        "underlying_scrip": "NIFTY", "expiry": "2026-11-26", "strike": "102",
        "option_type": "CE", "security_id": "OPT-102-CE",
        "underlying_price": spot, "last_price": premium,
        "volume": volume, "open_interest": oi,
        "bid_price": bid, "ask_price": ask,
        "bid_quantity": bid_qty, "ask_quantity": ask_qty,
        "observed_at": at,
    }


class AirQocQualificationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            observation("2026-11-16T09:58:00+05:30", spot=100, premium=10,
                        volume=1000, oi=5000, bid=9.9, ask=10.1),
            observation("2026-11-16T09:59:30+05:30", spot=101, premium=11,
                        volume=1500, oi=5500, bid=10.9, ask=11.1),
        ]

    def test_high_conviction_requires_all_evidence_and_returns_transparent_breakdown(self):
        result = qualify_option_observations(self.rows, mode="LIVE", now=NOW)
        self.assertEqual(result["counts"]["HIGH_CONVICTION"], 1)
        signal = result["signals"][0]
        self.assertEqual(signal["classification"], "HIGH_CONVICTION")
        self.assertEqual(signal["score"], 97)
        self.assertEqual(signal["score_breakdown"]["underlying_direction"], 20)
        self.assertEqual(signal["premium_change_pct"], 10.0)
        self.assertEqual(signal["volume_delta"], 500)
        self.assertEqual(signal["oi_delta"], 500)
        self.assertAlmostEqual(signal["otm_pct"], 0.99, places=2)
        self.assertEqual(signal["stop_loss_reference"], 7.7)
        self.assertEqual(signal["targets_reference"]["plus_300_percent"], 44.0)
        self.assertEqual(signal["gate_failures"], [])

    def test_single_snapshot_is_rejected_not_inferred_as_a_signal(self):
        result = qualify_option_observations(self.rows[:1], mode="LIVE", now=NOW)
        signal = result["signals"][0]
        self.assertEqual(signal["classification"], "REJECT")
        self.assertIn("SECOND_OBSERVATION_REQUIRED", signal["gate_failures"])
        self.assertIn("UNDERLYING_DIRECTION_NOT_CONFIRMED", signal["gate_failures"])

    def test_stale_and_wrong_direction_data_are_rejected(self):
        stale = [dict(row, observed_at="2026-11-16T09:00:00+05:30") for row in self.rows]
        result = qualify_option_observations(stale, mode="LIVE", now=NOW)
        self.assertIn("STALE_OR_WRONG_SESSION_DATA", result["signals"][0]["gate_failures"])
        wrong = [dict(self.rows[0]), dict(self.rows[1], underlying_price=99)]
        result = qualify_option_observations(wrong, mode="LIVE", now=NOW)
        self.assertIn("UNDERLYING_DIRECTION_NOT_CONFIRMED", result["signals"][0]["gate_failures"])

    def test_bad_spread_and_zero_quote_quantity_fail_liquidity_gate(self):
        bad = [dict(self.rows[0]), dict(self.rows[1], bid_price=8, ask_price=12, bid_quantity=0)]
        result = qualify_option_observations(bad, mode="LIVE", now=NOW)
        self.assertIn("TWO_SIDED_LIQUIDITY_FAILED", result["signals"][0]["gate_failures"])

    def test_put_requires_falling_underlying_and_otm_put_strike(self):
        put_rows = [
            dict(row, option_type="PE", strike="98", underlying_price=spot,
                 last_price=premium, security_id="OPT-98-PE")
            for row, spot, premium in zip(self.rows, (100, 99), (10, 11))
        ]
        result = qualify_option_observations(put_rows, mode="LIVE", now=NOW)
        self.assertEqual(result["signals"][0]["classification"], "HIGH_CONVICTION")

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            qualify_option_observations(self.rows, mode="INTRADAY", now=NOW)


if __name__ == "__main__":
    unittest.main()
