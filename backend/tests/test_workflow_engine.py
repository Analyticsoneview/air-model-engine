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


def test_event_matching_creates_one_durable_run_and_is_idempotent(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflow.sqlite3"))
    try:
        workflow = store.create_workflow(
            name="ORB alert", created_by="admin", trigger_type="STRATEGY",
            trigger_config={"event_type": "market.orb.breakout"},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True)
        event = store.publish_event(
            event_type="market.orb.breakout", source="orb",
            payload={"symbol": "NIFTY"}, idempotency_key="orb-run-1",
        )
        first = store.process_event(event["event_id"])
        replay = store.process_event(event["event_id"])
        assert len(first) == 1
        assert first[0]["status"] == "QUEUED"
        assert replay[0]["run_id"] == first[0]["run_id"]
        assert replay[0]["duplicate"] is True
        assert len(store.list_runs()) == 1
    finally:
        store.close()


def test_time_trigger_is_timezone_aware_and_weekday_configured(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    store = WorkflowStore(str(tmp_path / "workflow.sqlite3"))
    try:
        workflow = store.create_workflow(
            name="QOC morning scan", created_by="admin", trigger_type="TIME",
            trigger_config={"timezone": "Asia/Kolkata", "hour": 9, "minute": 18,
                            "days_of_week": [0, 1, 2, 3, 4]},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True)
        due = store.due_time_workflows(datetime(2026, 11, 16, 3, 48, tzinfo=ZoneInfo("UTC")))
        assert [item["workflow_id"] for item in due] == [workflow["workflow_id"]]
        later = store.due_time_workflows(datetime(2026, 11, 16, 3, 49, tzinfo=ZoneInfo("UTC")))
        assert later == []
    finally:
        store.close()


def test_outbox_retry_is_bounded_and_success_can_be_recorded(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflow.sqlite3"))
    try:
        event = store.publish_event(event_type="test.event", source="test", idempotency_key="outbox-1")
        item = store.pending_outbox()[0]
        store.mark_outbox_failed(item["outbox_id"], 0, "connection refused")
        retried = store.pending_outbox()
        assert retried == []  # backoff delays the next attempt
        store.mark_outbox_published(item["outbox_id"])
        row = store.db.execute("SELECT status FROM air_workflow_outbox WHERE event_id=?", (event["event_id"],)).fetchone()
        assert row["status"] == "PUBLISHED"
    finally:
        store.close()
