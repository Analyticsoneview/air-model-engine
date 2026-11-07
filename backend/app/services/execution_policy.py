"""Persistent AIR automatic-order policy. Default is manual-only."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

STRATEGIES = ("EXPIRY78", "EXPIRYSCAN", "RECOVERED")


class ExecutionPolicy:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("AIR_EXECUTION_POLICY_DB_PATH", "data/air_execution_policy.sqlite3")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS execution_policy (
                id INTEGER PRIMARY KEY CHECK(id=1),
                master_auto_enabled INTEGER NOT NULL DEFAULT 0,
                strategy_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
        """)
        self.db.execute("""
            INSERT OR IGNORE INTO execution_policy(id,master_auto_enabled,strategy_json,updated_at)
            VALUES(1,0,'{}',?)
        """, (datetime.now(timezone.utc).isoformat(),))
        self.db.commit()

    def get(self) -> dict:
        row = self.db.execute("SELECT * FROM execution_policy WHERE id=1").fetchone()
        flags = json.loads(row["strategy_json"] or "{}")
        return {
            "master_auto_enabled": bool(row["master_auto_enabled"]),
            "strategies": {name: bool(flags.get(name, False)) for name in STRATEGIES},
            "effective_auto": {
                name: bool(row["master_auto_enabled"]) and bool(flags.get(name, False))
                for name in STRATEGIES
            },
            "manual_review_enabled": True,
            "manual_order_submission_enabled": False,
            "default_mode": "MANUAL",
            "updated_at": row["updated_at"],
            "live_orders_enabled": False,
            "note": "Policy only. Broker order submission remains separately gated until live execution adapters and risk controls are verified.",
        }

    def update(self, master_auto_enabled: bool, strategies: dict[str, bool]) -> dict:
        unknown = set(strategies) - set(STRATEGIES)
        if unknown:
            raise ValueError(f"Unknown strategy controls: {sorted(unknown)}")
        current = self.get()["strategies"]
        current.update({key: bool(value) for key, value in strategies.items()})
        # A strategy cannot remain effectively automatic when the master is OFF.
        stamp = datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.execute(
                "UPDATE execution_policy SET master_auto_enabled=?,strategy_json=?,updated_at=? WHERE id=1",
                (int(master_auto_enabled), json.dumps(current, sort_keys=True), stamp),
            )
        return self.get()

    def authorize_mode(self, strategy: str, requested_mode: str) -> str:
        strategy = strategy.strip().upper()
        requested_mode = requested_mode.strip().upper()
        if strategy not in STRATEGIES or requested_mode not in {"MANUAL", "AUTO"}:
            raise ValueError("Unsupported strategy or execution mode")
        policy = self.get()
        if requested_mode == "AUTO" and not policy["effective_auto"][strategy]:
            raise PermissionError("Automatic execution is disabled by AIR master or strategy switch")
        return requested_mode

    def close(self) -> None:
        self.db.close()
