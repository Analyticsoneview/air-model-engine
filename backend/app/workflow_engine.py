"""AIR workflow engine persistence: definitions, events, outbox, runs and operations.

PostgreSQL is the production system of record. SQLite remains the local/test path.
The transactional outbox decouples durable event acceptance from RabbitMQ delivery.
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
from app.tenant_context import current_customer_id, current_tenant_id

TRIGGER_TYPES = {"EVENT", "TIME", "STRATEGY", "CONDITION"}
EXECUTION_MODES = {"RESEARCH_ONLY", "ALERT_NOTIFY"}
WORKFLOW_ACTIONS = {"qoc.qualify", "qoc.backtest", "portfolio.overview", "notify.telegram", "event.emit", "monthly_pd.evaluate"}
TELEGRAM_STRATEGIES = {"RECOVERED", "EXPIRY78", "EXPIRYSCAN", "AIR_QOC", "ORB", "PORTFOLIO_RISK", "AIR_WORKFLOW"}


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



_MISSING = object()


def _value_at_path(payload: dict, path: str):
    value: Any = payload
    for part in str(path).split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return _MISSING
    return value


def _condition_matches(payload: dict, condition: dict) -> bool:
    if not isinstance(condition, dict) or not condition.get("field"):
        return False
    actual = _value_at_path(payload, condition["field"])
    operator = str(condition.get("operator", "eq")).lower()
    expected = condition.get("value")
    if operator == "exists":
        return (actual is not _MISSING) is bool(expected if expected is not None else True)
    if actual is _MISSING:
        return False
    if operator == "in":
        return isinstance(expected, list) and actual in expected
    if operator == "not_in":
        return isinstance(expected, list) and actual not in expected
    if operator == "contains":
        try:
            return expected in actual
        except (TypeError, ValueError):
            return False
    left, right = actual, expected
    if operator in {"gt", "gte", "lt", "lte"}:
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
    if operator == "eq":
        return left == right
    if operator == "neq":
        return left != right
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    return False


def _conditions_match(payload: dict, config: dict) -> bool:
    conditions = config.get("filters", config.get("conditions"))
    if isinstance(conditions, dict):
        conditions = [conditions]
    if not isinstance(conditions, list) or not conditions:
        return False
    outcomes = [_condition_matches(payload, condition) for condition in conditions]
    mode = str(config.get("match", "ALL")).upper()
    if mode == "ANY":
        return any(outcomes)
    if mode == "ALL":
        return all(outcomes)
    return False


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
                self.db.execute("SELECT 1 FROM air_workflow_run_steps LIMIT 0")
                self.db.execute("SELECT 1 FROM air_workflow_definition_versions LIMIT 0")
                self.db.execute("SELECT 1 FROM air_workflow_audit LIMIT 0")
                self.db.execute("SELECT 1 FROM air_exchange_calendar LIMIT 0")
                self.db.execute("SELECT 1 FROM air_workflow_worker_heartbeats LIMIT 0")
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
                created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                customer_id TEXT, tenant_id TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_enabled_trigger
                ON air_workflow_definitions(enabled,trigger_type);
            CREATE TABLE IF NOT EXISTS air_workflow_definition_versions (
                workflow_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version >= 1),
                name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                trigger_type TEXT NOT NULL, trigger_config_json TEXT NOT NULL DEFAULT '{}',
                workflow_spec_json TEXT NOT NULL DEFAULT '{}', execution_mode TEXT NOT NULL,
                created_by TEXT NOT NULL, created_at TEXT NOT NULL,
                customer_id TEXT, tenant_id TEXT,
                PRIMARY KEY(workflow_id,version)
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_definition_versions_created
                ON air_workflow_definition_versions(workflow_id,created_at);
            INSERT OR IGNORE INTO air_workflow_definition_versions
                (workflow_id,version,name,description,trigger_type,trigger_config_json,
                 workflow_spec_json,execution_mode,created_by,created_at)
            SELECT workflow_id,version,name,description,trigger_type,trigger_config_json,
                   workflow_spec_json,execution_mode,created_by,created_at
            FROM air_workflow_definitions;
            CREATE TABLE IF NOT EXISTS air_workflow_events (
                event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, source TEXT NOT NULL,
                occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
                idempotency_key TEXT NOT NULL UNIQUE, correlation_id TEXT, created_at TEXT NOT NULL,
                customer_id TEXT, tenant_id TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_events_type_time
                ON air_workflow_events(event_type,occurred_at);
            CREATE TABLE IF NOT EXISTS air_workflow_outbox (
                outbox_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING','PUBLISHED','FAILED')),
                attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL,
                published_at TEXT, last_error TEXT, customer_id TEXT, tenant_id TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_outbox_pending
                ON air_workflow_outbox(status,available_at);
            CREATE TABLE IF NOT EXISTS air_workflow_runs (
                run_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, workflow_version INTEGER NOT NULL,
                event_id TEXT NOT NULL, status TEXT NOT NULL, execution_mode TEXT NOT NULL,
                started_at TEXT NOT NULL, completed_at TEXT, error TEXT,
                claimed_by TEXT, claimed_at TEXT, lease_expires_at TEXT,
                claim_version INTEGER NOT NULL DEFAULT 0, customer_id TEXT, tenant_id TEXT,
                UNIQUE(workflow_id,workflow_version,event_id)
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_runs_status_time
                ON air_workflow_runs(status,started_at);
            CREATE TABLE IF NOT EXISTS air_workflow_run_steps (
                step_record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_key TEXT NOT NULL,
                step_index INTEGER NOT NULL, action TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','SKIPPED')),
                input_json TEXT NOT NULL DEFAULT '{}', output_json TEXT, error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, started_at TEXT, completed_at TEXT,
                customer_id TEXT, tenant_id TEXT,
                UNIQUE(run_id,step_key)
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_run_steps_order
                ON air_workflow_run_steps(run_id,step_index);
            CREATE TABLE IF NOT EXISTS air_workflow_audit (
                audit_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
                workflow_version INTEGER NOT NULL, actor_id TEXT NOT NULL,
                action TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, customer_id TEXT, tenant_id TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_audit_workflow_time
                ON air_workflow_audit(workflow_id,created_at);
            CREATE TRIGGER IF NOT EXISTS trg_air_workflow_audit_no_update
                BEFORE UPDATE ON air_workflow_audit BEGIN
                    SELECT RAISE(ABORT, 'AIR workflow audit is append-only');
                END;
            CREATE TRIGGER IF NOT EXISTS trg_air_workflow_audit_no_delete
                BEFORE DELETE ON air_workflow_audit BEGIN
                    SELECT RAISE(ABORT, 'AIR workflow audit is append-only');
                END;
            CREATE TABLE IF NOT EXISTS air_exchange_calendar (
                exchange_code TEXT NOT NULL, session_date TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('HOLIDAY','SPECIAL_SESSION','TRADING_DAY')),
                description TEXT NOT NULL DEFAULT '', session_open TEXT, session_close TEXT,
                source TEXT NOT NULL DEFAULT 'ADMIN', updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(exchange_code,session_date)
            );
            CREATE INDEX IF NOT EXISTS ix_air_exchange_calendar_date
                ON air_exchange_calendar(session_date,exchange_code);
            CREATE TABLE IF NOT EXISTS air_workflow_worker_heartbeats (
                worker_id TEXT NOT NULL, component TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('STARTING','RUNNING','DEGRADED','STOPPING')),
                details_json TEXT NOT NULL DEFAULT '{}', started_at TEXT NOT NULL,
                last_seen TEXT NOT NULL, PRIMARY KEY(worker_id,component)
            );
            CREATE INDEX IF NOT EXISTS ix_air_workflow_worker_heartbeat_seen
                ON air_workflow_worker_heartbeats(last_seen);
        """)
        # Upgrade pre-existing local SQLite databases without requiring Alembic.
        columns = {row["name"] for row in self.db.execute(
            "PRAGMA table_info(air_workflow_runs)"
        ).fetchall()}
        for name, definition in (
            ("claimed_by", "TEXT"), ("claimed_at", "TEXT"),
            ("lease_expires_at", "TEXT"),
            ("claim_version", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                self.db.execute(f"ALTER TABLE air_workflow_runs ADD COLUMN {name} {definition}")
        self.db.execute("""CREATE INDEX IF NOT EXISTS ix_air_workflow_runs_lease
            ON air_workflow_runs(status,lease_expires_at,started_at)""")
        for table in (
            "air_workflow_definitions", "air_workflow_definition_versions",
            "air_workflow_events", "air_workflow_outbox", "air_workflow_runs",
            "air_workflow_run_steps", "air_workflow_audit",
        ):
            existing = {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})").fetchall()}
            for column in ("customer_id", "tenant_id"):
                if column not in existing:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
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
        request_customer = current_customer_id()
        configured_customer = str(trigger_config.get("customer_id") or "").strip() or None
        if request_customer and configured_customer and configured_customer != request_customer:
            raise PermissionError("Workflow customer scope cannot be changed by the caller")
        customer_id = configured_customer or request_customer
        tenant_id = current_tenant_id()
        if customer_id:
            trigger_config["customer_id"] = customer_id
        workflow_spec = _json_object(workflow_spec, "workflow_spec")
        steps = workflow_spec.get("steps", [])
        if not isinstance(steps, list) or len(steps) > 20:
            raise ValueError("workflow_spec.steps must be an array containing at most 20 steps")
        seen_step_ids: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("Each workflow step must be an object")
            step_id = str(step.get("id") or "").strip()
            action = str(step.get("action") or "").strip().lower()
            params = step.get("params", {})
            if not step_id or len(step_id) > 64 or step_id in seen_step_ids:
                raise ValueError("Workflow step IDs must be unique and contain 1-64 characters")
            if action not in WORKFLOW_ACTIONS:
                raise ValueError(f"Unsupported workflow action: {action or 'missing'}")
            if not isinstance(params, dict):
                raise ValueError(f"Workflow step {step_id} params must be an object")
            attempts = step.get("max_attempts", 3)
            if not isinstance(attempts, int) or not 1 <= attempts <= 5:
                raise ValueError(f"Workflow step {step_id} max_attempts must be between 1 and 5")
            if action == "notify.telegram" and execution_mode != "ALERT_NOTIFY":
                raise ValueError("Telegram notification steps require ALERT_NOTIFY execution mode")
            if action == "notify.telegram":
                strategy = str(params.get("strategy") or "AIR_WORKFLOW").upper()
                if strategy not in TELEGRAM_STRATEGIES:
                    raise ValueError(f"Unsupported Telegram strategy route: {strategy}")
            if action == "event.emit" and not str(params.get("event_type") or "").strip():
                raise ValueError(f"Workflow step {step_id} event.emit requires params.event_type")
            source_step = params.get("source_step")
            if source_step and source_step not in seen_step_ids:
                raise ValueError(f"Workflow step {step_id} source_step must reference an earlier step")
            seen_step_ids.add(step_id)
        workflow_id, now = str(uuid4()), _now()
        with self.db:
            self.db.execute("""INSERT INTO air_workflow_definitions
                (workflow_id,name,description,trigger_type,trigger_config_json,workflow_spec_json,
                 execution_mode,version,enabled,created_by,created_at,updated_at,customer_id,tenant_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                workflow_id, name, str(description)[:4000], trigger_type,
                json.dumps(trigger_config, allow_nan=False), json.dumps(workflow_spec, allow_nan=False),
                execution_mode, 1, False if self.is_postgres else 0, created_by, now, now, customer_id, tenant_id,
            ))
            self.db.execute("""INSERT INTO air_workflow_definition_versions
                (workflow_id,version,name,description,trigger_type,trigger_config_json,
                 workflow_spec_json,execution_mode,created_by,created_at,customer_id,tenant_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                workflow_id, 1, name, str(description)[:4000], trigger_type,
                json.dumps(trigger_config, allow_nan=False), json.dumps(workflow_spec, allow_nan=False),
                execution_mode, created_by, now, customer_id, tenant_id,
            ))
            self._append_audit(workflow_id, 1, created_by, "CREATED",
                               {"name": name, "trigger_type": trigger_type, "execution_mode": execution_mode})
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
            "customer_id": row["customer_id"], "tenant_id": row["tenant_id"],
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
        request_customer = current_customer_id()
        event_customer = str(payload.get("customer_id") or request_customer or "").strip() or None
        event_tenant = current_tenant_id()
        if request_customer and event_customer and event_customer != request_customer:
            raise PermissionError("Workflow event tenant scope cannot be changed by the caller")
        if event_customer:
            payload["customer_id"] = event_customer
        event_id, now = str(uuid4()), _now()
        event_time = occurred_at or now
        try:
            with self.db:
                self.db.execute("""INSERT INTO air_workflow_events
                    (event_id,event_type,source,occurred_at,payload_json,idempotency_key,correlation_id,created_at,customer_id,tenant_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                    event_id, event_type, source, event_time,
                    json.dumps(payload, allow_nan=False), idempotency_key, correlation_id, now, event_customer, event_tenant,
                ))
                self.db.execute("""INSERT INTO air_workflow_outbox
                    (outbox_id,event_id,status,attempts,available_at,customer_id,tenant_id)
                    VALUES(?,?,'PENDING',0,?,?,?)""", (str(uuid4()), event_id, now, event_customer, event_tenant))
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
            "created_at": row["created_at"], "customer_id": row["customer_id"],
            "tenant_id": row["tenant_id"], "duplicate": duplicate,
        }


    def list_workflow_versions(self, workflow_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM air_workflow_definition_versions WHERE workflow_id=? ORDER BY version DESC",
            (workflow_id,),
        ).fetchall()
        return [{
            "workflow_id": row["workflow_id"], "version": row["version"],
            "name": row["name"], "description": row["description"],
            "trigger_type": row["trigger_type"],
            "trigger_config": json.loads(row["trigger_config_json"]),
            "workflow_spec": json.loads(row["workflow_spec_json"]),
            "execution_mode": row["execution_mode"],
            "created_by": row["created_by"], "created_at": row["created_at"],
            "customer_id": row["customer_id"], "tenant_id": row["tenant_id"],
        } for row in rows]

    def update_workflow(
        self, workflow_id: str, *, name: str, description: str,
        trigger_type: str, trigger_config: dict, workflow_spec: dict,
        execution_mode: str, updated_by: str,
    ) -> dict | None:
        current = self.get_workflow(workflow_id)
        if current is None:
            return None
        name = str(name).strip()
        description = str(description or "")[:4000]
        trigger_type = str(trigger_type).upper()
        execution_mode = str(execution_mode).upper()
        updated_by = str(updated_by).strip()
        if not name or len(name) > 120 or not updated_by or len(updated_by) > 128:
            raise ValueError("Workflow name and updated_by are required and bounded")
        if trigger_type not in TRIGGER_TYPES or execution_mode not in EXECUTION_MODES:
            raise ValueError("Unsupported workflow trigger or execution mode")
        trigger_config = _json_object(trigger_config, "trigger_config")
        request_customer = current_customer_id()
        configured_customer = str(trigger_config.get("customer_id") or "").strip() or None
        if request_customer and configured_customer and configured_customer != request_customer:
            raise PermissionError("Workflow customer scope cannot be changed by the caller")
        customer_id = current.get("customer_id") or configured_customer or request_customer
        if current.get("customer_id") and configured_customer and configured_customer != current["customer_id"]:
            raise PermissionError("Workflow ownership cannot be transferred by update")
        if customer_id:
            trigger_config["customer_id"] = customer_id
        workflow_spec = _json_object(workflow_spec, "workflow_spec")
        steps = workflow_spec.get("steps", [])
        if not isinstance(steps, list) or len(steps) > 20:
            raise ValueError("workflow_spec.steps must be an array containing at most 20 steps")
        seen: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("Each workflow step must be an object")
            step_id = str(step.get("id") or "").strip()
            action = str(step.get("action") or "").strip().lower()
            params = step.get("params", {})
            if not step_id or len(step_id) > 64 or step_id in seen:
                raise ValueError("Workflow step IDs must be unique and contain 1-64 characters")
            if action not in WORKFLOW_ACTIONS or not isinstance(params, dict):
                raise ValueError(f"Unsupported action or params for workflow step {step_id}")
            attempts = step.get("max_attempts", 3)
            if not isinstance(attempts, int) or not 1 <= attempts <= 5:
                raise ValueError(f"Workflow step {step_id} max_attempts must be between 1 and 5")
            if action == "notify.telegram":
                if execution_mode != "ALERT_NOTIFY":
                    raise ValueError("Telegram notification steps require ALERT_NOTIFY execution mode")
                strategy = str(params.get("strategy") or "AIR_WORKFLOW").upper()
                if strategy not in TELEGRAM_STRATEGIES:
                    raise ValueError(f"Unsupported Telegram strategy route: {strategy}")
            if action == "event.emit" and not str(params.get("event_type") or "").strip():
                raise ValueError(f"Workflow step {step_id} event.emit requires params.event_type")
            if params.get("source_step") and params["source_step"] not in seen:
                raise ValueError(f"Workflow step {step_id} source_step must reference an earlier step")
            seen.add(step_id)
        version = int(current["version"]) + 1
        now = _now()
        with self.db:
            self.db.execute(
                """UPDATE air_workflow_definitions
                   SET name=?,description=?,trigger_type=?,trigger_config_json=?,
                       workflow_spec_json=?,execution_mode=?,version=?,enabled=?,updated_at=?
                   WHERE workflow_id=?""",
                (name, description, trigger_type,
                 json.dumps(trigger_config, allow_nan=False),
                 json.dumps(workflow_spec, allow_nan=False), execution_mode,
                 version, False if self.is_postgres else 0, now, workflow_id),
            )
            self.db.execute(
                """INSERT INTO air_workflow_definition_versions
                   (workflow_id,version,name,description,trigger_type,trigger_config_json,
                    workflow_spec_json,execution_mode,created_by,created_at,customer_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (workflow_id, version, name, description, trigger_type,
                 json.dumps(trigger_config, allow_nan=False),
                 json.dumps(workflow_spec, allow_nan=False), execution_mode, updated_by, now,
                 current.get("customer_id") or current_customer_id()),
            )
            if bool(current["enabled"]):
                self._append_audit(workflow_id, int(current["version"]), updated_by,
                                   "DISABLED", {"reason": "definition_changed"})
            self._append_audit(workflow_id, version, updated_by, "UPDATED",
                               {"name": name, "trigger_type": trigger_type, "execution_mode": execution_mode})
        return self.get_workflow(workflow_id)


    def set_workflow_enabled(self, workflow_id: str, enabled: bool, actor_id: str = "system") -> dict | None:
        current = self.get_workflow(workflow_id)
        if current is None:
            return None
        enabled = bool(enabled)
        now = _now()
        with self.db:
            self.db.execute(
                "UPDATE air_workflow_definitions SET enabled=?,updated_at=? WHERE workflow_id=?",
                (enabled, now, workflow_id),
            )
            if bool(current["enabled"]) != enabled:
                self._append_audit(workflow_id, int(current["version"]), actor_id,
                                   "ENABLED" if enabled else "DISABLED", {})
        return self.get_workflow(workflow_id)

    def _append_audit(self, workflow_id: str, version: int, actor_id: str,
                      action: str, payload: dict | None = None) -> None:
        owner = self.db.execute(
            "SELECT customer_id FROM air_workflow_definitions WHERE workflow_id=?",
            (str(workflow_id),),
        ).fetchone()
        customer_id = owner["customer_id"] if owner else current_customer_id()
        self.db.execute(
            """INSERT INTO air_workflow_audit
               (audit_id,workflow_id,workflow_version,actor_id,action,payload_json,created_at,customer_id)
               VALUES(?,?,?,?,?,?,?,?)""",
            (str(uuid4()), str(workflow_id), int(version), str(actor_id)[:128],
             str(action)[:48], json.dumps(_json_object(payload, "audit payload"), allow_nan=False),
             _now(), customer_id),
        )

    def list_workflow_audit(self, workflow_id: str | None = None, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        if workflow_id:
            rows = self.db.execute(
                "SELECT * FROM air_workflow_audit WHERE workflow_id=? ORDER BY created_at DESC,audit_id DESC LIMIT ?",
                (workflow_id, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM air_workflow_audit ORDER BY created_at DESC,audit_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{
            "audit_id": row["audit_id"], "workflow_id": row["workflow_id"],
            "customer_id": row["customer_id"], "tenant_id": row["tenant_id"],
            "workflow_version": row["workflow_version"], "actor_id": row["actor_id"],
            "action": row["action"], "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        } for row in rows]

    @staticmethod
    def _validate_exchange_calendar_day(exchange_code: str, session_date: str, status: str,
                                        session_open: str | None, session_close: str | None) -> tuple[str, str, str]:
        from datetime import date, time
        exchange_code = str(exchange_code).strip().upper()
        status = str(status).strip().upper()
        if exchange_code not in {"NSE", "BSE"}:
            raise ValueError("exchange_code must be NSE or BSE")
        try:
            parsed_date = date.fromisoformat(str(session_date))
        except ValueError as exc:
            raise ValueError("session_date must use YYYY-MM-DD") from exc
        if parsed_date.isoformat() != str(session_date):
            raise ValueError("session_date must use YYYY-MM-DD")
        if status not in {"HOLIDAY", "SPECIAL_SESSION", "TRADING_DAY"}:
            raise ValueError("status must be HOLIDAY, SPECIAL_SESSION or TRADING_DAY")
        def valid_time(value: str | None) -> bool:
            if value is None:
                return False
            try:
                return time.fromisoformat(value).strftime("%H:%M") == value
            except ValueError:
                return False
        if status == "SPECIAL_SESSION":
            if not valid_time(session_open) or not valid_time(session_close) or session_open >= session_close:
                raise ValueError("SPECIAL_SESSION requires valid session_open and session_close (HH:MM)")
        elif session_open is not None or session_close is not None:
            if not valid_time(session_open) or not valid_time(session_close) or session_open >= session_close:
                raise ValueError("session_open and session_close must both be valid HH:MM values")
        return exchange_code, parsed_date.isoformat(), status

    def set_exchange_calendar_day(self, *, exchange_code: str, session_date: str, status: str,
                                  updated_by: str, description: str = "", session_open: str | None = None,
                                  session_close: str | None = None, source: str = "ADMIN") -> dict:
        exchange_code, session_date, status = self._validate_exchange_calendar_day(
            exchange_code, session_date, status, session_open, session_close)
        updated_by = str(updated_by).strip()
        if not updated_by or len(updated_by) > 128:
            raise ValueError("updated_by must contain 1-128 characters")
        if len(str(description)) > 240 or len(str(source)) > 240:
            raise ValueError("description and source must be at most 240 characters")
        now = _now()
        with self.db:
            self.db.execute(
                """INSERT INTO air_exchange_calendar
                   (exchange_code,session_date,status,description,session_open,session_close,source,updated_by,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(exchange_code,session_date) DO UPDATE SET
                     status=excluded.status,description=excluded.description,
                     session_open=excluded.session_open,session_close=excluded.session_close,
                     source=excluded.source,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                (exchange_code, session_date, status, str(description), session_open, session_close,
                 str(source), updated_by, now),
            )
            self._append_audit(f"exchange-calendar:{exchange_code}:{session_date}", 1, updated_by,
                               "EXCHANGE_CALENDAR_SET", {"exchange_code": exchange_code,
                               "session_date": session_date, "status": status, "source": source})
        return self.get_exchange_calendar_day(exchange_code, session_date)

    def get_exchange_calendar_day(self, exchange_code: str, session_date: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM air_exchange_calendar WHERE exchange_code=? AND session_date=?",
            (str(exchange_code).upper(), str(session_date)),
        ).fetchone()
        return self._decode_exchange_calendar(row) if row else None

    @staticmethod
    def _decode_exchange_calendar(row: Any) -> dict:
        return {key: row[key] for key in ("exchange_code", "session_date", "status", "description",
                "session_open", "session_close", "source", "updated_by", "updated_at")}

    def list_exchange_calendar(self, exchange_code: str, start_date: str, end_date: str) -> list[dict]:
        exchange_code = str(exchange_code).strip().upper()
        if exchange_code not in {"NSE", "BSE"}:
            raise ValueError("exchange_code must be NSE or BSE")
        try:
            start = datetime.fromisoformat(start_date).date().isoformat()
            end = datetime.fromisoformat(end_date).date().isoformat()
        except ValueError as exc:
            raise ValueError("Calendar range must use YYYY-MM-DD") from exc
        if start > end:
            raise ValueError("start_date must not be after end_date")
        rows = self.db.execute(
            "SELECT * FROM air_exchange_calendar WHERE exchange_code=? AND session_date>=? AND session_date<=? ORDER BY session_date",
            (exchange_code, start, end),
        ).fetchall()
        return [self._decode_exchange_calendar(row) for row in rows]

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
            workflow_chain = payload.get("workflow_chain")
            if isinstance(workflow_chain, list) and definition["workflow_id"] in workflow_chain:
                continue
            definition_customer = definition["customer_id"] or config.get("customer_id")
            definition_tenant = definition["tenant_id"]
            event_tenant = event["tenant_id"]
            if definition_tenant and event_tenant != definition_tenant:
                continue
            if trigger_type == "TIME":
                matched = payload.get("workflow_id") == definition["workflow_id"]
            else:
                event_types = config.get("event_types")
                if not isinstance(event_types, list):
                    event_types = [config.get("event_type")] if config.get("event_type") else []
                matched = event["event_type"] in event_types
                if matched and trigger_type == "STRATEGY" and config.get("strategy"):
                    matched = str(payload.get("strategy") or "").upper() == str(config["strategy"]).upper()
                if matched and trigger_type == "CONDITION":
                    matched = _conditions_match(payload, config)
            if not matched:
                continue
            run_id = str(uuid4())
            now = _now()
            run_customer = definition["customer_id"] or event["customer_id"]
            run_tenant = definition["tenant_id"] or event["tenant_id"]
            with self.db:
                self.db.execute(
                    """INSERT INTO air_workflow_runs
                       (run_id,workflow_id,workflow_version,event_id,status,execution_mode,
                        started_at,completed_at,error,customer_id,tenant_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(workflow_id,workflow_version,event_id) DO NOTHING""",
                    (run_id, definition["workflow_id"], definition["version"], event_id,
                     "QUEUED", definition["execution_mode"], now, None, None,
                     run_customer, run_tenant),
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
                    "status": row["status"], "customer_id": row["customer_id"],
                    "tenant_id": row["tenant_id"], "duplicate": row["run_id"] != run_id,
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
                exchange_code = str(config.get("exchange_code") or "").strip().upper()
                if exchange_code:
                    session = self.get_exchange_calendar_day(exchange_code, local.date().isoformat())
                    # Explicit exchange calendars fail closed: an unlisted date is not tradable.
                    if not session or session["status"] == "HOLIDAY":
                        continue
                    scheduled_hhmm = scheduled.strftime("%H:%M")
                    if session["status"] == "SPECIAL_SESSION":
                        if not session["session_open"] or not session["session_close"] or not (session["session_open"] <= scheduled_hhmm <= session["session_close"]):
                            continue
                    # TRADING_DAY means the exchange is open on this date. Do not
                    # constrain the trigger clock: post-market reports are valid too.
                    # SPECIAL_SESSION remains bounded by its explicit session hours.
                due.append({
                    "workflow_id": row["workflow_id"], "name": row["name"],
                    "customer_id": row["customer_id"] or config.get("customer_id"),
                    "tenant_id": row["tenant_id"],
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
            "customer_id": row["customer_id"], "tenant_id": row["tenant_id"],
            "status": row["status"], "execution_mode": row["execution_mode"],
            "started_at": row["started_at"], "completed_at": row["completed_at"], "error": row["error"],
        } for row in rows]

    def runnable_runs(self, limit: int = 20) -> list[str]:
        """Compatibility listing only; workers must use claim_runnable_runs."""
        rows = self.db.execute(
            "SELECT run_id FROM air_workflow_runs WHERE status IN ('QUEUED','RUNNING') ORDER BY started_at LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [row["run_id"] for row in rows]

    def claim_runnable_runs(
        self, worker_id: str, limit: int = 20, lease_seconds: int = 60,
    ) -> list[dict]:
        """Atomically claim eligible runs; expired leases are recoverable after a crash."""
        worker_id = str(worker_id).strip()
        if not worker_id or len(worker_id) > 160:
            raise ValueError("worker_id must contain 1-160 characters")
        limit = max(1, min(int(limit), 100))
        lease_seconds = max(15, min(int(lease_seconds), 3600))
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        expires = (now_dt.timestamp() + lease_seconds)
        lease_until = datetime.fromtimestamp(expires, timezone.utc).isoformat()
        claimed = []
        if self.is_postgres:
            with self.db:
                rows = self.db.execute(
                    """SELECT run_id,customer_id,tenant_id FROM air_workflow_runs
                       WHERE status IN ('QUEUED','RUNNING')
                         AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                       ORDER BY started_at LIMIT ? FOR UPDATE SKIP LOCKED""", (now, limit),
                ).fetchall()
                for row in rows:
                    version = self.db.execute(
                        """UPDATE air_workflow_runs
                           SET claimed_by=?,claimed_at=?,lease_expires_at=?,
                               claim_version=claim_version+1,status='RUNNING',
                               started_at=COALESCE(started_at,?),completed_at=NULL
                           WHERE run_id=? RETURNING claim_version""",
                        (worker_id, now, lease_until, now, row["run_id"]),
                    ).fetchone()
                    claimed.append({"run_id": row["run_id"], "worker_id": worker_id,
                                    "claim_version": version["claim_version"],
                                    "customer_id": row["customer_id"], "tenant_id": row["tenant_id"]})
        else:
            # BEGIN IMMEDIATE serializes claimers before selecting candidates.
            self.db.execute("BEGIN IMMEDIATE")
            try:
                rows = self.db.execute(
                    """SELECT run_id,customer_id,tenant_id FROM air_workflow_runs
                       WHERE status IN ('QUEUED','RUNNING')
                         AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                       ORDER BY started_at LIMIT ?""", (now, limit),
                ).fetchall()
                for row in rows:
                    cur = self.db.execute(
                        """UPDATE air_workflow_runs
                           SET claimed_by=?,claimed_at=?,lease_expires_at=?,
                               claim_version=claim_version+1,status='RUNNING',
                               started_at=COALESCE(started_at,?),completed_at=NULL
                           WHERE run_id=? AND status IN ('QUEUED','RUNNING')
                             AND (lease_expires_at IS NULL OR lease_expires_at <= ?)""",
                        (worker_id, now, lease_until, now, row["run_id"], now),
                    )
                    if cur.rowcount:
                        version = self.db.execute(
                            "SELECT claim_version FROM air_workflow_runs WHERE run_id=?",
                            (row["run_id"],),
                        ).fetchone()
                        claimed.append({"run_id": row["run_id"], "worker_id": worker_id,
                                        "claim_version": version["claim_version"],
                                        "customer_id": row["customer_id"], "tenant_id": row["tenant_id"]})
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return claimed

    def renew_run_lease(
        self, run_id: str, worker_id: str, claim_version: int, lease_seconds: int = 60,
    ) -> bool:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        lease_until = datetime.fromtimestamp(
            now_dt.timestamp() + max(15, min(int(lease_seconds), 3600)), timezone.utc
        ).isoformat()
        with self.db:
            cur = self.db.execute(
                """UPDATE air_workflow_runs SET lease_expires_at=?
                   WHERE run_id=? AND status='RUNNING' AND claimed_by=?
                     AND claim_version=? AND lease_expires_at>?""",
                (lease_until, run_id, worker_id, int(claim_version), now),
            )
        return cur.rowcount == 1

    def release_run_claim(
        self, run_id: str, worker_id: str, claim_version: int, error: str | None = None,
    ) -> bool:
        with self.db:
            cur = self.db.execute(
                """UPDATE air_workflow_runs
                   SET claimed_by=NULL,claimed_at=NULL,lease_expires_at=NULL,
                       status='QUEUED',error=?
                   WHERE run_id=? AND status='RUNNING' AND claimed_by=? AND claim_version=?""",
                (str(error)[:1000] if error else None, run_id, worker_id, int(claim_version)),
            )
        return cur.rowcount == 1

    def run_context(self, run_id: str) -> dict | None:
        row = self.db.execute(
            """SELECT r.*,v.name,v.workflow_spec_json,v.trigger_config_json,e.payload_json
               FROM air_workflow_runs r
               JOIN air_workflow_definition_versions v
                 ON v.workflow_id=r.workflow_id AND v.version=r.workflow_version
               JOIN air_workflow_events e ON e.event_id=r.event_id
               WHERE r.run_id=?""", (run_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "run_id": row["run_id"], "workflow_id": row["workflow_id"],
            "workflow_version": row["workflow_version"], "event_id": row["event_id"],
            "customer_id": row["customer_id"], "tenant_id": row["tenant_id"],
            "status": row["status"], "execution_mode": row["execution_mode"],
            "workflow_name": row["name"], "workflow_spec": json.loads(row["workflow_spec_json"]),
            "trigger_config": json.loads(row["trigger_config_json"]),
            "event_payload": json.loads(row["payload_json"]),
        }

    def set_run_status(
        self, run_id: str, status: str, error: str | None = None,
        *, worker_id: str | None = None, claim_version: int | None = None,
    ) -> None:
        status = str(status).upper()
        if status not in {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ValueError("Unsupported workflow run status")
        now = _now()
        with self.db:
            owner_clause = ""
            owner_params: tuple = ()
            if worker_id is not None or claim_version is not None:
                if worker_id is None or claim_version is None:
                    raise ValueError("worker_id and claim_version must be supplied together")
                owner_clause = " AND claimed_by=? AND claim_version=?"
                owner_params = (worker_id, int(claim_version))
            if status == "RUNNING":
                cur = self.db.execute(
                    "UPDATE air_workflow_runs SET status=?,started_at=COALESCE(started_at,?),completed_at=NULL,error=NULL WHERE run_id=?" + owner_clause,
                    (status, now, run_id, *owner_params),
                )
            elif status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                cur = self.db.execute(
                    "UPDATE air_workflow_runs SET status=?,completed_at=?,error=?,claimed_by=NULL,claimed_at=NULL,lease_expires_at=NULL WHERE run_id=?" + owner_clause,
                    (status, now, str(error)[:1000] if error else None, run_id, *owner_params),
                )
            else:
                cur = self.db.execute(
                    "UPDATE air_workflow_runs SET status=?,error=? WHERE run_id=?" + owner_clause,
                    (status, str(error)[:1000] if error else None, run_id, *owner_params),
                )
            if worker_id is not None and cur.rowcount != 1:
                raise RuntimeError("Workflow run claim was lost; stale worker cannot update run status")

    def get_run_step(self, run_id: str, step_key: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM air_workflow_run_steps WHERE run_id=? AND step_key=?",
            (run_id, step_key),
        ).fetchone()
        return self._decode_run_step(row) if row else None

    def save_run_step(
        self, *, run_id: str, step_key: str, step_index: int, action: str,
        status: str, input_data: dict, output_data: dict | list | None = None,
        error: str | None = None, attempts: int = 0,
        worker_id: str | None = None, claim_version: int | None = None,
    ) -> dict:
        status = str(status).upper()
        if status not in {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "SKIPPED"}:
            raise ValueError("Unsupported workflow step status")
        now = _now()
        input_json = json.dumps(input_data, allow_nan=False)
        output_json = json.dumps(output_data, allow_nan=False) if output_data is not None else None
        with self.db:
            if worker_id is not None or claim_version is not None:
                if worker_id is None or claim_version is None:
                    raise ValueError("worker_id and claim_version must be supplied together")
                lock_sql = """SELECT claimed_by,claim_version,lease_expires_at
                              FROM air_workflow_runs WHERE run_id=?"""
                if self.is_postgres:
                    lock_sql += " FOR UPDATE"
                claim = self.db.execute(lock_sql, (run_id,)).fetchone()
                now_check = _now()
                if (not claim or claim["claimed_by"] != worker_id
                        or int(claim["claim_version"]) != int(claim_version)
                        or not claim["lease_expires_at"]
                        or claim["lease_expires_at"] <= now_check):
                    raise RuntimeError("Workflow run claim was lost; stale worker cannot save a step")
            existing = self.get_run_step(run_id, step_key)
            if existing:
                if status == "RUNNING":
                    self.db.execute(
                        """UPDATE air_workflow_run_steps SET status=?,input_json=?,output_json=NULL,
                           error=NULL,attempts=?,started_at=COALESCE(started_at,?),completed_at=NULL
                           WHERE run_id=? AND step_key=?""",
                        (status, input_json, attempts, now, run_id, step_key),
                    )
                else:
                    completed = now if status in {"SUCCEEDED", "FAILED", "SKIPPED"} else None
                    self.db.execute(
                        """UPDATE air_workflow_run_steps SET status=?,input_json=?,output_json=?,
                           error=?,attempts=?,completed_at=? WHERE run_id=? AND step_key=?""",
                        (status, input_json, output_json, str(error)[:1000] if error else None,
                         attempts, completed, run_id, step_key),
                    )
            else:
                self.db.execute(
                    """INSERT INTO air_workflow_run_steps
                       (step_record_id,run_id,step_key,step_index,action,status,input_json,
                        output_json,error,attempts,started_at,completed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid4()), run_id, step_key, step_index, action, status, input_json,
                     output_json, str(error)[:1000] if error else None, attempts,
                     now if status == "RUNNING" else None,
                     now if status in {"SUCCEEDED", "FAILED", "SKIPPED"} else None),
                )
        return self.get_run_step(run_id, step_key)

    @staticmethod
    def _decode_run_step(row: Any) -> dict:
        return {
            "step_record_id": row["step_record_id"], "run_id": row["run_id"],
            "step_key": row["step_key"], "step_index": row["step_index"],
            "action": row["action"], "status": row["status"],
            "input": json.loads(row["input_json"]),
            "output": json.loads(row["output_json"]) if row["output_json"] else None,
            "error": row["error"], "attempts": row["attempts"],
            "started_at": row["started_at"], "completed_at": row["completed_at"],
        }

    def list_run_steps(self, run_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM air_workflow_run_steps WHERE run_id=? ORDER BY step_index",
            (run_id,),
        ).fetchall()
        return [self._decode_run_step(row) for row in rows]


    def record_worker_heartbeat(
        self, *, worker_id: str, component: str, status: str,
        details: dict | None = None, started_at: str | None = None,
    ) -> None:
        status = str(status).upper()
        if status not in {"STARTING", "RUNNING", "DEGRADED", "STOPPING"}:
            raise ValueError("Unsupported workflow worker status")
        worker_id = str(worker_id).strip()
        component = str(component).strip()
        if not worker_id or len(worker_id) > 160 or not component or len(component) > 64:
            raise ValueError("Worker ID and component are required and must fit their limits")
        now = _now()
        details_json = json.dumps(details or {}, allow_nan=False)
        with self.db:
            self.db.execute(
                """INSERT INTO air_workflow_worker_heartbeats
                   (worker_id,component,status,details_json,started_at,last_seen)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(worker_id,component) DO UPDATE SET
                     status=excluded.status,details_json=excluded.details_json,
                     last_seen=excluded.last_seen""",
                (worker_id, component, status, details_json, started_at or now, now),
            )

    def list_worker_heartbeats(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute(
            """SELECT worker_id,component,status,details_json,started_at,last_seen
               FROM air_workflow_worker_heartbeats
               ORDER BY last_seen DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [{
            "worker_id": row["worker_id"], "component": row["component"],
            "status": row["status"], "details": json.loads(row["details_json"]),
            "started_at": row["started_at"], "last_seen": row["last_seen"],
        } for row in rows]

    def runtime_metrics(self) -> dict:
        def counts(table: str) -> dict[str, int]:
            rows = self.db.execute(
                f"SELECT status,COUNT(*) AS total FROM {table} GROUP BY status"
            ).fetchall()
            return {str(row["status"]): int(row["total"]) for row in rows}
        outbox = counts("air_workflow_outbox")
        runs = counts("air_workflow_runs")
        steps = counts("air_workflow_run_steps")
        return {
            "outbox": {"pending": outbox.get("PENDING", 0),
                       "published": outbox.get("PUBLISHED", 0),
                       "failed": outbox.get("FAILED", 0)},
            "runs": {"queued": runs.get("QUEUED", 0), "running": runs.get("RUNNING", 0),
                     "succeeded": runs.get("SUCCEEDED", 0), "failed": runs.get("FAILED", 0),
                     "cancelled": runs.get("CANCELLED", 0)},
            "steps": {"pending": steps.get("PENDING", 0), "running": steps.get("RUNNING", 0),
                      "succeeded": steps.get("SUCCEEDED", 0), "failed": steps.get("FAILED", 0),
                      "skipped": steps.get("SKIPPED", 0)},
        }

    def close(self) -> None:
        self.db.close()
