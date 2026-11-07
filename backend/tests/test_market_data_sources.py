import asyncio
import tempfile
import unittest
from pathlib import Path

from app.market_data.provider_registry import MarketDataSourceRegistry
from app.market_data.router import MarketDataRouter


class FakeAdapter:
    provider_code = "fake"

    def __init__(self):
        self.authenticated = 0
        self.closed = 0

    async def authenticate(self, account_id):
        self.authenticated += 1

    async def close(self):
        self.closed += 1

    async def search_instruments(self, query, limit=100, exchange_segment=None):
        return []

    async def get_historical(self, instrument, start, end, interval):
        return []

    async def subscribe(self, instruments):
        return None

    async def unsubscribe(self, instruments):
        return None


class MarketDataSourceRegistryTests(unittest.TestCase):
    def test_historical_and_live_selections_are_independent_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sources.sqlite3")
            registry = MarketDataSourceRegistry(path)
            registry.set_source("historical", "nse_bhavcopy", None, True)
            registry.set_source("live", "dhan", "1234567890", True)
            selections = registry.selections()
            self.assertEqual(selections["historical"]["provider"], "nse_bhavcopy")
            self.assertEqual(selections["live"]["provider"], "dhan")
            registry.close()

            reopened = MarketDataSourceRegistry(path)
            self.assertTrue(reopened.selections()["historical"]["enabled"])
            self.assertEqual(reopened.selections()["live"]["account_id"], "1234567890")
            reopened.close()

    def test_catalog_only_provider_cannot_be_enabled(self):
        registry = MarketDataSourceRegistry(":memory:")
        with self.assertRaisesRegex(ValueError, "not implemented and verified"):
            registry.set_source("live", "custom_vendor", "vendor-1", True)
        registry.close()

    def test_provider_must_support_selected_channel(self):
        registry = MarketDataSourceRegistry(":memory:")
        with self.assertRaisesRegex(ValueError, "does not support"):
            registry.set_source("live", "nse_bhavcopy", None, True)
        registry.close()


class MarketDataRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_historical_and_live_can_use_different_providers(self):
        router = MarketDataRouter()
        historical = FakeAdapter()
        live = FakeAdapter()
        router.register("hist-account", historical)
        # A second provider code demonstrates that each channel can be routed
        # independently; use a small subclass for the live account.
        live.provider_code = "fake-live"
        router.register("live-account", live)

        await router.set_source("historical", "fake", "hist-account")
        await router.set_source("live", "fake-live", "live-account")

        self.assertEqual(router.resolve("historical")[0][1], "hist-account")
        self.assertEqual(router.resolve("live")[0][1], "live-account")
        self.assertEqual(historical.authenticated, 1)
        self.assertEqual(live.authenticated, 1)
        self.assertEqual(router.status()["data_connection_policy"],
                         "independent_historical_and_live_sources")

    async def test_failed_switch_retains_previous_connected_source(self):
        router = MarketDataRouter()
        current = FakeAdapter()

        class BrokenAdapter(FakeAdapter):
            async def authenticate(self, account_id):
                raise RuntimeError("invalid credentials")

        broken = BrokenAdapter()
        broken.provider_code = "broken"
        router.register("current-account", current)
        router.register("broken-account", broken)
        await router.set_source("live", "fake", "current-account")
        with self.assertRaises(RuntimeError):
            await router.set_source("live", "broken", "broken-account")
        self.assertEqual(router.resolve("live")[0][1], "current-account")
        self.assertEqual(router.status()["connection_state"]["live"], "connected")

    async def test_health_aware_failover_switches_to_first_healthy_candidate(self):
        router = MarketDataRouter()

        class HealthAdapter(FakeAdapter):
            def __init__(self, state):
                super().__init__()
                self.state = state
            def health(self):
                return {"feed_state": self.state}

        primary = HealthAdapter("stale")
        backup = HealthAdapter("connected")
        backup.provider_code = "backup"
        router.register("primary-account", primary)
        router.register("backup-account", backup)
        await router.set_source("live", "fake", "primary-account")
        await router.configure_failover(
            "live", [("backup", "backup-account")], enabled=True
        )
        result = await router.check_health("live")
        self.assertEqual(result["failover"], "switched")
        self.assertEqual(router.resolve("live")[0][1], "backup-account")
        self.assertEqual(primary.closed, 1)
        self.assertEqual(backup.authenticated, 1)

    async def test_shared_adapter_is_not_closed_when_one_channel_switches(self):
        router = MarketDataRouter()
        shared = FakeAdapter()
        alternate = FakeAdapter()
        alternate.provider_code = "alternate"
        router.register("shared-account", shared)
        router.register("alternate-account", alternate)

        await router.set_source("historical", "fake", "shared-account")
        await router.set_source("live", "fake", "shared-account")
        self.assertEqual(shared.authenticated, 1)

        await router.set_source("historical", "alternate", "alternate-account")
        self.assertEqual(shared.closed, 0)
        self.assertEqual(router.resolve("live")[0][1], "shared-account")
        self.assertEqual(router.resolve("historical")[0][1], "alternate-account")

        await router.clear_source("live")
        self.assertEqual(shared.closed, 1)


if __name__ == "__main__":
    unittest.main()
