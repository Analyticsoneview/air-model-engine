"""Fail-closed, one-time migration of AIR Admin SQLite rows to PostgreSQL.

The SQLite source is opened read-only and is never modified or deleted. Existing
password hashes and encrypted MFA secrets are copied byte-for-byte.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
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
DATETIME_COLUMNS = {"created_at"}


def _secret(name: str) -> str:
    file_name = os.getenv(name + "_FILE")
    value = Path(file_name).read_text(encoding="utf-8").strip() if file_name else os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} or {name}_FILE must be configured")
    return value


def _normalise(column: str, value: Any) -> Any:
    if column in BOOL_COLUMNS:
        return bool(value)
    if column in DATETIME_COLUMNS and value is not None:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    if column == "mfa_secret" and value is not None:
        return bytes(value)
    return value


def migrate(source_path: str, database_url: str) -> dict[str, Any]:
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("AIR_ADMIN_DATABASE_URL must point to PostgreSQL")
    path = Path(source_path).expanduser().resolve()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as target:
            marker = target.execute(
                text("SELECT imported_at FROM air_domain_store_imports WHERE import_name=:name"),
                {"name": "sqlite_admin_auth_v1"},
            ).mappings().first()
            if marker:
                return {"status": "ALREADY_IMPORTED", "imported_at": marker["imported_at"]}

        if not path.is_file():
            return {"status": "NO_SOURCE_FILE", "source": str(path)}

        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        try:
            source_rows = {}
            counts = {}
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

        key = _secret("AIR_ADMIN_MFA_KEY")
        cipher = Fernet(key.encode())
        for row in source_rows["air_admin_users"]:
            cipher.decrypt(bytes(row["mfa_secret"]))

        with engine.begin() as target:
            marker = target.execute(
                text("SELECT imported_at FROM air_domain_store_imports WHERE import_name=:name"),
                {"name": "sqlite_admin_auth_v1"},
            ).mappings().first()
            if marker:
                return {"status": "ALREADY_IMPORTED", "imported_at": marker["imported_at"]}

            for table, (pk, columns) in TABLES.items():
                for raw in source_rows[table]:
                    row = {column: _normalise(column, raw[column]) for column in columns}
                    values = [
                        f"CAST(:{column} AS timestamptz)" if column in DATETIME_COLUMNS else f":{column}"
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
                        expected = _normalise(column, row[column])
                        actual = _normalise(column, existing[column])
                        if expected != actual:
                            raise RuntimeError(
                                f"Data conflict in {table}.{column} for key {row[pk]!r}; transaction rolled back"
                            )

                target_count = target.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                if target_count != counts[table]:
                    raise RuntimeError(
                        f"Row-count conflict in {table}: SQLite={counts[table]}, PostgreSQL={target_count}; transaction rolled back"
                    )

            for row in target.execute(text("SELECT mfa_secret FROM air_admin_users")).mappings():
                cipher.decrypt(bytes(row["mfa_secret"]))

            manifest = json.dumps({"source": str(path), "rows": counts}, sort_keys=True)
            target.execute(
                text("INSERT INTO air_domain_store_imports(import_name,source_manifest,imported_at) "
                     "VALUES(:name,:manifest,CURRENT_TIMESTAMP::text)"),
                {"name": "sqlite_admin_auth_v1", "manifest": manifest},
            )
        return {"status": "IMPORTED_AND_RECONCILED", **counts}
    finally:
        engine.dispose()


if __name__ == "__main__":
    sqlite_path = os.getenv("AIR_ADMIN_SQLITE_PATH", os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3"))
    database_url = _secret("AIR_ADMIN_DATABASE_URL")
    result = migrate(sqlite_path, database_url)
    print(f"admin auth import: {result.get('status', 'UNKNOWN')}")
    for table, count in result.items():
        if table in TABLES:
            print(f"{table}: reconciled {count} source rows")
