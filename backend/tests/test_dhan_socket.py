import json
import unittest

from app.brokers.dhan_socket import DhanFeedSocket


class FakeSocket:
    def __init__(self):
        self.sent = []
    async def send(self, value):
        self.sent.append(value)
    async def close(self):
        pass


class DhanSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscriptions_are_chunked_at_100(self):
        feed = DhanFeedSocket("10001", "token", mode="full")
        fake = FakeSocket()
        feed._socket = fake
        instruments = [
            {"exchange_segment": "NSE_EQ", "security_id": str(i + 1)}
            for i in range(205)
        ]
        await feed.subscribe(instruments)
        payloads = [json.loads(item) for item in fake.sent]
        self.assertEqual([p["InstrumentCount"] for p in payloads], [100, 100, 5])
        self.assertTrue(all(p["RequestCode"] == 21 for p in payloads))

    async def test_deduplicates_and_validates_instruments(self):
        feed = DhanFeedSocket("10001", "token", mode="quote")
        fake = FakeSocket()
        feed._socket = fake
        await feed.subscribe([
            {"exchange_segment": "NSE_FNO", "security_id": "123"},
            {"exchange_segment": "NSE_FNO", "security_id": "123"},
        ])
        payload = json.loads(fake.sent[0])
        self.assertEqual(payload["InstrumentCount"], 1)
        self.assertEqual(payload["RequestCode"], 17)
        with self.assertRaises(ValueError):
            await feed.subscribe([{"exchange_segment": "BAD", "security_id": "1"}])

    async def test_subscription_requires_connection_and_mode_is_validated(self):
        feed = DhanFeedSocket("10001", "token")
        with self.assertRaises(RuntimeError):
            await feed.subscribe([{"exchange_segment": "NSE_EQ", "security_id": "1"}])
        with self.assertRaises(ValueError):
            DhanFeedSocket("10001", "token", mode="unsupported")


if __name__ == "__main__":
    unittest.main()
