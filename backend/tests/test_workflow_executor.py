import pytest

from app.workflow_engine import WorkflowStore
import app.workflow_executor as executor


def _queued_run(store, workflow_spec):
    workflow = store.create_workflow(
        name="Executor test", created_by="admin", trigger_type="EVENT",
        trigger_config={"event_type": "workflow.executor.trigger"},
        workflow_spec=workflow_spec,
    )
    store.set_workflow_enabled(workflow["workflow_id"], True)
    event = store.publish_event(
        event_type="workflow.executor.trigger", source="test",
        payload={"customer_id": "customer-1"}, idempotency_key=f"trigger:{workflow['workflow_id']}",
    )
    run = store.process_event(event["event_id"])[0]
    return workflow, run


def test_workflow_executor_runs_allowlisted_event_emit_step(tmp_path):
    store = WorkflowStore(str(tmp_path / "executor.sqlite3"))
    try:
        workflow = store.create_workflow(
            name="Executor test", created_by="admin", trigger_type="EVENT",
            trigger_config={"event_types": ["workflow.executor.trigger", "workflow.executor.completed"]},
            workflow_spec={"steps": [{
                "id": "emit", "action": "event.emit",
                "params": {"event_type": "workflow.executor.completed",
                           "payload": {"result": "ok"}},
            }]},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True)
        event = store.publish_event(
            event_type="workflow.executor.trigger", source="test",
            payload={"customer_id": "customer-1"},
            idempotency_key=f"trigger:{workflow['workflow_id']}",
        )
        run = store.process_event(event["event_id"])[0]
        result = executor.execute_workflow_run(store, run["run_id"])
        assert result["status"] == "SUCCEEDED"
        assert store.list_runs()[0]["status"] == "SUCCEEDED"
        step = store.list_run_steps(run["run_id"])[0]
        assert step["status"] == "SUCCEEDED"
        assert step["output"]["event_type"] == "workflow.executor.completed"
        emitted = store.db.execute(
            "SELECT payload_json FROM air_workflow_events WHERE event_type=?",
            ("workflow.executor.completed",),
        ).fetchone()
        assert '"customer_id": "customer-1"' in emitted["payload_json"]
        emitted_row = store.db.execute(
            "SELECT event_id FROM air_workflow_events WHERE event_type=?",
            ("workflow.executor.completed",),
        ).fetchone()
        assert store.process_event(emitted_row["event_id"]) == []
    finally:
        store.close()


def test_workflow_executor_resumes_successful_steps_after_restart(tmp_path, monkeypatch):
    store = WorkflowStore(str(tmp_path / "resume.sqlite3"))
    calls = []

    def action(store, context, step, outputs):
        calls.append(step["id"])
        return {"value": len(calls)}

    try:
        _, run = _queued_run(store, {"steps": [
            {"id": "first", "action": "event.emit",
             "params": {"event_type": "workflow.first"}},
            {"id": "second", "action": "event.emit",
             "params": {"event_type": "workflow.second", "source_step": "first"}},
        ]})
        monkeypatch.setattr(executor, "_execute_action", action)
        executor.execute_workflow_run(store, run["run_id"])
        executor.execute_workflow_run(store, run["run_id"])
        assert calls == ["first", "second"]
        assert store.list_runs()[0]["status"] == "SUCCEEDED"
    finally:
        store.close()


def test_workflow_executor_retries_failed_step_with_bounded_attempts(tmp_path, monkeypatch):
    store = WorkflowStore(str(tmp_path / "retry.sqlite3"))
    calls = []

    def flaky(store, context, step, outputs):
        calls.append(step["id"])
        if len(calls) == 1:
            raise RuntimeError("temporary failure")
        return {"ok": True}

    try:
        _, run = _queued_run(store, {"steps": [{
            "id": "retry", "action": "event.emit", "max_attempts": 2,
            "params": {"event_type": "workflow.retry"},
        }]})
        monkeypatch.setattr(executor, "_execute_action", flaky)
        result = executor.execute_workflow_run(store, run["run_id"])
        assert result["status"] == "SUCCEEDED"
        assert len(calls) == 2
        step = store.list_run_steps(run["run_id"])[0]
        assert step["attempts"] == 2
        assert step["status"] == "SUCCEEDED"
    finally:
        store.close()


@pytest.mark.parametrize("spec,mode", [
    ({"steps": [{"id": "bad", "action": "shell.exec", "params": {}}]}, "RESEARCH_ONLY"),
    ({"steps": [{"id": "notify", "action": "notify.telegram", "params": {}}]}, "RESEARCH_ONLY"),
    ({"steps": [{"id": "a", "action": "event.emit", "params": {"event_type": "x"}},
                {"id": "b", "action": "event.emit", "params": {"event_type": "y", "source_step": "missing"}}]}, "RESEARCH_ONLY"),
    ({"steps": [{"id": "notify", "action": "notify.telegram", "params": {"strategy": "UNSAFE_ROUTE"}}]}, "ALERT_NOTIFY"),
])
def test_workflow_rejects_unsafe_or_invalid_step_definitions(tmp_path, spec, mode):
    store = WorkflowStore(str(tmp_path / "invalid.sqlite3"))
    try:
        with pytest.raises(ValueError):
            store.create_workflow(
                name="Invalid", created_by="admin", trigger_type="EVENT",
                trigger_config={"event_type": "test"}, workflow_spec=spec,
                execution_mode=mode,
            )
    finally:
        store.close()


def test_telegram_action_uses_alert_mode_and_source_step_rows(tmp_path, monkeypatch):
    import asyncio
    from app import telegram_notifications

    store = WorkflowStore(str(tmp_path / "telegram-action.sqlite3"))
    sent = {}

    async def fake_notify(strategy, rows):
        sent["strategy"] = strategy
        sent["rows"] = rows
        return {"configured": True, "attempted": len(rows), "sent": len(rows), "failures": []}

    monkeypatch.setattr(telegram_notifications, "notify_candidates", fake_notify)
    try:
        context = {
            "run_id": "run-1", "workflow_id": "workflow-1",
            "execution_mode": "ALERT_NOTIFY",
            "event_payload": {"customer_id": "customer-1"},
        }
        step = {"id": "notify", "action": "notify.telegram",
                "params": {"strategy": "AIR_QOC", "source_step": "scan"}}
        outputs = {"scan": {"signals": [{"symbol": "NIFTY", "classification": "QUALIFIED"}]}}
        result = executor._execute_action(store, context, step, outputs)
        assert result["sent"] == 1
        assert sent["strategy"] == "AIR_QOC"
        assert sent["rows"][0]["customer_id"] == "customer-1"
        assert sent["rows"][0]["signal_id"] == "run-1:notify:0"
    finally:
        store.close()


def test_empty_qoc_result_does_not_send_false_candidate_alert(tmp_path, monkeypatch):
    from app import telegram_notifications

    store = WorkflowStore(str(tmp_path / "empty-qoc.sqlite3"))
    called = []

    async def fake_notify(strategy, rows):
        called.append((strategy, rows))
        return {"configured": True, "attempted": len(rows), "sent": len(rows), "failures": []}

    monkeypatch.setattr(telegram_notifications, "notify_candidates", fake_notify)
    try:
        context = {
            "run_id": "run-empty", "workflow_id": "workflow-empty",
            "execution_mode": "ALERT_NOTIFY",
            "event_payload": {"customer_id": "customer-1"},
        }
        step = {"id": "notify", "action": "notify.telegram",
                "params": {"strategy": "AIR_QOC", "source_step": "scan"}}
        result = executor._execute_action(store, context, step, {"scan": {"signals": []}})
        assert result["sent"] == 0
        assert result["reason"] == "no qualified candidates"
        assert called == []
    finally:
        store.close()


def test_executor_recovers_missing_terminal_event_after_publish_outage(tmp_path, monkeypatch):
    store = WorkflowStore(str(tmp_path / "terminal-recovery.sqlite3"))
    try:
        _, run = _queued_run(store, {"steps": []})
        store.set_run_status(run["run_id"], "FAILED", "Injected terminal failure")
        original_publish = store.publish_event
        attempts = {"count": 0}

        def fail_once(**kwargs):
            if kwargs.get("event_type") == "workflow.run.failed" and attempts["count"] == 0:
                attempts["count"] += 1
                raise RuntimeError("temporary outbox failure")
            return original_publish(**kwargs)

        monkeypatch.setattr(store, "publish_event", fail_once)
        executor.execute_workflow_run(store, run["run_id"])
        assert run["run_id"] in store.runnable_runs()
        monkeypatch.setattr(store, "publish_event", original_publish)
        executor.execute_workflow_run(store, run["run_id"])
        assert run["run_id"] not in store.runnable_runs()
        terminal = store.db.execute(
            "SELECT COUNT(*) AS count FROM air_workflow_events WHERE event_type=?",
            ("workflow.run.failed",),
        ).fetchone()
        assert terminal["count"] == 1
    finally:
        store.close()


def test_terminal_event_does_not_retrigger_the_originating_workflow(tmp_path):
    store = WorkflowStore(str(tmp_path / "terminal-chain.sqlite3"))
    try:
        workflow = store.create_workflow(
            name="Terminal loop guard", created_by="admin", trigger_type="EVENT",
            trigger_config={"event_types": ["workflow.executor.trigger", "workflow.run.completed"]},
            workflow_spec={"steps": []},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True)
        trigger = store.publish_event(
            event_type="workflow.executor.trigger", source="test", payload={},
            idempotency_key="terminal-loop-trigger",
        )
        run = store.process_event(trigger["event_id"])[0]
        executor.execute_workflow_run(store, run["run_id"])
        event = store.db.execute(
            "SELECT event_id,payload_json FROM air_workflow_events WHERE event_type=?",
            ("workflow.run.completed",),
        ).fetchone()
        assert event is not None
        payload = __import__("json").loads(event["payload_json"])
        assert workflow["workflow_id"] in payload["workflow_chain"]
        assert store.process_event(event["event_id"]) == []
    finally:
        store.close()
