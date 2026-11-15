"""AIR workflow-engine foundation: validated contracts and durable event intake.

The first phase deliberately persists events before dispatch. A transactional outbox
allows RabbitMQ (recommended transport) to be added without losing events between a
database commit and broker publish. No workflow action or broker order is executed here.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db_compat import PostgresConnection, read_database_url

TRIGGER_TYPES = {"EVENT", "TIME", "STRATEGY", "CONDITION"}
EXECUTION_MODES = {"RESEARCH_ONLY", "ALERT_NOTIFY", "AUTHORIZED_EXECUTION"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_object(value: Any, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain valid JSON values") from exc
    return value


class WorkflowStore:
    """Durable definitions and idempotent event intake.

    PostgreSQL is selected automatically when AIR_CUSTOMER_DATABASE_URL or
    AIR_DATABASE_URL is configured; SQLite is only the local/test compatibility path.
    """

    def __init__(self, db_path: str | None = None):
        url = None if db_path is not None else (
            read_database_url("AIR_CUSTOMER_DATABASE_URL") or read_database_url("AIR_DATABASE_URL")
        )
        self.is_postgres = bool(url)
        if url:
            self.db = PostgresConnection(url)
            try:
                self.db.execute("SELECT 1 FROM air_workflow_definitions LIMIT 0")
                self.db.execute("SELECT 1 FROM air_workflow_events LIMIT 0")
                self.db.execute("SELECT 1 FROM air_workflow_outbox LIMIT 0")
                self.db.execute("SELECT 1 FROM air_workflow_runs LIMIT 0")
            except Exception as exc:
                self.db.close()
                raise RuntimeError("Workflow PostgreSQL schema is missing; apply Alembic migrations first") from exc
        else:
            path = db_path or os.getenv("AIR_WORKFLOW_DB_PATH", "data/air_workflows.sqlite3")
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=30000")
            self._initialize_sqlite()

    def _initialize_sqlite(self) -> None:
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS air_workflow_definitions (
                workflow_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                trigger_type TEXT NOT NULL CHECK(trigger_type IN ('EVENT','TIME','STRATEGY','CONDITION')),
                trigger_config_json TEXT NOT NULL DEFAULT '{}', workflow_spec_json TEXT NOT NULL DEFAULT '{}',
                execution_mode TEXT NOT NULL DEFAULT 'RESEARCH_ONLY'
                    CHECK(execution_mode IN ('RESEARCH_ONLY','ALERT_NOTIFY','AUTHORIZED_EXECUTION')),
                version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1), enabled INTEGER NOT NULL DEFAULT 0,
                created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_enabled_trigger
                ON air_workflow_definitions(enabled,trigger_type);
            CREATE TABLE IF NOT EXISTS air_workflow_events (
                event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, source TEXT NOT NULL,
                occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
                idempotency_key TEXT NOT NULL UNIQUE, correlation_id TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_events_type_time
                ON air_workflow_events(event_type,occurred_at);
            CREATE TABLE IF NOT EXISTS air_workflow_outbox (
                outbox_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING','PUBLISHED','FAILED')),
                attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL,
                published_at TEXT, last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_outbox_pending
                ON air_workflow_outbox(status,available_at);
            CREATE TABLE IF NOT EXISTS air_workflow_runs (
                run_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, workflow_version INTEGER NOT NULL,
                event_id TEXT NOT NULL, status TEXT NOT NULL, execution_mode TEXT NOT NULL,
                started_at TEXT NOT NULL, completed_at TEXT, error TEXT,
                UNIQUE(workflow_id,workflow_version,event_id)
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_runs_status_time
                ON air_workflow_runs(status,started_at);
        """)
        self.db.commit()

    def create_workflow(
        self, *, name: str, created_by: str, trigger_type: str,
        trigger_config: dict | None = None, workflow_spec: dict | None = None,
        description: str = "", execution_mode: str = "RESEARCH_ONLY",
    ) -> dict:
        name = str(name).strip()
        created_by = str(created_by).strip()
        trigger_type = str(trigger_type).upper()
        execution_mode = str(execution_mode).upper()
        if not name or len(name) > 120:
            raise ValueError("Workflow name must contain 1-120 characters")
        if not created_by or len(created_by) > 128:
            raise ValueError("created_by must contain 1-128 characters")
        if trigger_type not in TRIGGER_TYPES:
            raise ValueError("Unsupported workflow trigger_type")
        if execution_mode not in EXECUTION_MODES:
            raise ValueError("Unsupported workflow execution_mode")
        trigger_config = _json_object(trigger_config, "trigger_config")
        workflow_spec = _json_object(workflow_spec, "workflow_spec")
        workflow_id, now = str(uuid4()), _now()
        with self.db:
            self.db.execute("""INSERT INTO air_workflow_definitions
                (workflow_id,name,description,trigger_type,trigger_config_json,workflow_spec_json,
                 execution_mode,version,enabled,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                workflow_id, name, str(description)[:4000], trigger_type,
                json.dumps(trigger_config, allow_nan=False), json.dumps(workflow_spec, allow_nan=False),
                execution_mode, 1, False if self.is_postgres else 0, created_by, now, now,
            ))
        return self.get_workflow(workflow_id)

    def get_workflow(self, workflow_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM air_workflow_definitions WHERE workflow_id=?", (workflow_id,)
        ).fetchone()
        return self._decode_workflow(row) if row else None

    def list_workflows(self, *, enabled: bool | None = None, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        if enabled is None:
            rows = self.db.execute(
                "SELECT * FROM air_workflow_definitions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM air_workflow_definitions WHERE enabled=? ORDER BY updated_at DESC LIMIT ?",
                (enabled, limit),
            ).fetchall()
        return [self._decode_workflow(row) for row in rows]

    @staticmethod
    def _decode_workflow(row: Any) -> dict:
        return {
            "workflow_id": row["workflow_id"], "name": row["name"], "description": row["description"],
            "trigger_type": row["trigger_type"], "trigger_config": json.loads(row["trigger_config_json"]),
            "workflow_spec": json.loads(row["workflow_spec_json"]), "execution_mode": row["execution_mode"],
            "version": row["version"], "enabled": bool(row["enabled"]), "created_by": row["created_by"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def publish_event(
        self, *, event_type: str, source: str, payload: dict | None = None,
        idempotency_key: str, occurred_at: str | None = None, correlation_id: str | None = None,
    ) -> dict:
        event_type, source, idempotency_key = (
            str(event_type).strip(), str(source).strip(), str(idempotency_key).strip()
        )
        if not event_type or len(event_type) > 120:
            raise ValueError("event_type must contain 1-120 characters")
        if not source or len(source) > 120:
            raise ValueError("source must contain 1-120 characters")
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("idempotency_key must contain 1-200 characters")
        payload = _json_object(payload, "payload")
        event_id, now = str(uuid4()), _now()
        event_time = occurred_at or now
        try:
            with self.db:
                self.db.execute("""INSERT INTO air_workflow_events
                    (event_id,event_type,source,occurred_at,payload_json,idempotency_key,correlation_id,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""", (
                    event_id, event_type, source, event_time,
                    json.dumps(payload, allow_nan=False), idempotency_key, correlation_id, now,
                ))
                self.db.execute("""INSERT INTO air_workflow_outbox
                    (outbox_id,event_id,status,attempts,available_at)
                    VALUES(?,?,'PENDING',0,?)""", (str(uuid4()), event_id, now))
        except Exception as exc:
            # A duplicate idempotency key is a successful replay, not a second event.
            existing = self.db.execute(
                "SELECT * FROM air_workflow_events WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if existing:
                return self._decode_event(existing, duplicate=True)
            raise exc
        row = self.db.execute("SELECT * FROM air_workflow_events WHERE event_id=?", (event_id,)).fetchone()
        return self._decode_event(row, duplicate=False)

    @staticmethod
    def _decode_event(row: Any, *, duplicate: bool) -> dict:
        return {
            "event_id": row["event_id"], "event_type": row["event_type"], "source": row["source"],
            "occurred_at": row["occurred_at"], "payload": json.loads(row["payload_json"]),
            "idempotency_key": row["idempotency_key"], "correlation_id": row["correlation_id"],
            "created_at": row["created_at"], "duplicate": duplicate,
        }


    def set_workflow_enabled(self, workflow_id: str, enabled: bool) -> dict | None:
        now = _now()
        with self.db:
            self.db.execute(
                "UPDATE air_workflow_definitions SET enabled=?,updated_at=? WHERE workflow_id=?",
                (bool(enabled), now, workflow_id),
            )
        return self.get_workflow(workflow_id)

    def pending_outbox(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        rows = self.db.execute(
            """SELECT o.outbox_id,o.event_id,o.attempts,e.event_type,e.source,e.occurred_at,
                      e.payload_json,e.idempotency_key,e.correlation_id
               FROM air_workflow_outbox o JOIN air_workflow_events e ON e.event_id=o.event_id
               WHERE o.status='PENDING' AND o.available_at<=?
               ORDER BY o.available_at LIMIT ?""", (_now(), limit),
        ).fetchall()
        return [{
            "outbox_id": row["outbox_id"], "event_id": row["event_id"],
            "attempts": row["attempts"], "event_type": row["event_type"],
            "source": row["source"], "occurred_at": row["occurred_at"],
            "payload": json.loads(row["payload_json"]),
            "idempotency_key": row["idempotency_key"], "correlation_id": row["correlation_id"],
        } for row in rows]

    def mark_outbox_published(self, outbox_id: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE air_workflow_outbox SET status='PUBLISHED',published_at=?,last_error=NULL WHERE outbox_id=?",
                (_now(), outbox_id),
            )

    def mark_outbox_failed(self, outbox_id: str, attempts: int, error: str, max_attempts: int = 12) -> None:
        next_attempt = max(1, int(attempts) + 1)
        delay = min(300, 2 ** min(next_attempt, 8))
        status = "FAILED" if next_attempt >= max_attempts else "PENDING"
        available = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + delay, timezone.utc
        ).isoformat()
        with self.db:
            self.db.execute(
                """UPDATE air_workflow_outbox SET status=?,attempts=?,available_at=?,last_error=?
                   WHERE outbox_id=?""",
                (status, next_attempt, available, str(error)[:500], outbox_id),
            )

    def process_event(self, event_id: str) -> list[dict]:
        event = self.db.execute(
            "SELECT * FROM air_workflow_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if not event:
            raise ValueError("Workflow event does not exist")
        payload = json.loads(event["payload_json"])
        definitions = self.db.execute(
            "SELECT * FROM air_workflow_definitions WHERE enabled=? ORDER BY created_at",
            (True,),
        ).fetchall()
        created = []
        for definition in definitions:
            config = json.loads(definition["trigger_config_json"])
            trigger_type = definition["trigger_type"]
            if trigger_type == "TIME":
                matched = payload.get("workflow_id") == definition["workflow_id"]
            else:
                event_types = config.get("event_types")
                if not isinstance(event_types, list):
                    event_types = [config.get("event_type")] if config.get("event_type") else []
                matched = event["event_type"] in event_types
            if not matched:
                continue
            run_id = str(uuid4())
            now = _now()
            with self.db:
                self.db.execute(
                    """INSERT INTO air_workflow_runs
                       (run_id,workflow_id,workflow_version,event_id,status,execution_mode,
                        started_at,completed_at,error)
                       VALUES(?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(workflow_id,workflow_version,event_id) DO NOTHING""",
                    (run_id, definition["workflow_id"], definition["version"], event_id,
                     "QUEUED", definition["execution_mode"], now, None, None),
                )
            row = self.db.execute(
                """SELECT * FROM air_workflow_runs
                   WHERE workflow_id=? AND workflow_version=? AND event_id=?""",
                (definition["workflow_id"], definition["version"], event_id),
            ).fetchone()
            if row:
                created.append({
                    "run_id": row["run_id"], "workflow_id": row["workflow_id"],
                    "workflow_version": row["workflow_version"], "event_id": row["event_id"],
                    "status": row["status"], "duplicate": row["run_id"] != run_id,
                })
        return created

    def due_time_workflows(self, now: datetime | None = None) -> list[dict]:
        current = now or datetime.now(timezone.utc)
        rows = self.db.execute(
            "SELECT * FROM air_workflow_definitions WHERE enabled=? AND trigger_type='TIME'",
            (True,),
        ).fetchall()
        due = []
        for row in rows:
            config = json.loads(row["trigger_config_json"])
            timezone_name = str(config.get("timezone", "Asia/Kolkata"))
            try:
                from zoneinfo import ZoneInfo
                local = current.astimezone(ZoneInfo(timezone_name))
                hour, minute = int(config["hour"]), int(config["minute"])
                days = config.get("days_of_week", [0, 1, 2, 3, 4])
                if not isinstance(days, list):
                    raise ValueError("days_of_week must be an array")
                days = {int(day) for day in days}
                grace = int(config.get("misfire_grace_seconds", 300))
            except (KeyError, TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"Invalid time trigger configuration for workflow {row['workflow_id']}") from exc
            if not 0 <= hour <= 23 or not 0 <= minute <= 59 or any(day < 0 or day > 6 for day in days) or not 0 <= grace <= 86400:
                raise ValueError(f"Invalid time trigger configuration for workflow {row['workflow_id']}")
            scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            lateness = (local - scheduled).total_seconds()
            if local.weekday() in days and 0 <= lateness <= grace:
                due.append({
                    "workflow_id": row["workflow_id"], "name": row["name"],
                    "local_time": scheduled.isoformat(), "scheduled_key": scheduled.strftime("%Y%m%d%H%M"),
                })
        return due

    def list_runs(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM air_workflow_runs ORDER BY started_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [{
            "run_id": row["run_id"], "workflow_id": row["workflow_id"],
            "workflow_version": row["workflow_version"], "event_id": row["event_id"],
            "status": row["status"], "execution_mode": row["execution_mode"],
            "started_at": row["started_at"], "completed_at": row["completed_at"], "error": row["error"],
        } for row in rows]

    def close(self) -> None:
        self.db.close()
