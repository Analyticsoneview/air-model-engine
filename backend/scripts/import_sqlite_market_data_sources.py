"""Incremental import of market-data source selections and failover settings."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


SOURCE_COLUMNS = (
    "channel", "provider", "account_id", "enabled", "fallback_provider",
    "fallback_account_id", "failover_enabled", "updated_at",
)
FAILOVER_COLUMNS = ("channel", "enabled", "candidates_json", "updated_at")


def _rows(path: Path, table: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists is None:
            return []
        available = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        selected = [column for column in columns if column in available]
        defaults = {
            "enabled": False, "failover_enabled": False,
            "candidates_json": "[]",
        }
        return [
            {column: dict(row).get(column, defaults.get(column)) for column in columns}
            for row in db.execute(f"SELECT {','.join(selected)} FROM {table}").fetchall()
        ]
    finally:
        db.close()


def run(source_data_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    target_url = os.getenv("AIR_DATABASE_URL", "").strip()
    if not target_url:
        raise RuntimeError("AIR_DATABASE_URL must point to the migrated PostgreSQL database")
    configured = os.getenv("AIR_MARKET_SOURCE_DB_PATH", "").strip()
    source_path = Path(configured) if configured else source_data_dir / "air_market_sources.sqlite3"
    if not source_path.is_file():
        return {"status": "NO_SOURCE_FILE", "source_path": str(source_path)}
    sources = _rows(source_path, "market_data_sources", SOURCE_COLUMNS)
    failover = _rows(source_path, "market_data_failover", FAILOVER_COLUMNS)
    manifest = json.dumps({
        "source_path": str(source_path.resolve()),
        "market_data_sources": len(sources),
        "market_data_failover": len(failover),
    }, sort_keys=True)
    driver_url = target_url.replace("postgresql+psycopg://", "postgresql://", 1)
    report = {"source_path": str(source_path), "source_rows": {
        "market_data_sources": len(sources), "market_data_failover": len(failover),
    }, "dry_run": dry_run}

    with psycopg.connect(driver_url, row_factory=dict_row) as connection:
        marker = connection.execute(
            "SELECT source_manifest, imported_at FROM air_domain_store_imports "
            "WHERE import_name=%s", ("sqlite_market_data_sources_v1",)
        ).fetchone()
        if marker:
            if marker["source_manifest"] != manifest:
                raise RuntimeError("Market-data source SQLite file changed after import; refusing overwrite")
            report.update({"status": "ALREADY_IMPORTED", "imported_at": marker["imported_at"]})
            return report

        before = {}
        for table in ("market_data_sources", "market_data_failover"):
            count = connection.execute(f"SELECT count(*) AS count FROM {table}").fetchone()["count"]
            before[table] = count
            if count:
                raise RuntimeError(f"Refusing to import into non-empty {table} ({count} rows)")
        report["target_rows_before"] = before

        if not dry_run:
            for table, columns, rows in (
                ("market_data_sources", SOURCE_COLUMNS, sources),
                ("market_data_failover", FAILOVER_COLUMNS, failover),
            ):
                for row in rows:
                    values = [row[column] for column in columns]
                    for key in ("enabled", "failover_enabled"):
                        if key in columns:
                            index = columns.index(key)
                            values[index] = bool(values[index])
                    placeholders = ",".join(["%s"] * len(columns))
                    connection.execute(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                        tuple(values),
                    )

            for table, columns, rows in (
                ("market_data_sources", SOURCE_COLUMNS, sources),
                ("market_data_failover", FAILOVER_COLUMNS, failover),
            ):
                actual = connection.execute(
                    f"SELECT {','.join(columns)} FROM {table} ORDER BY channel"
                ).fetchall()
                expected = sorted(
                    [tuple(bool(row[col]) if col in {"enabled", "failover_enabled"} else row[col]
                           for col in columns) for row in rows],
                    key=lambda row: row[0],
                )
                got = sorted(
                    [tuple(bool(row[col]) if col in {"enabled", "failover_enabled"} else row[col]
                           for col in columns) for row in actual],
                    key=lambda row: row[0],
                )
                if got != expected:
                    raise RuntimeError(f"Field-level reconciliation failed for {table}")

            connection.execute(
                "INSERT INTO air_domain_store_imports(import_name,source_manifest,imported_at) "
                "VALUES(%s,%s,CURRENT_TIMESTAMP::text)",
                ("sqlite_market_data_sources_v1", manifest),
            )
            report["target_rows_after"] = {
                "market_data_sources": len(sources), "market_data_failover": len(failover),
            }

    report["status"] = "DRY_RUN_VALIDATED" if dry_run else "IMPORTED_AND_RECONCILED"
    return report
