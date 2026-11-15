from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security import require_admin
from app.workflow_api import router
from app.workflow_engine import WorkflowStore


def _client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = lambda: {"admin_id": "admin-1", "role": "ADMIN"}
    return TestClient(app)


def test_runtime_endpoint_reports_fresh_worker_and_queue_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("AIR_WORKFLOW_DB_PATH", str(tmp_path / "runtime-api.sqlite3"))
    store = WorkflowStore()
    try:
        store.record_worker_heartbeat(
            worker_id="worker-1", component="workflow-runtime", status="RUNNING",
            details={"rabbitmq_connected": True, "components": {"workflow-executor": True}},
        )
    finally:
        store.close()

    response = _client().get("/api/v1/admin/workflows/runtime")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HEALTHY"
    assert body["workers"][0]["healthy"] is True
    assert body["workers"][0]["details"]["rabbitmq_connected"] is True
    assert body["metrics"]["outbox"]["pending"] == 0


def test_runtime_endpoint_fails_closed_for_stale_or_missing_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("AIR_WORKFLOW_DB_PATH", str(tmp_path / "runtime-stale.sqlite3"))
    store = WorkflowStore()
    try:
        store.record_worker_heartbeat(
            worker_id="worker-stale", component="workflow-runtime", status="RUNNING",
        )
        store.db.execute(
            "UPDATE air_workflow_worker_heartbeats SET last_seen=?",
            ("2020-01-01T00:00:00+00:00",),
        )
        store.db.commit()
    finally:
        store.close()

    response = _client().get("/api/v1/admin/workflows/runtime")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DEGRADED"
    assert body["workers"][0]["healthy"] is False


def test_runtime_endpoint_reports_not_seen_before_worker_starts(tmp_path, monkeypatch):
    monkeypatch.setenv("AIR_WORKFLOW_DB_PATH", str(tmp_path / "runtime-empty.sqlite3"))
    response = _client().get("/api/v1/admin/workflows/runtime")
    assert response.status_code == 200
    assert response.json()["status"] == "NOT_SEEN"
    assert response.json()["workers"] == []
