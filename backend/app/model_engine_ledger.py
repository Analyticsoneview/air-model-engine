"""Customer-scoped AIR Model Engine signal and position lifecycle ledger.

This is a normalized derived-signal store, not a broker order ledger. No orders are
placed here. Signals enter this ledger only after a research/scoring pipeline writes
a verified record; absent evidence is never synthesized.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


STATUSES = {"NEW", "HOLD", "WAIT", "RE-ENTRY", "SL", "TARGETS", "EXPIRED", "EXPIRYSCAN"}


class ModelEngineLedger:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("AIR_MODEL_LEDGER_DB_PATH", "data/air_model_ledger.sqlite3")
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS model_signals (
                signal_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                classification TEXT NOT NULL CHECK(classification IN
                    ('NEW','HOLD','WAIT','RE-ENTRY','SL','TARGETS','EXPIRED','EXPIRYSCAN')),
                signal_date TEXT NOT NULL,
                entry_date TEXT,
                symbol TEXT NOT NULL,
                instrument_type TEXT,
                option_type TEXT,
                expiry TEXT,
                strike REAL,
                entry_price REAL,
                latest_price REAL,
                stop_loss REAL,
                target_1 REAL,
                target_2 REAL,
                target_3 REAL,
                lot_size INTEGER,
                quantity INTEGER,
                score REAL,
                pnl REAL,
                pnl_pct REAL,
                shelf_life_days INTEGER,
                valid_until TEXT,
                exit_date TEXT,
                exit_price REAL,
                achieved_target TEXT,
                reason TEXT,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
        """)
        # Existing customer databases were created before WAIT was a persisted
        # lifecycle state. Rebuild only when the old CHECK constraint is present.
        schema_row = self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='model_signals'"
        ).fetchone()
        schema_sql = schema_row["sql"] if schema_row else ""
        if "'WAIT'" not in schema_sql:
            updated_schema = schema_sql.replace(
                "CREATE TABLE model_signals",
                "CREATE TABLE model_signals_new",
                1,
            ).replace(
                "('NEW','HOLD','RE-ENTRY','SL','TARGETS','EXPIRED','EXPIRYSCAN')",
                "('NEW','HOLD','WAIT','RE-ENTRY','SL','TARGETS','EXPIRED','EXPIRYSCAN')",
            )
            if updated_schema == schema_sql:
                raise RuntimeError("Unable to safely migrate model_signals lifecycle CHECK constraint")
            self.db.execute("ALTER TABLE model_signals RENAME TO model_signals_legacy")
            self.db.execute(updated_schema)
            self.db.execute("INSERT INTO model_signals_new SELECT * FROM model_signals_legacy")
            self.db.execute("DROP TABLE model_signals_legacy")
            self.db.execute("ALTER TABLE model_signals_new RENAME TO model_signals")
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_model_signals_customer_status
            ON model_signals(customer_id, classification, signal_date DESC)
        """)
        self.db.commit()

    def upsert(self, customer_id: str, record: dict[str, Any]) -> None:
        status = str(record.get("classification", "")).upper()
        if status not in STATUSES:
            raise ValueError("Unsupported signal classification")
        if status == "RE-ENTRY" and not (record.get("evidence") or {}).get("reentry_verified"):
            raise ValueError("RE-ENTRY requires evidence.reentry_verified=true")
        signal_id = str(record.get("signal_id", "")).strip()
        symbol = str(record.get("symbol", "")).strip().upper()
        signal_date = str(record.get("signal_date", "")).strip()
        if not signal_id or not symbol or not signal_date:
            raise ValueError("signal_id, symbol and signal_date are required")
        try:
            date.fromisoformat(signal_date)
            if record.get("expiry"):
                date.fromisoformat(str(record["expiry"]))
        except ValueError as exc:
            raise ValueError("signal_date and expiry must use YYYY-MM-DD") from exc
        fields = [
            "classification", "signal_date", "entry_date", "symbol", "instrument_type",
            "option_type", "expiry", "strike", "entry_price", "latest_price", "stop_loss",
            "target_1", "target_2", "target_3", "lot_size", "quantity", "score", "pnl",
            "pnl_pct", "shelf_life_days", "valid_until", "exit_date", "exit_price",
            "achieved_target", "reason"
        ]
        values = [record.get(field) for field in fields]
        if record.get("entry_date"):
            date.fromisoformat(str(record["entry_date"]))
        if record.get("valid_until"):
            date.fromisoformat(str(record["valid_until"]))
        if record.get("exit_date"):
            date.fromisoformat(str(record["exit_date"]))
        values.extend([json.dumps(record.get("evidence") or {}, default=str),
                       datetime.now(timezone.utc).isoformat()])
        columns = ["signal_id", "customer_id", *fields, "evidence_json", "updated_at"]
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{name}=excluded.{name}" for name in columns[2:])
        with self.db:
            self.db.execute(
                f"INSERT INTO model_signals ({','.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(signal_id) DO UPDATE SET {updates}",
                [signal_id, customer_id, *values],
            )

    def list_signals(self, customer_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.execute("""
            SELECT * FROM model_signals WHERE customer_id=?
            ORDER BY signal_date DESC, updated_at DESC LIMIT ?
        """, (customer_id, max(1, min(limit, 2000)))).fetchall()
        today = date.today()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
            item["sector"] = item["evidence"].get("sector")
            item["pnl_points"] = item["evidence"].get("pnl_points")
            quantity = item.get("quantity")
            pnl_points = item.get("pnl_points")
            item["pnl_rupees"] = (
                round(float(pnl_points) * int(quantity), 2)
                if pnl_points is not None and quantity is not None else None
            )
            expiry = date.fromisoformat(item["expiry"]) if item.get("expiry") else None
            valid_until = date.fromisoformat(item["valid_until"]) if item.get("valid_until") else None
            signal_day = date.fromisoformat(item["signal_date"])
            item["signal_age_days"] = max(0, (today - signal_day).days)
            item["days_to_expiry"] = (expiry - today).days if expiry else None
            classification = str(item.get("classification") or "").upper()
            if classification == "EXPIRED" or (expiry is not None and expiry < today):
                item["position_status"] = "EXPIRED"
            elif classification in ("SL", "TARGETS") or item.get("exit_date") or item.get("exit_price") is not None:
                item["position_status"] = "EXITED"
            elif classification == "HOLD":
                item["position_status"] = "HOLD"
            elif classification == "WAIT":
                item["position_status"] = "WAIT"
            elif classification in ("NEW", "RE-ENTRY"):
                item["position_status"] = "OPEN"
            else:
                item["position_status"] = "—"
            item["days_to_validity_end"] = (valid_until - today).days if valid_until else None
            shelf_end = valid_until or (signal_day.fromordinal(signal_day.toordinal() + item["shelf_life_days"])
                                        if item.get("shelf_life_days") is not None else None)
            item["shelf_life_remaining_days"] = (
                (shelf_end - today).days if shelf_end else None
            )
            item["shelf_life_status"] = (
                "EXPIRED" if item.get("classification") == "EXPIRED" or
                    (expiry is not None and expiry < today) else
                "REVIEW DUE" if shelf_end is not None and shelf_end < today else
                "SURVIVOR" if expiry is not None and 0 <= (expiry - today).days <= 7 else
                "ACTIVE" if shelf_end is not None else "UNDEFINED"
            )
            result.append(item)
        return result

    def close(self) -> None:
        self.db.close()
