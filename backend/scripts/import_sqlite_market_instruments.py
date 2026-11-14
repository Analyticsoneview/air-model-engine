"""Incremental, reconciled import of the broker instrument-master SQLite stores."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


INSTRUMENT_COLUMNS = (
    "provider", "account_id", "exchange", "symbol", "underlying_symbol", "token",
    "segment", "expiry", "strike", "option_type", "lot_size", "instrument_type",
    "tick_size", "updated_at",
)
REFRESH_COLUMNS = ("provider", "account_id", "row_count", "source", "refreshed_at")


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
        return [
            {column: dict(row).get(column) for column in columns}
            for row in db.execute(f"SELECT {','.join(selected)} FROM {table}").fetchall()
        ]
    finally:
        db.close()


def run(source_data_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    target_url = os.getenv("AIR_DATABASE_URL", "").strip()
    if not target_url:
        raise RuntimeError("AIR_DATABASE_URL must point to the migrated PostgreSQL database")
    configured = os.getenv("AIR_MARKET_INSTRUMENT_DB_PATH", "").strip()
    source_path = Path(configured) if configured else source_data_dir / "air_market_instruments.sqlite3"
    if not source_path.is_file():
        return {"status": "NO_SOURCE_FILE", "source_path": str(source_path)}

    instruments = _rows(source_path, "market_instruments", INSTRUMENT_COLUMNS)
    refreshes = _rows(source_path, "market_master_refresh", REFRESH_COLUMNS)
    manifest = json.dumps({
        "source_path": str(source_path.resolve()),
        "market_instruments": len(instruments),
        "market_master_refresh": len(refreshes),
    }, sort_keys=True)
    driver_url = target_url.replace("postgresql+psycopg://", "postgresql://", 1)
    report = {
        "source_path": str(source_path),
        "market_instruments_source_rows": len(instruments),
        "market_master_refresh_source_rows": len(refreshes),
        "dry_run": dry_run,
    }

    with psycopg.connect(driver_url, row_factory=dict_row) as connection:
        marker = connection.execute(
            "SELECT source_manifest, imported_at FROM air_domain_store_imports "
            "WHERE import_name=%s", ("sqlite_market_instruments_v1",)
        ).fetchone()
        if marker:
            if marker["source_manifest"] != manifest:
                raise RuntimeError("Instrument master SQLite source changed after import; refusing overwrite")
            report.update({"status": "ALREADY_IMPORTED", "imported_at": marker["imported_at"]})
            return report

        counts = {}
        for table in ("market_instruments", "market_master_refresh"):
            count = connection.execute(f"SELECT count(*) AS count FROM {table}").fetchone()["count"]
            counts[table] = count
            if count:
                raise RuntimeError(f"Refusing to import into non-empty {table} ({count} rows)")
        report["target_rows_before"] = counts

        if not dry_run:
            for table, columns, rows in (
                ("market_instruments", INSTRUMENT_COLUMNS, instruments),
                ("market_master_refresh", REFRESH_COLUMNS, refreshes),
            ):
                if not rows:
                    continue
                placeholders = ",".join(["%s"] * len(columns))
                statement = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
                for row in rows:
                    connection.execute(statement, tuple(row[column] for column in columns))

            for table, columns, rows in (
                ("market_instruments", INSTRUMENT_COLUMNS, instruments),
                ("market_master_refresh", REFRESH_COLUMNS, refreshes),
            ):
                target = connection.execute(
                    f"SELECT {','.join(columns)} FROM {table} ORDER BY 1,2"
                ).fetchall()
                expected = sorted(
                    [tuple(row[column] for column in columns) for row in rows],
                    key=lambda value: (str(value[0]), str(value[1]), str(value[5] if table == "market_instruments" else "")),
                )
                actual = sorted(
                    [tuple(row[column] for column in columns) for row in target],
                    key=lambda value: (str(value[0]), str(value[1]), str(value[5] if table == "market_instruments" else "")),
                )
                if actual != expected:
                    raise RuntimeError(f"Field-level reconciliation failed for {table}")

            connection.execute(
                "INSERT INTO air_domain_store_imports(import_name,source_manifest,imported_at) "
                "VALUES(%s,%s,CURRENT_TIMESTAMP::text)",
                ("sqlite_market_instruments_v1", manifest),
            )
            report["target_rows_after"] = {
                "market_instruments": len(instruments),
                "market_master_refresh": len(refreshes),
            }

    report["status"] = "DRY_RUN_VALIDATED" if dry_run else "IMPORTED_AND_RECONCILED"
    return report
