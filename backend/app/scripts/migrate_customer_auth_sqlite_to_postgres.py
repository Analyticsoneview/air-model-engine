"""Fail-closed, one-time SQLite import for customer identities, access requests and device sessions.

Run after Alembic upgrade. The source database is opened read-only and is never modified.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

TABLES = {
    "customers": ("customer_id", ("customer_id", "email", "password_hash", "is_active", "created_at")),
    "air_access_requests": ("request_id", ("request_id", "mobile_e164", "device_id", "status", "created_at", "reviewed_at", "reviewer_note")),
    "air_device_sessions": ("session_id", ("session_id", "request_id", "active", "created_at")),
    "air_customer_subscriptions": ("customer_id", (
        "customer_id", "plan_code", "starts_at", "expires_at", "status", "updated_at",
    )),
}
BOOL_COLUMNS = {"is_active", "active"}
TIMESTAMP_COLUMNS = {"created_at", "reviewed_at"}


def _timestamp(value):
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def migrate(source_path: str, database_url: str) -> dict[str, Any]:
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must point to PostgreSQL")
    path = Path(source_path).expanduser().resolve()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as connection:
            marker = connection.execute(
                text("SELECT imported_at FROM air_domain_store_imports WHERE import_name=:name"),
                {"name": "sqlite_customer_auth_v1"},
            ).mappings().first()
            if marker:
                return {"status": "ALREADY_IMPORTED", "imported_at": marker["imported_at"]}

        if not path.is_file():
            return {"status": "NO_SOURCE_FILE", "source": str(path)}

        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        counts: dict[str, int] = {}
        try:
            source_rows = {}
            for table, (_pk, columns) in TABLES.items():
                exists = source.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                rows = [] if exists is None else source.execute(
                    f"SELECT {','.join(columns)} FROM {table}"
                ).fetchall()
                source_rows[table] = rows
                counts[table] = len(rows)
        finally:
            source.close()

        with engine.begin() as target:
            marker = target.execute(
                text("SELECT imported_at FROM air_domain_store_imports WHERE import_name=:name"),
                {"name": "sqlite_customer_auth_v1"},
            ).mappings().first()
            if marker:
                return {"status": "ALREADY_IMPORTED", "imported_at": marker["imported_at"]}

            for table, (pk, columns) in TABLES.items():
                for raw in source_rows[table]:
                    row = {column: raw[column] for column in columns}
                    for column in BOOL_COLUMNS.intersection(columns):
                        row[column] = bool(row[column])
                    for column in TIMESTAMP_COLUMNS.intersection(columns):
                        row[column] = _timestamp(row[column])
                    values = [
                        f"CAST(:{column} AS timestamptz)" if column in TIMESTAMP_COLUMNS else f":{column}"
                        for column in columns
                    ]
                    target.execute(
                        text(
                            f"INSERT INTO {table} ({','.join(columns)}) "
                            f"VALUES ({','.join(values)}) ON CONFLICT ({pk}) DO NOTHING"
                        ),
                        row,
                    )
                    existing = target.execute(
                        text(f"SELECT {','.join(columns)} FROM {table} WHERE {pk}=:key"),
                        {"key": row[pk]},
                    ).mappings().one()
                    for column in columns:
                        expected, actual = row[column], existing[column]
                        if column in BOOL_COLUMNS:
                            expected, actual = bool(expected), bool(actual)
                        elif column in TIMESTAMP_COLUMNS and expected is not None:
                            expected = expected.astimezone(timezone.utc)
                            actual = actual.replace(tzinfo=timezone.utc) if actual.tzinfo is None else actual.astimezone(timezone.utc)
                        if expected != actual:
                            raise RuntimeError(
                                f"Data conflict in {table}.{column} for key {row[pk]!r}; transaction rolled back"
                            )

                # Reconcile the imported source keys, not the whole shared target table.
                # Other legitimate customers may already exist in PostgreSQL.
                reconciled_count = target.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE {pk} = ANY(:keys)"),
                    {"keys": [row[pk] for row in source_rows[table]]},
                ).scalar_one() if source_rows[table] else 0
                if reconciled_count != counts[table]:
                    raise RuntimeError(
                        f"Row-count conflict in {table}: SQLite={counts[table]}, reconciled PostgreSQL={reconciled_count}; transaction rolled back"
                    )

            manifest = json.dumps({"source": str(path), "rows": counts}, sort_keys=True)
            target.execute(
                text("INSERT INTO air_domain_store_imports(import_name,source_manifest,imported_at) "
                     "VALUES(:name,:manifest,CURRENT_TIMESTAMP::text)"),
                {"name": "sqlite_customer_auth_v1", "manifest": manifest},
            )
        return {"status": "IMPORTED_AND_RECONCILED", **counts}
    finally:
        engine.dispose()


if __name__ == "__main__":
    source_path = os.getenv("AIR_CUSTOMER_SQLITE_PATH", "data/air_auth.sqlite3")
    secret_file = os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE")
    database_url = Path(secret_file).read_text(encoding="utf-8").strip() if secret_file else os.getenv("AIR_CUSTOMER_DATABASE_URL", "")
    result = migrate(source_path, database_url)
    print(f"customer auth import: {result.get('status', 'UNKNOWN')}")
    for table, count in result.items():
        if table in TABLES:
            print(f"{table}: reconciled {count} source rows")
