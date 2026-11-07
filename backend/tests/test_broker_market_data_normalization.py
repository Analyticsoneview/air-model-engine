import unittest
from datetime import datetime, timezone

from app.market_data.broker_adapters import (
    _angel_interval, _decimal, _dt, _fyers_resolution, _upstox_interval,
)


class BrokerMarketDataNormalizationTests(unittest.TestCase):
    def test_provider_interval_mappings(self):
        self.assertEqual(_upstox_interval("5minute"), ("minutes", 5))
        self.assertEqual(_upstox_interval("day"), ("days", 1))
        self.assertEqual(_fyers_resolution("15minute"), "15")
        self.assertEqual(_fyers_resolution("day"), "D")
        self.assertEqual(_angel_interval("60minute"), "ONE_HOUR")
        self.assertEqual(_angel_interval("day"), "ONE_DAY")

    def test_epoch_milliseconds_are_normalized_to_utc(self):
        stamp = _dt(1_700_000_000_000)
        self.assertEqual(stamp.tzinfo, timezone.utc)
        self.assertEqual(stamp.timestamp(), 1_700_000_000)

    def test_naive_broker_timestamps_are_assumed_india_market_time(self):
        stamp = _dt("2026-11-07T09:15:00")
        self.assertEqual(stamp.isoformat(), "2026-11-07T03:45:00+00:00")

    def test_invalid_decimal_does_not_escape_normalizer(self):
        self.assertIsNone(_decimal("not-a-price"))
        self.assertEqual(str(_decimal("123.45")), "123.45")


if __name__ == "__main__":
    unittest.main()
