import tempfile
import unittest
from pathlib import Path

from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount


class CustomerAccountDirectoryTests(unittest.TestCase):
    def test_multiple_accounts_per_broker_and_multiple_brokers(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = CustomerAccountDirectory(str(Path(temp) / "accounts.sqlite3"))
            directory.add(CustomerTradingAccount("customer-1", "Dhan", "D001", True))
            directory.add(CustomerTradingAccount("customer-1", "Dhan", "D002", True))
            directory.add(CustomerTradingAccount("customer-1", "Zerodha", "Z001", False))

            rows = directory.list_for_customer("customer-1")
            self.assertEqual(len(rows), 3)
            self.assertEqual({r.broker for r in rows}, {"dhan", "zerodha"})
            self.assertEqual(sum(r.broker == "dhan" for r in rows), 2)
            directory.close()

    def test_admin_inventory_lists_accounts_across_customers(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = CustomerAccountDirectory(str(Path(temp) / "accounts.sqlite3"))
            directory.add(CustomerTradingAccount("+919000000001", "Dhan", "D001", False))
            directory.add(CustomerTradingAccount("+919000000002", "Dhan", "D002", False))
            directory.add(CustomerTradingAccount("+919000000001", "Zerodha", "Z001", False))
            rows = directory.list_all()
            self.assertEqual(len(rows), 3)
            self.assertEqual(
                {(row.customer_id, row.broker, row.account_id) for row in rows},
                {
                    ("+919000000001", "dhan", "D001"),
                    ("+919000000002", "dhan", "D002"),
                    ("+919000000001", "zerodha", "Z001"),
                },
            )
            directory.close()

    def test_account_ownership_is_unique_and_tenant_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = CustomerAccountDirectory(str(Path(temp) / "accounts.sqlite3"))
            directory.add(CustomerTradingAccount("customer-1", "Dhan", "D001", True))
            with self.assertRaises(ValueError):
                directory.add(CustomerTradingAccount("customer-2", "Dhan", "D001", True))
            with self.assertRaises(PermissionError):
                directory.authorize_order_target("customer-2", "Dhan", "D001")
            directory.authorize_order_target("customer-1", "Dhan", "D001")
            directory.close()

    def test_order_permission_can_be_revoked_and_persists(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "accounts.sqlite3")
            directory = CustomerAccountDirectory(path)
            directory.add(CustomerTradingAccount("customer-1", "Dhan", "D001", True))
            directory.set_order_permission("customer-1", "Dhan", "D001", False)
            with self.assertRaises(PermissionError):
                directory.authorize_order_target("customer-1", "Dhan", "D001")
            directory.close()

            reopened = CustomerAccountDirectory(path)
            self.assertFalse(reopened.list_for_customer("customer-1")[0].enabled_for_orders)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
