import unittest

from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount
from app.market_data.customer_runtime import CustomerMarketDataRuntime


class FakeBrokerAdapter:
    def __init__(self, provider, hub):
        self.provider = provider
        self.provider_code = provider
        self.hub = hub
        self.authenticated = 0

    async def authenticate(self, account_id):
        self.authenticated += 1
        if self.provider == "broken":
            raise RuntimeError("broker unavailable")

    async def close(self):
        return None

    def health(self):
        return {"feed_state": "connected"}


class CustomerMarketDataRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_paid_customer_uses_own_broker_while_standard_customer_uses_nse(self):
        accounts = CustomerAccountDirectory(":memory:")
        accounts.add(CustomerTradingAccount("paid-1", "dhan", "D001"))
        accounts.set_market_data_access("paid-1", "PAID", True)
        accounts.set_market_data_selection("paid-1", "dhan", "D001")
        runtime = CustomerMarketDataRuntime(
            accounts, None,
            lambda customer, provider, account, hub: FakeBrokerAdapter(provider, hub),
        )

        paid = await runtime.get_service("paid-1")
        standard = await runtime.get_service("standard-1")

        self.assertEqual(paid.router.resolve("historical")[0][0:2], ("dhan", "D001"))
        self.assertEqual(paid.router.resolve("live")[0][0:2], ("dhan", "D001"))
        self.assertEqual(standard.router.resolve("historical")[0][0:2],
                         ("nse_bhavcopy", "official"))
        self.assertEqual(standard.router.resolve("live"), [])
        self.assertIsNot(paid.hub, standard.hub)
        accounts.close()


    async def test_unavailable_selected_broker_uses_nse_and_reports_fallback(self):
        accounts = CustomerAccountDirectory(":memory:")
        accounts.add(CustomerTradingAccount("paid-2", "broken", "B001"))
        accounts.set_market_data_access("paid-2", "PAID", True)
        accounts.set_market_data_selection("paid-2", "broken", "B001")
        runtime = CustomerMarketDataRuntime(
            accounts, None,
            lambda customer, provider, account, hub: FakeBrokerAdapter(provider, hub),
        )

        service = await runtime.get_service("paid-2")
        self.assertEqual(service.router.resolve("historical")[0][0:2],
                         ("nse_bhavcopy", "official"))
        self.assertEqual(service.router.resolve("live"), [])
        status = service.customer_market_data_status
        self.assertEqual(status["requested_source"], {
            "provider": "broken", "account_id": "B001"
        })
        self.assertEqual(status["effective_source"], "NSE")
        self.assertEqual(status["connection_status"], "unavailable")
        self.assertTrue(status["fallback_active"])
        accounts.close()

    async def test_standard_customer_defaults_to_nse_without_broker_selection(self):
        accounts = CustomerAccountDirectory(":memory:")
        accounts.add(CustomerTradingAccount("standard-2", "dhan", "D002"))
        accounts.set_market_data_access("standard-2", "STANDARD", False)
        runtime = CustomerMarketDataRuntime(
            accounts, None,
            lambda customer, provider, account, hub: FakeBrokerAdapter(provider, hub),
        )

        service = await runtime.get_service("standard-2")
        self.assertEqual(service.router.resolve("historical")[0][0:2],
                         ("nse_bhavcopy", "official"))
        status = service.customer_market_data_status
        self.assertEqual(status["connection_status"], "not_requested")
        self.assertIsNone(status["requested_source"])
        self.assertFalse(status["fallback_active"])
        accounts.close()

    async def test_non_paid_customer_cannot_activate_assigned_broker(self):
        accounts = CustomerAccountDirectory(":memory:")
        accounts.add(CustomerTradingAccount("standard-1", "dhan", "D001"))
        accounts.set_market_data_access("standard-1", "STANDARD", False)
        runtime = CustomerMarketDataRuntime(
            accounts, None,
            lambda customer, provider, account, hub: FakeBrokerAdapter(provider, hub),
        )
        service = await runtime.get_service("standard-1")
        self.assertEqual(service.router.resolve("historical")[0][0],
                         "nse_bhavcopy")
        accounts.close()


if __name__ == "__main__":
    unittest.main()
