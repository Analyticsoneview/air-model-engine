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
