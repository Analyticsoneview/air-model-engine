import unittest
from datetime import datetime, timedelta, timezone

from app.installation_readiness import evaluate_workflow_runtime


class InstallationReadinessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)

    def _worker(self, **overrides):
        worker = {
            "worker_id": "air-worker-1",
            "component": "workflow-runtime",
            "status": "RUNNING",
            "last_seen": (self.now - timedelta(seconds=10)).isoformat(),
            "details": {
                "rabbitmq_connected": True,
                "components": {
                    "workflow-outbox": True,
                    "workflow-scheduler": True,
                    "workflow-executor": True,
                    "workflow-operations-monitor": True,
                },
            },
        }
        worker.update(overrides)
        return worker

    def test_requires_fresh_rabbitmq_connected_worker_and_live_components(self):
        result = evaluate_workflow_runtime([self._worker()], now=self.now)
        self.assertEqual(result["status"], "HEALTHY")
        self.assertTrue(result["healthy"])

    def test_rejects_stale_heartbeat(self):
        worker = self._worker(last_seen=(self.now - timedelta(seconds=46)).isoformat())
        result = evaluate_workflow_runtime([worker], now=self.now)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["workers"][0]["age_seconds"], 46.0)

    def test_rejects_disconnected_broker_or_dead_runtime_component(self):
        disconnected = self._worker(details={
            "rabbitmq_connected": False, "components": {"workflow-executor": True},
        })
        dead_component = self._worker(details={
            "rabbitmq_connected": True, "components": {"workflow-executor": False},
        })
        self.assertFalse(evaluate_workflow_runtime([disconnected], now=self.now)["healthy"])
        self.assertFalse(evaluate_workflow_runtime([dead_component], now=self.now)["healthy"])

    def test_no_worker_heartbeat_is_not_ready(self):
        result = evaluate_workflow_runtime([], now=self.now)
        self.assertEqual(result["status"], "NOT_SEEN")
        self.assertFalse(result["healthy"])


if __name__ == "__main__":
    unittest.main()
