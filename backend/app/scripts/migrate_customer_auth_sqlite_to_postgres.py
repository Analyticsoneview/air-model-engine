"""Read-only SQLite import with transactional conflict detection and row reconciliation.

Run after Alembic upgrade on the customer PostgreSQL database:
  AIR_CUSTOMER_SQLITE_PATH=data/air_auth.sqlite3 python -m app.scripts.migrate_customer_auth_sqlite_to_postgres
The source database is opened read-only and is never modified or deleted.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

TABLES = {
    "customers": ("customer_id", ("customer_id", "email", "password_hash", "is_active", "created_at")),
    "air_access_requests": ("request_id", ("request_id", "mobile_e164", "device_id", "status", "created_at", "reviewed_at", "reviewer_note")),
    "air_device_sessions": ("session_id", ("session_id", "request_id", "active", "created_at")),
}
BOOL_COLUMNS = {"is_active", "active"}
TIMESTAMP_COLUMNS = {"created_at", "reviewed_at"}


def _timestamp(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


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
        with engine.begin() as target:
            for table, (pk, columns) in TABLES.items():
                source_rows = source.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
                counts[table] = len(source_rows)
                for raw in source_rows:
                    row = {column: raw[column] for column in columns}
                    for column in BOOL_COLUMNS.intersection(columns):
                        row[column] = bool(row[column])
                    for column in TIMESTAMP_COLUMNS.intersection(columns):
                        row[column] = _timestamp(row[column])
                    values = [f"CAST(:{c} AS timestamptz)" if c in TIMESTAMP_COLUMNS else f":{c}" for c in columns]
                    target.execute(text(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(values)}) ON CONFLICT ({pk}) DO NOTHING"), row)
                    existing = target.execute(text(f"SELECT {','.join(columns)} FROM {table} WHERE {pk}=:key"), {"key": row[pk]}).mappings().one()
                    for column in columns:
                        expected, actual = row[column], existing[column]
                        if column in BOOL_COLUMNS:
                            expected, actual = bool(expected), bool(actual)
                        elif column in TIMESTAMP_COLUMNS and expected is not None:
                            expected = expected.replace(tzinfo=None)
                            actual = actual.replace(tzinfo=None) if actual.tzinfo else actual
                        if expected != actual:
                            raise RuntimeError(f"Data conflict in {table}.{column} for key {row[pk]!r}; transaction rolled back")
                target_count = target.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                if target_count != counts[table]:
                    raise RuntimeError(
                        f"Row-count conflict in {table}: SQLite={counts[table]}, PostgreSQL={target_count}; transaction rolled back"
                    )
        return counts
    finally:
        source.close()
        engine.dispose()


if __name__ == "__main__":
    source_path = os.getenv("AIR_CUSTOMER_SQLITE_PATH", "data/air_auth.sqlite3")
    secret_file = os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE")
    database_url = Path(secret_file).read_text(encoding="utf-8").strip() if secret_file else os.getenv("AIR_CUSTOMER_DATABASE_URL", "")
    result = migrate(source_path, database_url)
    for table, count in result.items():
        print(f"{table}: reconciled {count} source rows")
