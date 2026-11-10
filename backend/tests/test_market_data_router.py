import unittest
from unittest.mock import AsyncMock

from app.market_data.router import MarketDataRouter


class FakeAdapter:
    provider_code = "fake"

    def __init__(self):
        self.authenticate = AsyncMock()
        self.close = AsyncMock()


class MarketDataRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_channels_use_only_selected_main_account(self):
        router = MarketDataRouter()
        adapter = FakeAdapter()
        router.register("acct-1", adapter)

        await router.set_main_account("fake", "acct-1")

        self.assertEqual(len(router.resolve("historical")), 1)
        self.assertEqual(len(router.resolve("live")), 1)
        self.assertIs(router.resolve("historical")[0][2], adapter)
        self.assertIs(router.resolve("live")[0][2], adapter)
        self.assertEqual(router.status()["historical_source"], {"provider": "fake", "account_id": "acct-1"})
        self.assertEqual(router.status()["live_source"], {"provider": "fake", "account_id": "acct-1"})

    async def test_switch_keeps_old_source_until_new_source_is_authenticated(self):
        router = MarketDataRouter()
        first, second = FakeAdapter(), FakeAdapter()
        first.provider_code = second.provider_code = "fake"
        events = []
        first.close.side_effect = lambda: events.append("close-old")
        second.authenticate.side_effect = lambda account: events.append("auth-new")
        router.register("one", first)
        router.register("two", second)

        await router.set_main_account("fake", "one")
        await router.set_main_account("fake", "two")

        self.assertEqual(events, ["auth-new", "close-old"])
        self.assertEqual(router.status()["active_data_account"]["account_id"], "two")
        self.assertIs(router.resolve("historical")[0][2], second)
        self.assertIs(router.resolve("live")[0][2], second)

    async def test_failed_switch_retains_previous_source_without_failover(self):
        router = MarketDataRouter()
        first, second = FakeAdapter(), FakeAdapter()
        first.provider_code = second.provider_code = "fake"
        second.authenticate.side_effect = RuntimeError("auth rejected")
        router.register("one", first)
        router.register("two", second)
        await router.set_main_account("fake", "one")

        with self.assertRaises(RuntimeError):
            await router.set_main_account("fake", "two")

        self.assertIs(router.resolve("historical")[0][2], first)
        self.assertIs(router.resolve("live")[0][2], first)
        self.assertEqual(router.status()["connection_state"]["historical"], "connected")
        self.assertFalse(router.status()["automatic_provider_failover"])


if __name__ == "__main__":
    unittest.main()
