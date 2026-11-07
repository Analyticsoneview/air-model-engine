import unittest

from app.orb_strategy import OrbSignalEngine


def tick(symbol: str, stamp: str, price: float) -> dict:
    return {"symbol": symbol, "ltp": price, "exchange_time": f"2026-11-06T{stamp}+05:30"}


class OrbSignalEngineTests(unittest.TestCase):
    def test_afternoon_entry_is_immediate_on_first_tick_above_range(self):
        engine = OrbSignalEngine(["NIFTY"])
        engine.on_tick(tick("NIFTY", "12:57:00", 100))
        engine.on_tick(tick("NIFTY", "12:59:59", 105))
        self.assertEqual(engine.snapshot()["signals"], [])
        engine.on_tick(tick("NIFTY", "13:00:00", 105.05))
        signals = engine.snapshot()["signals"]
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["strategy"], "ORB_AFTERNOON")
        self.assertEqual(signals[0]["entry_price"], "105.05")
        self.assertEqual(signals[0]["stop_loss"], "100")

    def test_morning_requires_breakout_retest_and_confirmation_close(self):
        engine = OrbSignalEngine(["NIFTY"])
        engine.on_tick(tick("NIFTY", "09:18:00", 100))
        engine.on_tick(tick("NIFTY", "09:22:59", 99))
        engine.on_tick(tick("NIFTY", "09:22:59", 105))
        # The partial 09:21–09:24 candle overlaps the range and is ignored.
        engine.on_tick(tick("NIFTY", "09:23:30", 106))
        engine.on_tick(tick("NIFTY", "09:24:00", 106))
        engine.on_tick(tick("NIFTY", "09:26:59", 107))
        engine.on_tick(tick("NIFTY", "09:27:00", 106))
        self.assertEqual(engine.snapshot()["signals"], [])  # breakout only
        engine.on_tick(tick("NIFTY", "09:28:00", 104))
        engine.on_tick(tick("NIFTY", "09:29:59", 105))
        engine.on_tick(tick("NIFTY", "09:30:00", 106))
        self.assertEqual(engine.snapshot()["signals"], [])  # retest only
        engine.on_tick(tick("NIFTY", "09:31:00", 106))
        engine.on_tick(tick("NIFTY", "09:32:59", 107))
        engine.on_tick(tick("NIFTY", "09:33:00", 106))
        signals = engine.snapshot()["signals"]
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["strategy"], "ORB_MORNING")
        self.assertEqual(signals[0]["entry_price"], "107")
        self.assertEqual(signals[0]["stop_loss"], "106")
        self.assertEqual(signals[0]["entry_at"], "2026-11-06T09:33:00+05:30")

    def test_only_one_orb_position_can_be_open_at_a_time(self):
        engine = OrbSignalEngine(["NIFTY", "BANKNIFTY"])
        engine.on_tick(tick("NIFTY", "12:57:00", 100))
        engine.on_tick(tick("BANKNIFTY", "12:57:00", 200))
        engine.on_tick(tick("NIFTY", "12:59:59", 105))
        engine.on_tick(tick("BANKNIFTY", "12:59:59", 205))
        engine.on_tick(tick("NIFTY", "13:00:00", 106))
        engine.on_tick(tick("BANKNIFTY", "13:00:00", 206))
        self.assertEqual(len(engine.snapshot()["signals"]), 1)
        self.assertEqual(engine.snapshot()["signals"][0]["symbol"], "NIFTY")

    def test_afternoon_stop_is_the_range_candle_low(self):
        engine = OrbSignalEngine(["BANKNIFTY"])
        engine.on_tick(tick("BANKNIFTY", "12:57:00", 500))
        engine.on_tick(tick("BANKNIFTY", "12:58:00", 498))
        engine.on_tick(tick("BANKNIFTY", "12:59:59", 510))
        engine.on_tick(tick("BANKNIFTY", "13:00:00", 511))
        engine.on_tick(tick("BANKNIFTY", "13:00:01", 497))
        signal = engine.snapshot()["signals"][0]
        self.assertEqual(signal["stop_loss"], "498")
        self.assertEqual(signal["status"], "SL_HIT")


if __name__ == "__main__":
    unittest.main()
