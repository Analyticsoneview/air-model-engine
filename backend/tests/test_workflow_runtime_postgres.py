"""PostgreSQL integration coverage for the workflow runtime heartbeat table."""
import os
from uuid import uuid4

import pytest

from app.workflow_engine import WorkflowStore
from app.tenant_context import tenant_scope


@pytest.mark.skipif(
    not (os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_DATABASE_URL")),
    reason="PostgreSQL workflow runtime integration is enabled in the disposable DB job",
)
def test_postgres_workflow_worker_heartbeat_upsert_and_metrics():
    worker_id = f"pytest:{uuid4()}"
    store = WorkflowStore()
    try:
        with tenant_scope(is_admin=True):
            store.record_worker_heartbeat(
                worker_id=worker_id, component="workflow-runtime", status="STARTING",
                details={"rabbitmq_connected": False},
            )
            store.record_worker_heartbeat(
                worker_id=worker_id, component="workflow-runtime", status="RUNNING",
                details={"rabbitmq_connected": True},
            )
            rows = [row for row in store.list_worker_heartbeats(500)
                    if row["worker_id"] == worker_id]
        assert len(rows) == 1
        assert rows[0]["status"] == "RUNNING"
        assert rows[0]["details"]["rabbitmq_connected"] is True
        with tenant_scope(is_admin=True):
            metrics = store.runtime_metrics()
        assert set(metrics) == {"outbox", "runs", "steps"}
    finally:
        with tenant_scope(is_admin=True):
            store.db.execute(
                "DELETE FROM air_workflow_worker_heartbeats WHERE worker_id=?",
                (worker_id,),
            )
        store.close()
