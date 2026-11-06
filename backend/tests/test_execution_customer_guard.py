import unittest
from decimal import Decimal

from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount
from app.brokers.registry import BrokerRegistry
from app.brokers.base import OrderRequest
from app.services.execution import ExecutionService


def make_order(account_id):
    return OrderRequest(
        account_id=account_id, exchange="NSE", symbol="TEST", token="123",
        side="BUY", order_type="LIMIT", product="INTRADAY", quantity=1,
        price=Decimal("100"), trigger_price=None, validity="DAY", tag="AIR",
        idempotency_key="test-order-1",
    )


class ExecutionOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_account_paper_order_requires_customer_ownership(self):
        directory = CustomerAccountDirectory(":memory:")
        directory.add(CustomerTradingAccount("customer-a", "Dhan", "A001", True))
        service = ExecutionService(BrokerRegistry(), {}, directory)

        with self.assertRaises(PermissionError):
            await service.submit(
                "Dhan", make_order("A001"), customer_id="customer-b",
                confirmed_by_user=True, paper=True,
            )

        result = await service.submit(
            "Dhan", make_order("A001"), customer_id="customer-a",
            confirmed_by_user=True, paper=True,
        )
        self.assertEqual(result.status, "PAPER_ACCEPTED")
        directory.close()


if __name__ == "__main__":
    unittest.main()
