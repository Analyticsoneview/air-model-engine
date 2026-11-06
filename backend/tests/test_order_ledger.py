import tempfile
import unittest
from pathlib import Path

from app.brokers.base import BrokerOrder
from app.services.order_ledger import DurableOrderLedger


class DurableOrderLedgerTests(unittest.TestCase):
    def test_result_survives_restart_and_is_account_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "orders.sqlite3")
            first = DurableOrderLedger(path)
            order = BrokerOrder("dhan", "acct-1", "12345", "ACCEPTED",
                               {"exchange_order_id": "12345"})
            first.record(order, "intent-1")
            first.close()

            second = DurableOrderLedger(path)
            restored = second.get("dhan", "acct-1", "intent-1")
            self.assertEqual(restored, order)
            self.assertIsNone(second.get("zerodha", "acct-1", "intent-1"))
            self.assertIsNone(second.get("dhan", "acct-2", "intent-1"))
            events = second.list_events("dhan", "acct-1")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["status"], "ACCEPTED")
            second.close()


    def test_atomic_reservation_is_unique_and_persisted_as_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "orders.sqlite3")
            first = DurableOrderLedger(path)
            self.assertTrue(first.reserve("dhan", "acct-1", "intent-1", {"symbol":"TEST"}))
            self.assertFalse(first.reserve("dhan", "acct-1", "intent-1", {"symbol":"TEST"}))
            pending = first.get("dhan", "acct-1", "intent-1")
            self.assertEqual(pending.status, "PENDING")
            first.record(BrokerOrder("dhan", "acct-1", "", "UNKNOWN",
                                     {"reconcile_before_retry": True}), "intent-1")
            first.close()
            second = DurableOrderLedger(path)
            unknown = second.get("dhan", "acct-1", "intent-1")
            self.assertEqual(unknown.status, "UNKNOWN")
            self.assertEqual([e["status"] for e in second.list_events("dhan", "acct-1")],
                             ["PENDING", "UNKNOWN"])
            second.close()

    def test_list_orders_is_bounded_and_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = DurableOrderLedger(str(Path(tmp) / "orders.sqlite3"))
            ledger.record(BrokerOrder("dhan", "acct-1", "1", "PAPER_ACCEPTED", {}), "k1")
            ledger.record(BrokerOrder("zerodha", "acct-2", "2", "PAPER_ACCEPTED", {}), "k2")
            self.assertEqual(len(ledger.list_orders(broker="dhan")), 1)
            with self.assertRaises(ValueError):
                ledger.list_orders(limit=5001)
            ledger.close()


if __name__ == "__main__":
    unittest.main()
