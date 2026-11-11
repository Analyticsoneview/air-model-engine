"""Fail-closed import of existing SQLite AIR administrator records to PostgreSQL."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from cryptography.fernet import Fernet
from psycopg.rows import dict_row


TABLES: dict[str, tuple[str, ...]] = {
    "air_admin_users": (
        "admin_id", "email", "password_hash", "mfa_secret", "role", "is_active",
        "created_at", "last_totp_counter", "must_change_password", "failed_attempts", "locked_until",
    ),
    "air_admin_sessions": ("session_id", "admin_id", "active", "created_at"),
    "air_admin_login_limits": ("rate_key", "failures", "window_started", "locked_until"),
    "air_admin_audit": ("event_id", "actor_admin_id", "action", "target_admin_id", "details", "created_at"),
}
BOOLEAN_COLUMNS = {"is_active", "must_change_password", "active"}
DATETIME_COLUMNS = {"created_at"}


def _secret(name: str) -> str:
    file_name = os.getenv(name + "_FILE")
    value = Path(file_name).read_text(encoding="utf-8").strip() if file_name else os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} or {name}_FILE must be configured")
    return value


def _datetime(value: Any) -> Any:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _normalise(column: str, value: Any) -> Any:
    if column in BOOLEAN_COLUMNS:
        return bool(value)
    if column in DATETIME_COLUMNS:
        return _datetime(value)
    if column == "mfa_secret" and value is not None:
        return bytes(value)
    return value


def run(source_db_path: Path, dry_run: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {"dry_run": dry_run, "source": str(source_db_path), "tables": {}}
    target_url = _secret("AIR_DATABASE_URL").replace("postgresql+psycopg://", "postgresql://", 1)

    with psycopg.connect(target_url, row_factory=dict_row) as connection:
        marker = connection.execute(
            "SELECT imported_at FROM air_domain_store_imports WHERE import_name=%s",
            ("sqlite_admin_auth_v1",),
        ).fetchone()
        if marker:
            report["status"] = "ALREADY_IMPORTED"
            report["imported_at"] = marker["imported_at"]
            return report

    if not source_db_path.exists():
        report["status"] = "NO_SOURCE_FILE"
        return report

    source = sqlite3.connect(source_db_path)
    source.row_factory = sqlite3.Row
    try:
        source_rows: dict[str, list[dict[str, Any]]] = {}
        for table, columns in TABLES.items():
            exists = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            rows = [] if exists is None else [
                dict(row) for row in source.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
            ]
            source_rows[table] = rows
            report["tables"][table] = {"source_rows": len(rows), "target_rows_before": None, "target_rows_after": None}
    finally:
        source.close()

    key = _secret("AIR_ADMIN_MFA_KEY")
    cipher = Fernet(key.encode())
    for row in source_rows["air_admin_users"]:
        cipher.decrypt(bytes(row["mfa_secret"]))

    with psycopg.connect(target_url, row_factory=dict_row) as connection:
        marker = connection.execute(
            "SELECT imported_at FROM air_domain_store_imports WHERE import_name=%s",
            ("sqlite_admin_auth_v1",),
        ).fetchone()
        if marker:
            report["status"] = "ALREADY_IMPORTED"
            report["imported_at"] = marker["imported_at"]
            return report

        for table in TABLES:
            count = connection.execute(f"SELECT count(*) AS count FROM {table}").fetchone()["count"]
            report["tables"][table]["target_rows_before"] = count
            if count:
                raise RuntimeError(f"Refusing to import into non-empty PostgreSQL table {table} ({count} rows)")

        if not dry_run:
            # Preserve FK ordering: users before sessions. The remaining tables are independent.
            for table, columns in TABLES.items():
                rows = source_rows[table]
                if not rows:
                    continue
                placeholders = ",".join(["%s"] * len(columns))
                statement = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
                for row in rows:
                    values = tuple(_normalise(column, row[column]) for column in columns)
                    connection.execute(statement, values)

        for table, columns in TABLES.items():
            count = connection.execute(f"SELECT count(*) AS count FROM {table}").fetchone()["count"]
            report["tables"][table]["target_rows_after"] = None if dry_run else count
            if not dry_run:
                target_rows = connection.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
                source_fingerprints = Counter(
                    tuple(_normalise(column, row[column]) for column in columns)
                    for row in source_rows[table]
                )
                target_fingerprints = Counter(
                    tuple(_normalise(column, row[column]) for column in columns)
                    for row in target_rows
                )
                if count != len(source_rows[table]) or source_fingerprints != target_fingerprints:
                    raise RuntimeError(f"Field-level reconciliation failed for {table}")

        if not dry_run:
            for row in connection.execute("SELECT mfa_secret FROM air_admin_users").fetchall():
                cipher.decrypt(bytes(row["mfa_secret"]))
            manifest = json.dumps(
                {table: len(source_rows[table]) for table in TABLES},
                sort_keys=True,
            )
            connection.execute(
                "INSERT INTO air_domain_store_imports(import_name,source_manifest,imported_at) "
                "VALUES(%s,%s,CURRENT_TIMESTAMP::text)",
                ("sqlite_admin_auth_v1", manifest),
            )

    report["status"] = "DRY_RUN_VALIDATED" if dry_run else "IMPORTED_AND_RECONCILED"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-db",
        type=Path,
        default=Path(os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3")),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.source_db, args.dry_run), indent=2, default=str))


if __name__ == "__main__":
    main()
