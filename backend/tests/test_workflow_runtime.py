import pytest

from app.workflow_engine import WorkflowStore


def test_worker_heartbeat_upserts_component_and_keeps_started_at(tmp_path):
    store = WorkflowStore(str(tmp_path / "runtime.sqlite3"))
    try:
        store.record_worker_heartbeat(
            worker_id="worker-1", component="workflow-runtime", status="STARTING",
            details={"rabbitmq_connected": False}, started_at="2026-11-16T00:00:00+00:00",
        )
        store.record_worker_heartbeat(
            worker_id="worker-1", component="workflow-runtime", status="RUNNING",
            details={"rabbitmq_connected": True}, started_at="2026-11-16T00:00:00+00:00",
        )
        rows = store.list_worker_heartbeats()
        assert len(rows) == 1
        assert rows[0]["status"] == "RUNNING"
        assert rows[0]["started_at"] == "2026-11-16T00:00:00+00:00"
        assert rows[0]["details"]["rabbitmq_connected"] is True
        assert rows[0]["last_seen"]
    finally:
        store.close()


def test_worker_heartbeat_rejects_unknown_status_and_invalid_identity(tmp_path):
    store = WorkflowStore(str(tmp_path / "runtime-validation.sqlite3"))
    try:
        with pytest.raises(ValueError):
            store.record_worker_heartbeat(
                worker_id="worker-1", component="workflow-runtime", status="OK",
            )
        with pytest.raises(ValueError):
            store.record_worker_heartbeat(
                worker_id="", component="workflow-runtime", status="RUNNING",
            )
    finally:
        store.close()


def test_runtime_metrics_returns_zeroed_counters_for_empty_engine(tmp_path):
    store = WorkflowStore(str(tmp_path / "runtime-metrics.sqlite3"))
    try:
        assert store.runtime_metrics() == {
            "outbox": {"pending": 0, "published": 0, "failed": 0},
            "runs": {"queued": 0, "running": 0, "succeeded": 0, "failed": 0, "cancelled": 0},
            "steps": {"pending": 0, "running": 0, "succeeded": 0, "failed": 0, "skipped": 0},
        }
    finally:
        store.close()
