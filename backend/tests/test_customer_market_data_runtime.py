import unittest

from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount
from app.market_data.customer_runtime import CustomerMarketDataRuntime


class FakeBrokerAdapter:
    def __init__(self, provider, hub):
        self.provider_code = provider
        self.hub = hub
        self.authenticated = 0

    async def authenticate(self, account_id):
        self.authenticated += 1

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
