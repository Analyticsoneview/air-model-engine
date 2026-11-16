from __future__ import annotations

from app.tenant_context import (
    current_customer_id, current_is_admin, current_tenant_id, tenant_scope,
)
from app.workflow_engine import WorkflowStore


def test_tenant_scope_is_nested_and_always_restored():
    assert current_tenant_id() is None
    assert current_customer_id() is None
    assert current_is_admin() is False
    with tenant_scope(tenant_id="tenant-a", customer_id="+919876543210"):
        assert current_tenant_id() == "tenant-a"
        assert current_customer_id() == "+919876543210"
        with tenant_scope(is_admin=True):
            assert current_tenant_id() is None
            assert current_customer_id() is None
            assert current_is_admin() is True
        assert current_tenant_id() == "tenant-a"
        assert current_customer_id() == "+919876543210"
        assert current_is_admin() is False
    assert current_tenant_id() is None
    assert current_customer_id() is None
    assert current_is_admin() is False


def test_workflow_definition_event_run_and_audit_keep_tenant_identity(tmp_path):
    store = WorkflowStore(str(tmp_path / "tenant-workflow.sqlite3"))
    try:
        with tenant_scope(tenant_id="tenant-a", customer_id="+919876543210"):
            workflow = store.create_workflow(
                name="Tenant A research", created_by="customer-admin",
                trigger_type="EVENT",
                trigger_config={"event_type": "tenant.research"},
            )
            assert workflow["customer_id"] == "+919876543210"
            assert workflow["tenant_id"] == "tenant-a"
            store.set_workflow_enabled(workflow["workflow_id"], True)
            event = store.publish_event(
                event_type="tenant.research", source="tenant-a",
                payload={"symbol": "NIFTY"},
                idempotency_key="tenant-a-research-1",
            )
            assert event["customer_id"] == "+919876543210"
            assert event["tenant_id"] == "tenant-a"
            runs = store.process_event(event["event_id"])
            assert len(runs) == 1
            assert runs[0]["tenant_id"] == "tenant-a"
            context = store.run_context(runs[0]["run_id"])
            assert context["customer_id"] == "+919876543210"
            assert context["tenant_id"] == "tenant-a"
            audit = store.list_workflow_audit(workflow["workflow_id"])
            assert audit and audit[0]["tenant_id"] == "tenant-a"
    finally:
        store.close()


def test_workflow_event_from_another_tenant_cannot_trigger_definition(tmp_path):
    store = WorkflowStore(str(tmp_path / "tenant-isolation.sqlite3"))
    try:
        with tenant_scope(tenant_id="tenant-a", customer_id="+919876543210"):
            workflow = store.create_workflow(
                name="Tenant A only", created_by="customer-admin",
                trigger_type="EVENT",
                trigger_config={"event_type": "tenant.private"},
            )
            store.set_workflow_enabled(workflow["workflow_id"], True)

        with tenant_scope(tenant_id="tenant-b", customer_id="+919876543211"):
            event = store.publish_event(
                event_type="tenant.private", source="tenant-b",
                payload={"symbol": "BANKNIFTY"},
                idempotency_key="tenant-b-private-1",
            )

        with tenant_scope(is_admin=True):
            assert store.process_event(event["event_id"]) == []
            assert store.list_runs() == []
    finally:
        store.close()


def test_tenant_migration_keeps_customer_rows_fail_closed_and_global_workflows_explicit():
    from pathlib import Path

    migration = Path("migrations/versions/0020_saas_tenant_isolation.py").read_text(encoding="utf-8")
    customer_policy = migration.split("# Customer-owned tables require", 1)[1].split(
        "# Global/system workflows", 1
    )[0]
    workflow_policy = migration.split("# Global/system workflows", 1)[1].split(
        "op.execute(\"ALTER TABLE air_workflow_worker_heartbeats", 1
    )[0]
    assert "tenant_id IS NULL" not in customer_policy
    assert "tenant_id IS NULL" in workflow_policy
    assert "ENABLE ROW LEVEL SECURITY" in customer_policy
    assert "FORCE ROW LEVEL SECURITY" in customer_policy
    assert "air_assign_tenant_id" in migration
    assert "air_tenant_members" in migration
