import os
import unittest
from unittest.mock import patch

from app import model_engine_api


class CustomerStrategyFeedTests(unittest.TestCase):
    def test_customer_receives_published_strategy_feed_with_only_own_overrides(self):
        published = [
            {"signal_id": "shared-1", "entry_price": 10},
            {"signal_id": "shared-2", "entry_price": 20},
        ]
        own = [
            {"signal_id": "shared-1", "entry_price": 11},
            {"signal_id": "customer-only", "entry_price": 30},
        ]

        def list_signals(customer_id, limit):
            return published if customer_id == "publisher" else own

        with patch.dict(os.environ, {"AIR_OPERATOR_CUSTOMER_IDS": "publisher,admin2"}), \
             patch.object(model_engine_api._ledger, "list_signals", side_effect=list_signals):
            rows = model_engine_api._strategy_rows_for_customer("customer-1", 100)

        by_id = {row["signal_id"]: row for row in rows}
        self.assertEqual(by_id["shared-1"]["entry_price"], 11)
        self.assertEqual(by_id["shared-2"]["entry_price"], 20)
        self.assertEqual(by_id["customer-only"]["entry_price"], 30)


if __name__ == "__main__":
    unittest.main()
