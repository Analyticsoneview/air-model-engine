"""Idempotent, transactional copy of AIR customer SQLite data into PostgreSQL.

The SQLite source is opened read-only and is never modified or removed.
Apply Alembic migrations first:
  AIR_CUSTOMER_DATABASE_URL=... python -m alembic upgrade head
Then run:
  AIR_CUSTOMER_SQLITE_PATH=... AIR_CUSTOMER_DATABASE_URL=... \
    python -m app.scripts.migrate_customer_sqlite_to_postgres
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text


TABLES = {
    "air_access_requests": ("request_id", (
        "request_id", "mobile_e164", "device_id", "status", "created_at", "reviewed_at", "reviewer_note",
    )),
    "air_access_decision_history": ("decision_id", (
        "decision_id", "request_id", "mobile_e164", "previous_status", "new_status",
        "reviewer_admin_id", "reviewer_role", "note", "totp_counter", "totp_verified_at",
        "verification_reference", "device_id", "request_context", "decided_at",
    )),
    "air_device_sessions": ("session_id", (
        "session_id", "request_id", "active", "created_at",
    )),
    "air_customer_subscriptions": ("customer_id", (
        "customer_id", "plan_code", "starts_at", "expires_at", "status", "updated_at",
    )),
    "air_customer_lifecycle": ("customer_id", (
        "customer_id", "first_registered_at", "first_approved_at", "first_rejected_at",
        "first_plan_availed_at", "created_at", "updated_at",
    )),
    "air_customer_subscription_history": ("assignment_id", (
        "assignment_id", "customer_id", "plan_code", "starts_at", "expires_at",
        "status", "assigned_by_admin_id", "assigned_at",
    )),
    "air_customer_marketing_preferences": ("customer_id", (
        "customer_id", "promotional_consent", "consent_updated_at", "updated_at",
    )),
    "air_marketing_offers": ("offer_id", (
        "offer_id", "name", "offer_code", "plan_code", "discount_percent", "starts_at",
        "expires_at", "terms", "status", "created_by", "approved_by", "created_at", "approved_at",
    )),
    "air_marketing_audit": ("event_id", (
        "event_id", "actor_customer_id", "action", "target_id", "details", "created_at",
    )),
}
OPTIONAL_TABLES = {
    "air_access_decision_history", "air_customer_lifecycle", "air_customer_subscription_history",
    "air_customer_marketing_preferences", "air_marketing_offers", "air_marketing_audit",
}
BOOL_COLUMNS = {"active", "promotional_consent"}
DATETIME_COLUMNS = {
    "air_access_decision_history": {"totp_verified_at"},
    "air_customer_lifecycle": {
        "first_registered_at", "first_approved_at", "first_rejected_at",
        "first_plan_availed_at", "created_at", "updated_at",
    },
    "air_customer_subscription_history": {"starts_at", "expires_at", "assigned_at"},
}


def _normalize(value, column, table=None):
    if value is None:
        return None
    if column in BOOL_COLUMNS:
        return bool(value)
    if column == "request_context":
        if isinstance(value, str):
            return json.loads(value or "{}")
        return value or {}
    if table in DATETIME_COLUMNS and column in DATETIME_COLUMNS[table]:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return value


def migrate(source_path: str, database_url: str) -> dict[str, int]:
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must point to PostgreSQL")
    path = Path(source_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {path}")

    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    counts: dict[str, int] = {}
    try:
        existing_tables = {row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        missing_required = set(TABLES) - OPTIONAL_TABLES - existing_tables
        if missing_required:
            raise RuntimeError("SQLite source is missing required tables: " + ", ".join(sorted(missing_required)))

        # One target transaction: any conflict or schema error rolls back the entire import.
        with engine.begin() as target:
            for table, (primary_key, configured_columns) in TABLES.items():
                if table not in existing_tables:
                    counts[table] = 0
                    continue
                source_columns = {row["name"] for row in source.execute(f"PRAGMA table_info({table})").fetchall()}
                columns = tuple(column for column in configured_columns if column in source_columns)
                if primary_key not in columns:
                    raise RuntimeError(f"SQLite source table {table} is missing primary key {primary_key}")
                rows = source.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
                counts[table] = len(rows)
                column_sql = ",".join(columns)
                value_sql = ",".join(f":{column}" for column in columns)
                insert = text(
                    f"INSERT INTO {table} ({column_sql}) VALUES ({value_sql}) "
                    f"ON CONFLICT ({primary_key}) DO NOTHING"
                )
                select = text(
                    f"SELECT {column_sql} FROM {table} WHERE {primary_key}=:key"
                )
                for raw in rows:
                    values = {column: _normalize(raw[column], column, table) for column in columns}
                    target.execute(insert, values)
                    stored = target.execute(select, {"key": values[primary_key]}).mappings().one()
                    for column in columns:
                        expected = _normalize(values[column], column, table)
                        actual = _normalize(stored[column], column, table)
                        if expected != actual:
                            raise RuntimeError(
                                f"Data conflict in {table}.{column} for key "
                                f"{values[primary_key]!r}; transaction rolled back"
                            )

            # The Alembic lifecycle backfill runs before a legacy SQLite copy. Rebuild
            # derived lifecycle dates after import and preserve every imported history row.
            # If an older SQLite file has no subscription history table, retain its
            # current subscription as the best available legacy assignment record.
            target.execute(text("""
                INSERT INTO air_customer_subscription_history
                    (assignment_id,customer_id,plan_code,starts_at,expires_at,status,assigned_at)
                SELECT md5(s.customer_id || s.starts_at || s.expires_at),s.customer_id,s.plan_code,
                       s.starts_at::timestamptz,s.expires_at::timestamptz,s.status,s.updated_at::timestamptz
                  FROM air_customer_subscriptions s
                 WHERE NOT EXISTS (
                    SELECT 1 FROM air_customer_subscription_history h WHERE h.customer_id=s.customer_id
                 )
                ON CONFLICT(assignment_id) DO NOTHING
            """))
            target.execute(text("""
                INSERT INTO air_customer_lifecycle(customer_id,first_registered_at)
                SELECT mobile_e164,MIN(created_at::timestamptz)
                  FROM air_access_requests GROUP BY mobile_e164
                ON CONFLICT(customer_id) DO NOTHING
            """))
            target.execute(text("""
                UPDATE air_customer_lifecycle l SET first_approved_at=COALESCE(
                    l.first_approved_at,
                    (SELECT MIN(d.decided_at::timestamptz) FROM air_access_decision_history d
                     WHERE d.mobile_e164=l.customer_id AND d.new_status='APPROVED'),
                    (SELECT MIN(r.reviewed_at::timestamptz) FROM air_access_requests r
                     WHERE r.mobile_e164=l.customer_id AND r.status='APPROVED' AND r.reviewed_at IS NOT NULL)
                )
            """))
            target.execute(text("""
                UPDATE air_customer_lifecycle l SET first_rejected_at=COALESCE(
                    l.first_rejected_at,
                    (SELECT MIN(d.decided_at::timestamptz) FROM air_access_decision_history d
                     WHERE d.mobile_e164=l.customer_id AND d.new_status='REJECTED'),
                    (SELECT MIN(r.reviewed_at::timestamptz) FROM air_access_requests r
                     WHERE r.mobile_e164=l.customer_id AND r.status='REJECTED' AND r.reviewed_at IS NOT NULL)
                )
            """))
            target.execute(text("""
                UPDATE air_customer_lifecycle l SET first_plan_availed_at=COALESCE(
                    l.first_plan_availed_at,
                    (SELECT MIN(h.assigned_at) FROM air_customer_subscription_history h
                     WHERE h.customer_id=l.customer_id)
                )
            """))
        return counts
    finally:
        source.close()
        engine.dispose()


if __name__ == "__main__":
    sqlite_path = os.getenv("AIR_CUSTOMER_SQLITE_PATH", os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3"))
    database_url = os.getenv("AIR_CUSTOMER_DATABASE_URL", "")
    if not database_url and os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE"):
        database_url = Path(os.environ["AIR_CUSTOMER_DATABASE_URL_FILE"]).read_text(encoding="utf-8").strip()
    result = migrate(sqlite_path, database_url)
    for table, count in result.items():
        print(f"{table}: verified {count} source rows")
