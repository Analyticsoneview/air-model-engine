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



    def test_broker_market_data_is_denied_without_paid_entitlement(self):
        directory = CustomerAccountDirectory(":memory:")
        directory.add(CustomerTradingAccount("customer-1", "Dhan", "D001", False))
        with self.assertRaisesRegex(PermissionError, "paid entitlement"):
            directory.set_market_data_selection("customer-1", "dhan", "D001")
        directory.close()

    def test_paid_market_data_selection_is_customer_owned_and_persistent(self):
        directory = CustomerAccountDirectory(":memory:")
        directory.add(CustomerTradingAccount("customer-1", "Dhan", "D001", False))
        directory.add(CustomerTradingAccount("customer-2", "Dhan", "D002", False))
        directory.set_market_data_access("customer-1", "PAID", True)
        selected = directory.set_market_data_selection("customer-1", "dhan", "D001")
        self.assertEqual(selected["provider"], "dhan")
        self.assertEqual(selected["account_id"], "D001")
        with self.assertRaises(PermissionError):
            directory.set_market_data_selection("customer-1", "dhan", "D002")
        directory.set_market_data_access("customer-1", "STANDARD", False)
        self.assertIsNone(directory.get_market_data_selection("customer-1"))
        self.assertEqual(directory.get_market_data_access("customer-1")["tier"], "STANDARD")
        directory.close()

    def test_market_data_entitlement_survives_database_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "accounts.sqlite3")
            directory = CustomerAccountDirectory(path)
            directory.set_market_data_access("customer-1", "PAID", True)
            directory.close()
            reopened = CustomerAccountDirectory(path)
            access = reopened.get_market_data_access("customer-1")
            self.assertEqual(access["tier"], "PAID")
            self.assertTrue(access["broker_data_enabled"])
            reopened.close()

if __name__ == "__main__":
    unittest.main()
