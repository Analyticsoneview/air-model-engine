"""Idempotent, transactional copy of AIR customer SQLite data into PostgreSQL.

The SQLite source is opened read-only and is never modified or removed.
Apply Alembic migrations first:
  AIR_CUSTOMER_DATABASE_URL=... python -m alembic upgrade head
Then run:
  AIR_CUSTOMER_SQLITE_PATH=... AIR_CUSTOMER_DATABASE_URL=... \
    python -m app.scripts.migrate_customer_sqlite_to_postgres
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, text


TABLES = {
    "air_access_requests": ("request_id", (
        "request_id", "mobile_e164", "device_id", "status", "created_at", "reviewed_at", "reviewer_note",
    )),
    "air_device_sessions": ("session_id", (
        "session_id", "request_id", "active", "created_at",
    )),
    "air_customer_subscriptions": ("customer_id", (
        "customer_id", "plan_code", "starts_at", "expires_at", "status", "updated_at",
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
OPTIONAL_TABLES = {"air_customer_marketing_preferences", "air_marketing_offers", "air_marketing_audit"}
BOOL_COLUMNS = {"active", "promotional_consent"}


def _normalize(value, column):
    if column in BOOL_COLUMNS and value is not None:
        return bool(value)
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
            for table, (primary_key, columns) in TABLES.items():
                if table not in existing_tables:
                    counts[table] = 0
                    continue
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
                    values = {column: _normalize(raw[column], column) for column in columns}
                    target.execute(insert, values)
                    stored = target.execute(select, {"key": values[primary_key]}).mappings().one()
                    for column in columns:
                        expected = _normalize(values[column], column)
                        actual = _normalize(stored[column], column)
                        if expected != actual:
                            raise RuntimeError(
                                f"Data conflict in {table}.{column} for key "
                                f"{values[primary_key]!r}; transaction rolled back"
                            )
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
