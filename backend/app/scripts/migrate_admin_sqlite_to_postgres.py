"""One-way, transactional migration of AIR Admin SQLite rows to PostgreSQL.

Run only after Alembic revision 0001_admin_auth_schema is applied:
  AIR_ADMIN_SQLITE_PATH=... AIR_ADMIN_DATABASE_URL=... python -m app.scripts.migrate_admin_sqlite_to_postgres
The source SQLite file is opened read-only and is never modified.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, text


TABLES = {
    "air_admin_users": ("admin_id", (
        "admin_id", "email", "password_hash", "mfa_secret", "role", "is_active",
        "created_at", "last_totp_counter", "must_change_password", "failed_attempts", "locked_until",
    )),
    "air_admin_sessions": ("session_id", ("session_id", "admin_id", "active", "created_at")),
    "air_admin_login_limits": ("rate_key", ("rate_key", "failures", "window_started", "locked_until")),
    "air_admin_audit": ("event_id", (
        "event_id", "actor_admin_id", "action", "target_admin_id", "details", "created_at",
    )),
}
BOOL_COLUMNS = {"is_active", "must_change_password", "active"}


def _sqlite_value(value):
    if isinstance(value, memoryview):
        return bytes(value)
    return value


def migrate(source_path: str, database_url: str) -> dict[str, int]:
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("AIR_ADMIN_DATABASE_URL must point to PostgreSQL")
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
                    row = {column: _sqlite_value(raw[column]) for column in columns}
                    for column in BOOL_COLUMNS.intersection(columns):
                        row[column] = bool(row[column])
                    insert_columns = []
                    values = []
                    for column in columns:
                        if column == "created_at":
                            insert_columns.append(f"CAST(:{column} AS timestamptz)")
                        else:
                            insert_columns.append(f":{column}")
                        values.append(column)
                    statement = text(
                        f"INSERT INTO {table} ({','.join(columns)}) "
                        f"VALUES ({','.join(insert_columns)}) ON CONFLICT ({pk}) DO NOTHING"
                    )
                    target.execute(statement, row)
                    existing = target.execute(
                        text(f"SELECT {','.join(columns)} FROM {table} WHERE {pk}=:key"),
                        {"key": row[pk]},
                    ).mappings().one()
                    for column in columns:
                        expected, actual = row[column], existing[column]
                        if column in BOOL_COLUMNS:
                            expected, actual = bool(expected), bool(actual)
                        if column == "created_at" and expected is not None:
                            # PostgreSQL normalizes timestamps; compare at second precision.
                            from datetime import datetime
                            expected = datetime.fromisoformat(str(expected).replace("Z", "+00:00")).replace(tzinfo=None)
                            actual = actual.replace(tzinfo=None) if actual.tzinfo else actual
                        if expected != actual:
                            raise RuntimeError(f"Data conflict in {table}.{column} for key {row[pk]!r}; transaction rolled back")
        return counts
    finally:
        source.close()
        engine.dispose()


if __name__ == "__main__":
    sqlite_path = os.getenv("AIR_ADMIN_SQLITE_PATH", "data/air_auth.sqlite3")
    database_url = os.getenv("AIR_ADMIN_DATABASE_URL", "")
    if not database_url and os.getenv("AIR_ADMIN_DATABASE_URL_FILE"):
        database_url = Path(os.environ["AIR_ADMIN_DATABASE_URL_FILE"]).read_text(encoding="utf-8").strip()
    result = migrate(sqlite_path, database_url)
    for table, count in result.items():
        print(f"{table}: verified {count} source rows")
