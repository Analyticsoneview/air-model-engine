import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount
from app.brokers.registry import BrokerRegistry
from app.brokers.base import OrderRequest
from app.services.execution import ExecutionService
from app.services.order_ledger import DurableOrderLedger


def order():
    return OrderRequest(
        account_id="A001", exchange="NSE", symbol="TEST", token="123",
        side="BUY", order_type="LIMIT", product="INTRADAY", quantity=1,
        price=Decimal("100"), trigger_price=None, validity="DAY", tag="AIR",
        idempotency_key="intent-unique",
    )


class DurableExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_paper_intent_is_reused_after_service_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ledger.sqlite3")
            directory = CustomerAccountDirectory(":memory:")
            directory.add(CustomerTradingAccount("customer-a", "dhan", "A001", True))

            first = ExecutionService(BrokerRegistry(), {}, directory, DurableOrderLedger(db))
            first_result = await first.submit(
                "dhan", order(), customer_id="customer-a",
                confirmed_by_user=True, paper=True,
            )

            second = ExecutionService(BrokerRegistry(), {}, directory, DurableOrderLedger(db))
            second_result = await second.submit(
                "dhan", order(), customer_id="customer-a",
                confirmed_by_user=True, paper=True,
            )
            self.assertEqual(first_result, second_result)
            self.assertEqual(second_result.status, "PAPER_ACCEPTED")
            directory.close()


if __name__ == "__main__":
    unittest.main()
