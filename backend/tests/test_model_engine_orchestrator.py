import os
import unittest
from unittest.mock import patch

from app import model_engine_orchestrator as orchestrator


class FakeLedger:
    def __init__(self):
        self.closed = False

    def list_signals(self, customer_id, limit):
        return [{"signal_id": f"{customer_id}:one"}]

    def close(self):
        self.closed = True


class ModelEngineOrchestratorTests(unittest.TestCase):
    def test_missing_operator_customers_blocks_strategy_completion(self):
        with patch.dict(os.environ, {"AIR_OPERATOR_CUSTOMER_IDS": ""}, clear=False):
            result = orchestrator.run_post_import_strategy_cycle("2026-11-07")
        self.assertEqual(result["status"], "NOT_CONFIGURED")
        self.assertEqual(result["customers"], 0)

    def test_runs_expiry78_recovered_and_master_for_each_customer(self):
        fake_ledger = FakeLedger()
        with patch.dict(os.environ, {"AIR_OPERATOR_CUSTOMER_IDS": "customer-a,customer-b"}):
            with patch.object(orchestrator, "ModelEngineLedger", return_value=fake_ledger):
                with patch.object(orchestrator, "evaluate_expiry78_rows", return_value=[
                    {"expiry78": {"trades": [{"classification": "EXPIRED"}]}}
                ]) as expiry78:
                    with patch.object(orchestrator, "evaluate_original366_rows", return_value=[
                        {"original366": {"trades": [{"classification": "EXPIRED_WIN"}]}}
                    ]) as original366:
                        with patch.object(orchestrator, "build_master", return_value={
                            "count": 1, "counts": {"SURVIVOR": 1}
                        }) as master:
                            result = orchestrator.run_post_import_strategy_cycle("2026-11-07")

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["customers"], 2)
        self.assertEqual([row["customer"] for row in result["results"]],
                         ["customer-a", "customer-b"])
        self.assertEqual(result["results"][0]["EXPIRY78"]["expired"], 1)
        self.assertEqual(result["results"][0]["RECOVERED"]["expired"], 1)
        self.assertEqual(expiry78.call_count, 2)
        self.assertEqual(original366.call_count, 2)
        self.assertEqual(master.call_count, 2)
        self.assertTrue(fake_ledger.closed)
        self.assertEqual(result["not_run"]["RECOVERY"], "DEFERRED_NO_EXECUTOR")


if __name__ == "__main__":
    unittest.main()
