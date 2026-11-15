from concurrent.futures import ThreadPoolExecutor

from app.workflow_engine import WorkflowStore


def _queued_run(store):
    workflow = store.create_workflow(
        name="Lease test", created_by="gate10-test", trigger_type="EVENT",
        trigger_config={"event_type": "lease.test"},
        workflow_spec={"steps": []},
    )
    store.set_workflow_enabled(workflow["workflow_id"], True)
    event = store.publish_event(
        event_type="lease.test", source="gate10-test",
        payload={"customer_id": "lease-customer"}, idempotency_key="lease-event-1",
    )
    return store.process_event(event["event_id"])[0]["run_id"]


def test_two_workers_cannot_claim_same_run_concurrently(tmp_path):
    path = str(tmp_path / "workflow-leases.sqlite3")
    setup = WorkflowStore(path)
    run_id = _queued_run(setup)
    setup.close()
    first, second = WorkflowStore(path), WorkflowStore(path)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(first.claim_runnable_runs, "worker-a", 1, 60)
            b = pool.submit(second.claim_runnable_runs, "worker-b", 1, 60)
            claims = a.result() + b.result()
        assert len(claims) == 1
        assert claims[0]["run_id"] == run_id
    finally:
        first.close()
        second.close()


def test_expired_run_lease_is_recovered_with_new_fencing_version(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflow-lease-recovery.sqlite3"))
    try:
        run_id = _queued_run(store)
        first = store.claim_runnable_runs("worker-old", 1, 60)[0]
        store.db.execute(
            "UPDATE air_workflow_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE run_id=?",
            (run_id,),
        )
        second = store.claim_runnable_runs("worker-new", 1, 60)[0]
        assert second["claim_version"] == first["claim_version"] + 1
        assert second["worker_id"] == "worker-new"
        assert store.renew_run_lease(
            run_id, "worker-old", first["claim_version"], 60,
        ) is False
        assert store.renew_run_lease(
            run_id, "worker-new", second["claim_version"], 60,
        ) is True
    finally:
        store.close()


def test_only_current_claim_owner_can_finalize_run(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflow-lease-owner.sqlite3"))
    try:
        run_id = _queued_run(store)
        claim = store.claim_runnable_runs("worker-owner", 1, 60)[0]
        try:
            store.set_run_status(
                run_id, "SUCCEEDED", worker_id="worker-stale",
                claim_version=claim["claim_version"],
            )
            assert False, "stale worker must not finalize a run"
        except RuntimeError as exc:
            assert "claim was lost" in str(exc)
        store.set_run_status(
            run_id, "SUCCEEDED", worker_id="worker-owner",
            claim_version=claim["claim_version"],
        )
        row = store.db.execute(
            "SELECT status,claimed_by,lease_expires_at FROM air_workflow_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        assert row["status"] == "SUCCEEDED"
        assert row["claimed_by"] is None
        assert row["lease_expires_at"] is None
    finally:
        store.close()
