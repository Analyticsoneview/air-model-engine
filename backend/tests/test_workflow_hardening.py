"""Gate 8 audit and exchange-calendar hardening regression tests."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.workflow_engine import WorkflowStore


def test_audit_records_workflow_lifecycle_and_is_append_only(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflow-audit.sqlite3"))
    try:
        workflow = store.create_workflow(
            name="Audit QOC", created_by="admin-1", trigger_type="EVENT",
            trigger_config={"event_type": "qoc.candidate.qualified"},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True, actor_id="admin-2")
        store.update_workflow(
            workflow["workflow_id"], name="Audit QOC v2", description="Updated",
            trigger_type="EVENT", trigger_config={"event_type": "qoc.scan.completed"},
            workflow_spec={"steps": []}, execution_mode="RESEARCH_ONLY", updated_by="admin-3",
        )
        store.set_workflow_enabled(workflow["workflow_id"], False, actor_id="admin-4")
        audit = store.list_workflow_audit(workflow["workflow_id"])
        assert [item["action"] for item in audit] == ["UPDATED", "DISABLED", "ENABLED", "CREATED"]
        assert [item["actor_id"] for item in audit] == ["admin-3", "admin-3", "admin-2", "admin-1"]
        assert audit[0]["workflow_version"] == 2
        assert audit[1]["workflow_version"] == 1
        with pytest.raises(Exception, match="append-only"):
            store.db.execute("UPDATE air_workflow_audit SET action='TAMPERED'")
        with pytest.raises(Exception, match="append-only"):
            store.db.execute("DELETE FROM air_workflow_audit")
    finally:
        store.close()


def test_exchange_calendar_upsert_query_and_audit(tmp_path):
    store = WorkflowStore(str(tmp_path / "exchange-calendar.sqlite3"))
    try:
        holiday = store.set_exchange_calendar_day(
            exchange_code="NSE", session_date="2026-11-17", status="HOLIDAY",
            description="Exchange holiday", updated_by="admin-1",
        )
        assert holiday["status"] == "HOLIDAY"
        special = store.set_exchange_calendar_day(
            exchange_code="NSE", session_date="2026-11-21", status="SPECIAL_SESSION",
            description="Special session", session_open="09:15", session_close="15:30",
            updated_by="admin-2",
        )
        assert special["session_open"] == "09:15"
        rows = store.list_exchange_calendar("NSE", "2026-11-01", "2026-11-30")
        assert [row["session_date"] for row in rows] == ["2026-11-17", "2026-11-21"]
        audit = store.list_workflow_audit()
        assert len([row for row in audit if row["action"] == "EXCHANGE_CALENDAR_SET"]) == 2
        with pytest.raises(ValueError, match="SPECIAL_SESSION"):
            store.set_exchange_calendar_day(
                exchange_code="NSE", session_date="2026-11-22", status="SPECIAL_SESSION",
                updated_by="admin-1",
            )
        with pytest.raises(ValueError, match="NSE or BSE"):
            store.set_exchange_calendar_day(
                exchange_code="NFO", session_date="2026-11-22", status="HOLIDAY",
                updated_by="admin-1",
            )
    finally:
        store.close()


def test_exchange_calendar_time_trigger_fails_closed_for_unlisted_and_holiday_dates(tmp_path):
    store = WorkflowStore(str(tmp_path / "exchange-calendar-schedule.sqlite3"))
    try:
        workflow = store.create_workflow(
            name="NSE market open monitor", created_by="admin", trigger_type="TIME",
            trigger_config={"timezone": "Asia/Kolkata", "hour": 9, "minute": 18,
                            "days_of_week": [0, 1, 2, 3, 4], "misfire_grace_seconds": 60,
                            "exchange_code": "NSE"},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True)
        monday = datetime(2026, 11, 16, 3, 48, tzinfo=ZoneInfo("UTC"))
        assert store.due_time_workflows(monday) == []
        store.set_exchange_calendar_day(
            exchange_code="NSE", session_date="2026-11-16", status="HOLIDAY",
            updated_by="admin",
        )
        assert store.due_time_workflows(monday) == []
        store.set_exchange_calendar_day(
            exchange_code="NSE", session_date="2026-11-16", status="TRADING_DAY",
            session_open="09:15", session_close="15:30", updated_by="admin",
        )
        assert [row["workflow_id"] for row in store.due_time_workflows(monday)] == [workflow["workflow_id"]]
        store.set_exchange_calendar_day(
            exchange_code="NSE", session_date="2026-11-16", status="SPECIAL_SESSION",
            session_open="10:00", session_close="14:00", updated_by="admin",
        )
        assert store.due_time_workflows(monday) == []
    finally:
        store.close()
