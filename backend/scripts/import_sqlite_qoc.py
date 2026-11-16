"""Incremental, reconciled import of the legacy SQLite AIR QOC store."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


COLUMNS = (
    "id", "provider", "account_id", "underlying_scrip", "underlying_segment", "expiry",
    "underlying_price", "strike", "option_type", "security_id", "last_price", "previous_close",
    "volume", "previous_volume", "open_interest", "previous_oi", "bid_price", "bid_quantity",
    "ask_price", "ask_quantity", "implied_volatility", "observed_at",
)


def run(source_data_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    target_url = os.getenv("AIR_DATABASE_URL", "").strip()
    if not target_url:
        raise RuntimeError("AIR_DATABASE_URL must point to the migrated PostgreSQL database")
    source_value = os.getenv("AIR_QOC_DB_PATH", "").strip()
    source_path = Path(source_value) if source_value else source_data_dir / "air_qoc.sqlite3"
    if not source_path.is_file():
        return {"status": "NO_SOURCE_FILE", "source_path": str(source_path)}

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        exists = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='option_observations'"
        ).fetchone()
        if exists is None:
            rows = []
        else:
            available = {row["name"] for row in source.execute("PRAGMA table_info(option_observations)")}
            selected = [column for column in COLUMNS if column in available]
            rows = []
            for raw in source.execute(
                f"SELECT {','.join(selected)} FROM option_observations ORDER BY id"
            ).fetchall():
                item = dict(raw)
                rows.append({column: (str(item.get(column)) if column == "underlying_scrip" and item.get(column) is not None else item.get(column)) for column in COLUMNS})
    finally:
        source.close()

    manifest = json.dumps({
        "source_path": str(source_path.resolve()),
        "source_rows": len(rows),
    }, sort_keys=True)
    driver_url = target_url.replace("postgresql+psycopg://", "postgresql://", 1)
    report = {"source_path": str(source_path), "source_rows": len(rows), "dry_run": dry_run}

    with psycopg.connect(driver_url, row_factory=dict_row) as connection:
        # Migration/import jobs run with explicit administrative RLS context;
        # every imported row is still assigned to a verified customer tenant.
        connection.execute("SELECT set_config('air.is_admin','true',true)")
        marker = connection.execute(
            "SELECT source_manifest, imported_at FROM air_domain_store_imports "
            "WHERE import_name=%s", ("sqlite_qoc_observations_v1",)
        ).fetchone()
        if marker:
            if marker["source_manifest"] != manifest:
                raise RuntimeError("QOC SQLite source changed after import; refusing automatic overwrite")
            report.update({"status": "ALREADY_IMPORTED", "imported_at": marker["imported_at"]})
            return report

        target_count = connection.execute(
            "SELECT count(*) AS count FROM option_observations"
        ).fetchone()["count"]
        report["target_rows_before"] = target_count
        if target_count:
            raise RuntimeError(
                f"Refusing to import into non-empty option_observations ({target_count} rows)"
            )

        if not dry_run:
            import_columns = COLUMNS + ("customer_id", "tenant_id")
            placeholders = ",".join(["%s"] * len(import_columns))
            column_sql = ",".join(COLUMNS)
            statement = f"INSERT INTO option_observations ({','.join(import_columns)}) VALUES ({placeholders})"
            for row in rows:
                owner = connection.execute("""
                    SELECT a.customer_id,m.tenant_id
                    FROM customer_trading_accounts a
                    JOIN air_tenant_members m ON m.customer_id=a.customer_id AND m.status='ACTIVE'
                    JOIN air_tenants t ON t.tenant_id=m.tenant_id AND t.status='ACTIVE'
                    WHERE lower(a.broker)=lower(%s) AND a.account_id=%s
                    LIMIT 1
                """, (row["provider"], row["account_id"])).fetchone()
                if not owner:
                    raise RuntimeError(
                        f"Cannot import QOC observations for {row['provider']}/{row['account_id']}: "
                        "no active customer account-to-tenant mapping exists"
                    )
                connection.execute(
                    statement,
                    tuple(row[column] for column in COLUMNS) + (owner["customer_id"], owner["tenant_id"]),
                )
            if rows:
                connection.execute(
                    "SELECT setval(pg_get_serial_sequence('option_observations','id'), "
                    "COALESCE((SELECT MAX(id) FROM option_observations), 1), true)"
                )

        if not dry_run:
            target_rows = connection.execute(
                f"SELECT {column_sql} FROM option_observations ORDER BY id"
            ).fetchall()
            if [tuple(row[column] for column in COLUMNS) for row in target_rows] != [
                tuple(row[column] for column in COLUMNS) for row in rows
            ]:
                raise RuntimeError("QOC field-level reconciliation failed; transaction rolled back")
            connection.execute(
                "INSERT INTO air_domain_store_imports(import_name,source_manifest,imported_at) "
                "VALUES(%s,%s,CURRENT_TIMESTAMP::text)",
                ("sqlite_qoc_observations_v1", manifest),
            )
            report["target_rows_after"] = len(target_rows)

    report["status"] = "DRY_RUN_VALIDATED" if dry_run else "IMPORTED_AND_RECONCILED"
    return report
