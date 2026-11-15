import json

import pytest

from app.workflow_engine import WorkflowStore


def test_workflow_definition_defaults_to_disabled_research_only(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflow.sqlite3"))
    try:
        workflow = store.create_workflow(
            name="NIFTY ORB monitor", created_by="admin-1", trigger_type="STRATEGY",
            trigger_config={"strategy": "ORB", "session": "09:18-09:23"},
            workflow_spec={"steps": [{"type": "evaluate", "service": "orb"}]},
        )
        assert workflow["workflow_id"]
        assert workflow["trigger_type"] == "STRATEGY"
        assert workflow["execution_mode"] == "RESEARCH_ONLY"
        assert workflow["enabled"] is False
        assert workflow["version"] == 1
        assert store.list_workflows(enabled=False)[0]["name"] == "NIFTY ORB monitor"
    finally:
        store.close()


@pytest.mark.parametrize("field,value", [
    ("trigger_type", "UNKNOWN"),
    ("execution_mode", "AUTO_TRADE"),
])
def test_workflow_rejects_unsupported_modes(field, value, tmp_path):
    store = WorkflowStore(str(tmp_path / "workflow.sqlite3"))
    try:
        args = {"name": "bad", "created_by": "admin", "trigger_type": "EVENT"}
        args[field] = value
        with pytest.raises(ValueError):
            store.create_workflow(**args)
    finally:
        store.close()


def test_event_intake_is_durable_and_idempotent(tmp_path):
    path = str(tmp_path / "workflow.sqlite3")
    store = WorkflowStore(path)
    try:
        first = store.publish_event(
            event_type="market.orb.breakout", source="orb-engine",
            payload={"symbol": "NIFTY", "timeframe": "5m"}, idempotency_key="orb:NIFTY:2026-11-16:0918",
        )
        replay = store.publish_event(
            event_type="market.orb.breakout", source="orb-engine",
            payload={"symbol": "NIFTY"}, idempotency_key="orb:NIFTY:2026-11-16:0918",
        )
        assert first["event_id"] == replay["event_id"]
        assert first["duplicate"] is False
        assert replay["duplicate"] is True
        assert first["payload"]["symbol"] == "NIFTY"
        outbox = store.db.execute(
            "SELECT event_id,status FROM air_workflow_outbox WHERE event_id=?", (first["event_id"],)
        ).fetchall()
        assert len(outbox) == 1
        assert outbox[0]["status"] == "PENDING"
    finally:
        store.close()


def test_event_payload_must_be_json_object(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflow.sqlite3"))
    try:
        with pytest.raises(ValueError):
            store.publish_event(
                event_type="market.tick", source="feed", payload=["not", "an", "object"],
                idempotency_key="tick-1",
            )
    finally:
        store.close()
