"""Disposable PostgreSQL backup/restore and concurrent-claim acceptance.

This is destructive only to the explicitly supplied RESTORE database. Never point
AIR_WORKFLOW_RESTORE_DATABASE_URL at a production database.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.workflow_engine import WorkflowStore
from app.workflow_executor import execute_workflow_run


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _pg_cli_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _run(*args: str, stdin=None, stdout=None) -> None:
    """Run PostgreSQL client tools with a version-matched disposable client image."""
    image = os.getenv("AIR_WORKFLOW_PG_CLIENT_DOCKER_IMAGE", "").strip()
    command = list(args)
    if image and command[0] in {"pg_dump", "pg_restore"}:
        docker_args = ["docker", "run", "--rm", "--network", "host"]
        if command[0] == "pg_restore":
            docker_args.append("-i")
        docker_args.extend(["-e", "PGPASSWORD", image, *command])
        command = docker_args
    subprocess.run(command, check=True, stdin=stdin, stdout=stdout)


def _seed_acceptance_records() -> dict:
    store = WorkflowStore()
    suffix = str(uuid4())
    worker_id = f"gate10-acceptance:{suffix}"
    try:
        workflow = store.create_workflow(
            name=f"Backup restore acceptance {suffix[:8]}",
            created_by="gate10-acceptance",
            trigger_type="EVENT",
            trigger_config={"event_type": "gate10.acceptance." + suffix},
            workflow_spec={"steps": [{"id": "emit", "action": "event.emit", "params": {"event_type": "gate10.acceptance.completed", "payload": {"accepted": True}}}]},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True, actor_id="gate10-acceptance")
        event = store.publish_event(
            event_type="gate10.acceptance." + suffix,
            source="gate10-acceptance",
            payload={"acceptance_id": suffix},
            idempotency_key="gate10-acceptance:" + suffix,
        )
        runs = store.process_event(event["event_id"])
        if len(runs) != 1:
            raise AssertionError(f"Expected one workflow run, got {len(runs)}")
        run_id = runs[0]["run_id"]
        claims = store.claim_runnable_runs(worker_id, limit=1, lease_seconds=120)
        if len(claims) != 1 or claims[0]["run_id"] != run_id:
            raise AssertionError("Acceptance run was not claimed exactly once")
        claim = claims[0]
        execution = execute_workflow_run(
            store, run_id, worker_id=worker_id,
            claim_version=claim["claim_version"],
        )
        if not execution or execution.get("status") != "SUCCEEDED":
            raise AssertionError(f"Workflow end-to-end execution failed: {execution}")
        completed_step = store.get_run_step(run_id, "emit")
        followup_event_id = completed_step["output"]["event_id"]
        store.set_exchange_calendar_day(
            exchange_code="NSE", session_date="2099-12-31",
            status="TRADING_DAY", updated_by="gate10-acceptance",
            source="gate10-backup-restore-test",
        )
        store.record_worker_heartbeat(
            worker_id=worker_id, component="workflow-runtime", status="RUNNING",
            details={"acceptance_id": suffix, "rabbitmq_connected": True, "components": {"workflow-outbox": True, "workflow-scheduler": True, "workflow-executor": True, "workflow-operations-monitor": True}},
        )
        return {
            "suffix": suffix, "workflow_id": workflow["workflow_id"],
            "event_id": event["event_id"], "run_id": run_id,
            "followup_event_id": followup_event_id, "worker_id": worker_id,
        }
    finally:
        store.close()


def _verify_records(database_url: str, ids: dict) -> None:
    os.environ["AIR_CUSTOMER_DATABASE_URL"] = database_url
    os.environ.pop("AIR_DATABASE_URL", None)
    store = WorkflowStore()
    try:
        checks = {
            "air_workflow_definitions": ("workflow_id", ids["workflow_id"]),
            "air_workflow_definition_versions": ("workflow_id", ids["workflow_id"]),
            "air_workflow_events": ("event_id", ids["event_id"]),
            "air_workflow_outbox": ("event_id", ids["event_id"]),
            "air_workflow_runs": ("run_id", ids["run_id"]),
            "air_workflow_run_steps": ("run_id", ids["run_id"]),
            "air_workflow_audit": ("workflow_id", ids["workflow_id"]),
            "air_workflow_worker_heartbeats": ("worker_id", ids["worker_id"]),
        }
        for table, (column, value) in checks.items():
            row = store.db.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {column}=?", (value,)
            ).fetchone()
            if int(row["n"]) < 1:
                raise AssertionError(f"Backup restore missing {table} record for {value}")
        followup = store.db.execute(
            "SELECT COUNT(*) AS n FROM air_workflow_events WHERE event_id=?",
            (ids["followup_event_id"],),
        ).fetchone()
        if int(followup["n"]) != 1:
            raise AssertionError("Backup restore did not preserve workflow-generated follow-up event")
        runtime_heartbeat = store.db.execute(
            """SELECT 1 FROM air_workflow_worker_heartbeats
               WHERE component='workflow-runtime' AND status='RUNNING'
                 AND last_seen::timestamptz > now() - interval '45 seconds'
                 AND details_json::jsonb ->> 'rabbitmq_connected' = 'true'
                 AND details_json::jsonb -> 'components' -> 'workflow-outbox' = 'true'::jsonb
                 AND details_json::jsonb -> 'components' -> 'workflow-scheduler' = 'true'::jsonb
                 AND details_json::jsonb -> 'components' -> 'workflow-executor' = 'true'::jsonb
                 AND details_json::jsonb -> 'components' -> 'workflow-operations-monitor' = 'true'::jsonb
                 AND NOT EXISTS (
                   SELECT 1 FROM jsonb_each(details_json::jsonb -> 'components') AS component(name, alive)
                   WHERE alive <> 'true'::jsonb
                 )
               LIMIT 1"""
        ).fetchone()
        if not runtime_heartbeat:
            raise AssertionError("Restored runtime heartbeat failed the Docker Swarm readiness query")
        calendar = store.get_exchange_calendar_day("NSE", "2099-12-31")
        if not calendar or calendar["status"] != "TRADING_DAY":
            raise AssertionError("Backup restore did not preserve exchange calendar record")
        run = store.run_context(ids["run_id"])
        if not run or run["status"] != "SUCCEEDED":
            raise AssertionError("Backup restore did not preserve workflow run state")
        steps = store.list_run_steps(ids["run_id"])
        if len(steps) != 1 or steps[0]["status"] != "SUCCEEDED":
            raise AssertionError("Backup restore did not preserve workflow step ledger")
        if store.list_workflow_audit(workflow_id=ids["workflow_id"], limit=20) == []:
            raise AssertionError("Backup restore did not preserve audit history")
        index_rows = store.db.execute(
            """SELECT indexname FROM pg_indexes
               WHERE schemaname=current_schema()
                 AND tablename IN ('air_workflow_runs','air_workflow_outbox',
                                   'air_workflow_run_steps','air_workflow_audit',
                                   'air_exchange_calendar')"""
        ).fetchall()
        index_names = {row["indexname"] for row in index_rows}
        required = {
            "ix_air_workflow_runs_lease", "ix_air_workflow_outbox_pending",
            "ix_air_workflow_run_steps_order", "ix_air_workflow_audit_workflow_time",
            "ix_air_exchange_calendar_date",
        }
        missing = required - index_names
        if missing:
            raise AssertionError(f"Backup restore missing indexes: {sorted(missing)}")
    finally:
        store.close()


def _concurrent_claim_acceptance() -> None:
    store = WorkflowStore()
    suffix = str(uuid4())
    workflow = store.create_workflow(
        name=f"Concurrent claim acceptance {suffix[:8]}",
        created_by="gate10-acceptance", trigger_type="EVENT",
        trigger_config={"event_type": "gate10.load." + suffix},
        workflow_spec={"steps": []},
    )
    store.set_workflow_enabled(workflow["workflow_id"], True, actor_id="gate10-acceptance")
    run_ids = []
    try:
        for index in range(40):
            event = store.publish_event(
                event_type="gate10.load." + suffix, source="gate10-acceptance",
                payload={"index": index},
                idempotency_key=f"gate10-load:{suffix}:{index}",
            )
            matched = store.process_event(event["event_id"])
            if len(matched) != 1:
                raise AssertionError(f"Expected one run for load event {index}")
            run_ids.append(matched[0]["run_id"])
    finally:
        store.close()

    def claim(worker_number: int) -> list[dict]:
        worker_store = WorkflowStore()
        try:
            return worker_store.claim_runnable_runs(
                f"gate10-load-worker-{suffix[:8]}-{worker_number}", limit=10, lease_seconds=120,
            )
        finally:
            worker_store.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = [claim for batch in pool.map(claim, range(8)) for claim in batch]
    claimed_ids = [item["run_id"] for item in claims]
    if len(claimed_ids) != 40 or len(set(claimed_ids)) != 40:
        raise AssertionError(
            f"Concurrent claim mismatch: expected 40 unique claims, got {len(claimed_ids)}"
        )
    if set(claimed_ids) != set(run_ids):
        raise AssertionError("Concurrent claims lost or introduced workflow runs")

    # Force one lease expiry and verify the next worker gets a higher fencing version.
    expired_run = claims[0]
    recovery = WorkflowStore()
    try:
        recovery.db.execute(
            "UPDATE air_workflow_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE run_id=?",
            (expired_run["run_id"],),
        )
        recovery.db.commit()
        replacement = recovery.claim_runnable_runs(
            f"gate10-recovery-worker-{suffix[:8]}", limit=1, lease_seconds=120,
        )
        if len(replacement) != 1:
            raise AssertionError("Expired lease was not recovered")
        if replacement[0]["claim_version"] <= expired_run["claim_version"]:
            raise AssertionError("Lease recovery did not advance the fencing version")
    finally:
        recovery.close()


def main() -> None:
    source_url = _require("AIR_CUSTOMER_DATABASE_URL")
    restore_url = _require("AIR_WORKFLOW_RESTORE_DATABASE_URL")
    if source_url == restore_url:
        raise SystemExit("Source and restore database URLs must be different")
    ids = _seed_acceptance_records()
    _concurrent_claim_acceptance()

    with tempfile.TemporaryDirectory(prefix="air-workflow-backup-") as directory:
        dump_path = str(Path(directory) / "workflow-acceptance.dump")
        with open(dump_path, "wb") as dump_file:
            _run("pg_dump", "--format=custom", "--no-owner", "--no-acl",
                 "--dbname", _pg_cli_url(source_url), stdout=dump_file)
        with open(dump_path, "rb") as dump_file:
            _run("pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl",
                 "--dbname", _pg_cli_url(restore_url), stdin=dump_file)

    _verify_records(restore_url, ids)
    print("PASS: PostgreSQL workflow backup/restore preserved definitions, versions, events, outbox, runs, steps, leases, audit, calendar, heartbeats and indexes.")
    print("PASS: 8 concurrent PostgreSQL workers claimed 40 runs exactly once.")
    print("PASS: expired lease recovery advanced the fencing version.")


if __name__ == "__main__":
    main()
