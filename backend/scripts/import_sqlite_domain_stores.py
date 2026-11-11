"""One-time, fail-closed import of core SQLite domain stores into PostgreSQL.

The source SQLite files are never modified or deleted. Target tables must be empty;
the script copies encrypted credential bytes unchanged and verifies they decrypt
with the configured AIR Fernet key before and after the import.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from cryptography.fernet import Fernet
from psycopg.rows import dict_row


TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "broker_credentials": (
        "air_credentials.sqlite3",
        ("customer_id", "broker", "account_id", "encrypted_payload", "updated_at"),
    ),
    "customer_trading_accounts": (
        "customer_accounts.sqlite3",
        ("customer_id", "broker", "account_id", "enabled_for_orders", "created_at"),
    ),
    "customer_market_data_access": (
        "customer_accounts.sqlite3",
        ("customer_id", "tier", "broker_data_enabled", "updated_at"),
    ),
    "customer_market_data_selection": (
        "customer_accounts.sqlite3",
        ("customer_id", "provider", "account_id", "updated_at"),
    ),
    "execution_policy": (
        "air_execution_policy.sqlite3",
        ("id", "master_auto_enabled", "strategy_json", "updated_at"),
    ),
    "order_ledger": (
        "air_orders.sqlite3",
        ("broker", "account_id", "idempotency_key", "broker_order_id", "status", "raw_json", "created_at", "updated_at"),
    ),
    "order_ledger_events": (
        "air_orders.sqlite3",
        ("event_id", "broker", "account_id", "idempotency_key", "status", "broker_order_id", "raw_json", "event_at"),
    ),
}
BOOLEAN_COLUMNS = {"enabled_for_orders", "broker_data_enabled", "master_auto_enabled"}


def _read_secret(name: str) -> str:
    secret_file = os.getenv(name + "_FILE")
    value = Path(secret_file).read_text(encoding="utf-8").strip() if secret_file else os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} or {name}_FILE must be configured")
    return value


def _sqlite_rows(path: Path, table: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    # Enforce read-only access at the SQLite URI layer; this is stronger
    # than relying on the importer to issue SELECT statements only.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists is None:
            return []
        return [dict(row) for row in connection.execute(
            f"SELECT {','.join(columns)} FROM {table}"
        ).fetchall()]
    finally:
        connection.close()


def _normalize_value(column: str, value: Any) -> Any:
    if column in BOOLEAN_COLUMNS:
        return bool(value)
    if column == "encrypted_payload" and value is not None:
        return bytes(value)
    return value


def _manifest_value(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes_hex__": bytes(value).hex()}
    return value


def _source_digest(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> str:
    """Hash the imported column values, independent of SQLite row ordering."""
    canonical_rows = [
        [_manifest_value(_normalize_value(column, row[column])) for column in columns]
        for row in rows
    ]
    canonical_rows.sort(
        key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    payload = json.dumps(
        canonical_rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _credential_cipher() -> Fernet | None:
    key_file = os.getenv("AIR_CREDENTIAL_KEY_FILE")
    key = Path(key_file).read_bytes().strip() if key_file else os.getenv("AIR_CREDENTIAL_KEY", "").encode()
    return Fernet(key) if key else None


def _source_path(source_data_dir: Path, table: str, filename: str) -> Path:
    env_name = {
        "broker_credentials": "AIR_CREDENTIAL_DB_PATH",
        "customer_trading_accounts": "AIR_ACCOUNT_DB_PATH",
        "customer_market_data_access": "AIR_ACCOUNT_DB_PATH",
        "customer_market_data_selection": "AIR_ACCOUNT_DB_PATH",
        "execution_policy": "AIR_EXECUTION_POLICY_DB_PATH",
        "order_ledger": "AIR_ORDER_DB_PATH",
        "order_ledger_events": "AIR_ORDER_DB_PATH",
    }[table]
    configured = os.getenv(env_name, "").strip()
    return Path(configured) if configured else source_data_dir / filename


def run(source_data_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    target_url = _read_secret("AIR_DATABASE_URL")
    driver_url = target_url.replace("postgresql+psycopg://", "postgresql://", 1)
    source_rows: dict[str, list[dict[str, Any]]] = {}
    source_paths: dict[str, Path] = {}
    report: dict[str, Any] = {"dry_run": dry_run, "tables": {}}
    cipher = _credential_cipher()

    for table, (filename, columns) in TABLES.items():
        source_path = _source_path(source_data_dir, table, filename)
        source_paths[table] = source_path
        rows = _sqlite_rows(source_path, table, columns)
        source_rows[table] = rows
        report["tables"][table] = {
            "source_path": str(source_path),
            "source_rows": len(rows),
            "target_rows_before": None,
            "target_rows_after": None,
        }
        if table == "broker_credentials" and rows:
            if cipher is None:
                raise RuntimeError("AIR_CREDENTIAL_KEY or AIR_CREDENTIAL_KEY_FILE is required to verify stored credentials")
            for row in rows:
                cipher.decrypt(bytes(row["encrypted_payload"]))

    missing_source_files = sorted({str(path) for path in source_paths.values() if not path.is_file()})
    if missing_source_files:
        raise FileNotFoundError(
            "Required SQLite source database(s) missing; refusing a partial domain-store import: "
            + ", ".join(missing_source_files)
        )

    manifest_data = {
        table: {
            "source_path": str(source_paths[table]),
            "source_rows": len(source_rows[table]),
            "source_sha256": _source_digest(source_rows[table], TABLES[table][1]),
        }
        for table in TABLES
    }
    manifest = json.dumps(manifest_data, sort_keys=True)

    with psycopg.connect(driver_url, row_factory=dict_row) as connection:
        marker = connection.execute(
            "SELECT source_manifest, imported_at FROM air_domain_store_imports "
            "WHERE import_name=%s",
            ("sqlite_domain_stores_v1",),
        ).fetchone()

        if marker:
            if marker["source_manifest"] != manifest:
                raise RuntimeError(
                    "SQLite source files changed after the recorded PostgreSQL import. "
                    "Stop writes and perform a reviewed reconciliation; refusing to continue."
                )
            report["status"] = "ALREADY_IMPORTED"
            report["imported_at"] = marker["imported_at"]
            return report

        for table in TABLES:
            target_count = connection.execute(
                f"SELECT count(*) AS count FROM {table}"
            ).fetchone()["count"]
            report["tables"][table]["target_rows_before"] = target_count
            if target_count:
                raise RuntimeError(
                    f"Refusing to import into non-empty PostgreSQL table {table} ({target_count} rows)"
                )

        if not dry_run:
            for table, (_filename, columns) in TABLES.items():
                for row in source_rows[table]:
                    placeholders = ",".join(["%s"] * len(columns))
                    column_sql = ",".join(columns)
                    statement = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})"
                    values = tuple(_normalize_value(column, row[column]) for column in columns)
                    connection.execute(statement, values)

            if source_rows["order_ledger_events"]:
                connection.execute(
                    "SELECT setval(pg_get_serial_sequence('order_ledger_events','event_id'), "
                    "COALESCE((SELECT MAX(event_id) FROM order_ledger_events), 1), true)"
                )

        for table, (_filename, columns) in TABLES.items():
            target_rows = connection.execute(
                f"SELECT {','.join(columns)} FROM {table}"
            ).fetchall()
            report["tables"][table]["target_rows_after"] = (
                len(target_rows) if not dry_run else None
            )
            if not dry_run:
                source_fingerprints = Counter(
                    tuple(_normalize_value(column, row[column]) for column in columns)
                    for row in source_rows[table]
                )
                target_fingerprints = Counter(
                    tuple(_normalize_value(column, row[column]) for column in columns)
                    for row in target_rows
                )
                if source_fingerprints != target_fingerprints:
                    raise RuntimeError(
                        f"Field-level reconciliation failed for {table}; transaction rolled back"
                    )

        if not dry_run:
            if cipher is not None:
                for row in connection.execute(
                    "SELECT encrypted_payload FROM broker_credentials"
                ).fetchall():
                    cipher.decrypt(bytes(row["encrypted_payload"]))
            connection.execute(
                "INSERT INTO air_domain_store_imports(import_name,source_manifest,imported_at) "
                "VALUES(%s,%s,CURRENT_TIMESTAMP::text)",
                ("sqlite_domain_stores_v1", manifest),
            )

    report["status"] = "DRY_RUN_VALIDATED" if dry_run else "IMPORTED_AND_RECONCILED"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-data-dir", type=Path, default=Path("data"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.source_data_dir, args.dry_run), indent=2, default=str))


if __name__ == "__main__":
    main()
