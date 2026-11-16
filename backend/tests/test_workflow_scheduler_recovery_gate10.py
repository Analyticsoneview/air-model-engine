from datetime import datetime, timezone

from app.workflow_engine import WorkflowStore


def _time_workflow(store, **config):
    trigger = {
        "timezone": "Asia/Kolkata",
        "hour": 9,
        "minute": 18,
        "days_of_week": list(range(7)),
        "misfire_grace_seconds": 300,
        **config,
    }
    workflow = store.create_workflow(
        name="Scheduler recovery acceptance",
        created_by="gate10",
        trigger_type="TIME",
        trigger_config=trigger,
    )
    store.set_workflow_enabled(workflow["workflow_id"], True)
    return workflow


def test_scheduler_restart_within_grace_emits_one_idempotent_event(tmp_path):
    store = WorkflowStore(str(tmp_path / "scheduler-restart.sqlite3"))
    try:
        workflow = _time_workflow(store)
        # 09:20 IST is within the configured five-minute grace after 09:18.
        now = datetime(2026, 11, 16, 3, 50, tzinfo=timezone.utc)
        first_scan = store.due_time_workflows(now)
        restarted_scan = store.due_time_workflows(now)
        assert len(first_scan) == len(restarted_scan) == 1
        item = first_scan[0]
        assert item["workflow_id"] == workflow["workflow_id"]
        assert item["scheduled_key"] == "202611160918"

        key = f"time:{workflow['workflow_id']}:{item['scheduled_key']}"
        first_event = store.publish_event(
            event_type="workflow.time.triggered", source="workflow.scheduler",
            payload={"workflow_id": workflow["workflow_id"]},
            idempotency_key=key,
        )
        replay_event = store.publish_event(
            event_type="workflow.time.triggered", source="workflow.scheduler",
            payload={"workflow_id": workflow["workflow_id"]},
            idempotency_key=key,
        )
        assert first_event["event_id"] == replay_event["event_id"]
        assert replay_event["duplicate"] is True
        assert len(store.pending_outbox()) == 1
    finally:
        store.close()


def test_scheduler_misfire_outside_grace_is_skipped(tmp_path):
    store = WorkflowStore(str(tmp_path / "scheduler-misfire.sqlite3"))
    try:
        _time_workflow(store, misfire_grace_seconds=60)
        now = datetime(2026, 11, 16, 3, 50, 1, tzinfo=timezone.utc)
        assert store.due_time_workflows(now) == []
    finally:
        store.close()


def test_exchange_calendar_missing_or_holiday_fails_closed(tmp_path):
    store = WorkflowStore(str(tmp_path / "scheduler-calendar.sqlite3"))
    try:
        workflow = _time_workflow(store, exchange_code="NSE")
        now = datetime(2026, 11, 16, 3, 48, tzinfo=timezone.utc)
        assert store.due_time_workflows(now) == []

        store.set_exchange_calendar_day(
            exchange_code="NSE", session_date="2026-11-16", status="HOLIDAY",
            updated_by="gate10", source="test",
        )
        assert store.due_time_workflows(now) == []

        store.set_exchange_calendar_day(
            exchange_code="NSE", session_date="2026-11-16", status="TRADING_DAY",
            updated_by="gate10", source="test",
        )
        assert [x["workflow_id"] for x in store.due_time_workflows(now)] == [workflow["workflow_id"]]
    finally:
        store.close()


def test_special_session_bounds_trigger_time(tmp_path):
    store = WorkflowStore(str(tmp_path / "scheduler-special.sqlite3"))
    try:
        _time_workflow(store, exchange_code="BSE", hour=9, minute=18)
        store.set_exchange_calendar_day(
            exchange_code="BSE", session_date="2026-11-16",
            status="SPECIAL_SESSION", session_open="10:00", session_close="14:00",
            updated_by="gate10", source="test",
        )
        before_open = datetime(2026, 11, 16, 3, 48, tzinfo=timezone.utc)
        assert store.due_time_workflows(before_open) == []

        _time_workflow(store, timezone="Asia/Kolkata", hour=10, minute=30,
                       exchange_code="BSE", misfire_grace_seconds=300)
        during_session = datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc)
        due = store.due_time_workflows(during_session)
        assert len(due) == 1
        assert due[0]["local_time"].startswith("2026-11-16T10:30")
    finally:
        store.close()


def test_timezone_conversion_is_independent_of_worker_host_timezone(tmp_path):
    store = WorkflowStore(str(tmp_path / "scheduler-timezone.sqlite3"))
    try:
        workflow = _time_workflow(store, timezone="Asia/Kolkata", hour=9, minute=18)
        # 03:48 UTC is 09:18 in India, irrespective of the worker host timezone.
        due = store.due_time_workflows(datetime(2026, 11, 16, 3, 48, tzinfo=timezone.utc))
        assert [item["workflow_id"] for item in due] == [workflow["workflow_id"]]
    finally:
        store.close()
