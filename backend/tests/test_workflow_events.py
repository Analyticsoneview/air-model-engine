from app.workflow_engine import WorkflowStore
import app.workflow_events as workflow_events


def test_domain_event_bridge_persists_idempotent_outbox_record(tmp_path, monkeypatch):
    path = str(tmp_path / "domain-events.sqlite3")
    monkeypatch.setattr(workflow_events, "WorkflowStore", lambda: WorkflowStore(path))
    first = workflow_events.emit_workflow_event(
        event_type="portfolio.snapshot.updated", source="portfolio.risk",
        payload={"customer_id": "customer-1", "summary": {"concentration": 42}},
        idempotency_key="portfolio-customer-1-snapshot-1",
    )
    second = workflow_events.emit_workflow_event(
        event_type="portfolio.snapshot.updated", source="portfolio.risk",
        payload={"customer_id": "customer-1", "summary": {"concentration": 42}},
        idempotency_key="portfolio-customer-1-snapshot-1",
    )
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    store = WorkflowStore(path)
    try:
        assert len(store.pending_outbox()) == 1
    finally:
        store.close()


def test_domain_event_bridge_is_non_blocking_for_domain_when_store_unavailable(monkeypatch):
    def unavailable():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(workflow_events, "WorkflowStore", unavailable)
    result = workflow_events.emit_workflow_event(
        event_type="strategy.orb.signal.created", source="orb.signal-engine",
        payload={"customer_id": "customer-1", "signal_id": "ORB:AM:2026-11-16:NIFTY"},
        idempotency_key="orb-customer-1-signal-1",
    )
    assert result["status"] == "deferred"
    assert result["error"] == "RuntimeError"
