import asyncio
import unittest

from app.market_data.dhan_adapter import DhanMarketDataAdapter
from app.market_data.contracts import MarketInstrument


class FakeFeed:
    def __init__(self):
        self.subscribed = []
        self.unsubscribed = []
    async def subscribe(self, instruments):
        self.subscribed.extend(instruments)
    async def unsubscribe(self, instruments):
        self.unsubscribed.extend(instruments)
    async def close(self):
        pass
    async def messages(self):
        yield {
            "type": "full", "exchange_segment_id": 2, "security_id": 123,
            "ltp": 101.5, "exchange_time": "2026-11-06T10:00:00+00:00",
            "volume": 1000, "open_interest": 200,
            "depth": [{"bid_price": 101.4, "ask_price": 101.6}],
        }


class FakeHub:
    def __init__(self):
        self.ticks = []
    async def publish(self, tick):
        self.ticks.append(tick)


class DhanAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscribe_unsubscribe_and_symbol_mapping(self):
        hub = FakeHub()
        adapter = DhanMarketDataAdapter("10001", "token", hub)
        feed = FakeFeed()
        adapter._feed = feed
        instrument = MarketInstrument(
            exchange="NSE", symbol="NIFTY FUT", token="123", segment="NSE_FNO"
        )
        await adapter.subscribe([instrument])
        await adapter.unsubscribe([instrument])
        self.assertEqual(feed.subscribed[0]["security_id"], "123")
        self.assertEqual(feed.unsubscribed[0]["exchange_segment"], "NSE_FNO")
        self.assertEqual(adapter._symbols[("NSE_FNO", "123")], "NIFTY FUT")

    async def test_binary_feed_packets_are_normalized_into_hub_ticks(self):
        hub = FakeHub()
        adapter = DhanMarketDataAdapter("10001", "token", hub)
        feed = FakeFeed()
        adapter._feed = feed
        adapter.account_id = "10001"
        adapter._symbols[("NSE_FNO", "123")] = "NIFTY FUT"
        received = asyncio.Event()

        class SignallingHub(FakeHub):
            async def publish(self, tick):
                await super().publish(tick)
                received.set()

        hub = SignallingHub()
        adapter.hub = hub
        reader = asyncio.create_task(adapter._read_feed())
        try:
            await asyncio.wait_for(received.wait(), timeout=2)
        finally:
            reader.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await reader

        self.assertEqual(len(hub.ticks), 1)
        tick = hub.ticks[0]
        self.assertEqual(tick["provider"], "dhan")
        self.assertEqual(tick["symbol"], "NIFTY FUT")
        self.assertEqual(tick["open_interest"], 200)
        self.assertEqual(tick["bid"], 101.4)


if __name__ == "__main__":
    unittest.main()
