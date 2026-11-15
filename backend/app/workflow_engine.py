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

    def close(self) -> None:
        self.db.close()
