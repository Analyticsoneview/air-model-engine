"""Durable, account-scoped order intent and broker result ledger.

The unique idempotency key prevents a retry from submitting the same intent twice
after a process restart. A broker timeout is recorded as UNKNOWN, never retried
automatically; reconcile it against the broker order book before retrying.
"""
import json
import sqlite3
from pathlib import Path

from app.brokers.base import BrokerOrder


class DurableOrderLedger:
    def __init__(self, db_path: str = "data/air_orders.sqlite3") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS order_ledger (
                broker TEXT NOT NULL,
                account_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                broker_order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (broker, account_id, idempotency_key)
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_order_ledger_status
            ON order_ledger(status, updated_at)
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS order_ledger_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker TEXT NOT NULL,
                account_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL,
                broker_order_id TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                event_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_order_events_account
            ON order_ledger_events(broker, account_id, event_id)
        """)
        self._db.commit()

    def get(self, broker: str, account_id: str, idempotency_key: str) -> BrokerOrder | None:
        row = self._db.execute("""
            SELECT broker, account_id, broker_order_id, status, raw_json
            FROM order_ledger WHERE broker=? AND account_id=? AND idempotency_key=?
        """, (broker.lower(), account_id, idempotency_key)).fetchone()
        if row is None:
            return None
        return BrokerOrder(row["broker"], row["account_id"], row["broker_order_id"],
                           row["status"], json.loads(row["raw_json"]))

    def record(self, order: BrokerOrder, idempotency_key: str) -> None:
        with self._db:
            self._db.execute("""
                INSERT INTO order_ledger
                    (broker, account_id, idempotency_key, broker_order_id, status, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(broker, account_id, idempotency_key) DO UPDATE SET
                    broker_order_id=excluded.broker_order_id,
                    status=excluded.status,
                    raw_json=excluded.raw_json,
                    updated_at=CURRENT_TIMESTAMP
            """, (order.broker.lower(), order.account_id, idempotency_key,
                  order.broker_order_id, order.status, json.dumps(order.raw, default=str)))
            self._db.execute("""
                INSERT INTO order_ledger_events
                    (broker, account_id, idempotency_key, broker_order_id, status, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (order.broker.lower(), order.account_id, idempotency_key,
                  order.broker_order_id, order.status, json.dumps(order.raw, default=str)))

    def list_events(self, broker: str, account_id: str, limit: int = 500) -> list[dict]:
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        rows = self._db.execute("""
            SELECT event_id, idempotency_key, broker_order_id, status, raw_json, event_at
            FROM order_ledger_events
            WHERE broker=? AND account_id=? ORDER BY event_id DESC LIMIT ?
        """, (broker.lower(), account_id, limit)).fetchall()
        return [{
            "event_id": row["event_id"],
            "idempotency_key": row["idempotency_key"],
            "broker_order_id": row["broker_order_id"],
            "status": row["status"],
            "raw": json.loads(row["raw_json"]),
            "event_at": row["event_at"],
        } for row in rows]

    def list_orders(self, broker: str | None = None, account_id: str | None = None,
                    limit: int = 500) -> list[BrokerOrder]:
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        clauses, params = [], []
        if broker:
            clauses.append("broker=?")
            params.append(broker.lower())
        if account_id:
            clauses.append("account_id=?")
            params.append(account_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._db.execute(
            "SELECT broker, account_id, broker_order_id, status, raw_json FROM order_ledger"
            + where + " ORDER BY created_at DESC LIMIT ?", (*params, limit)
        ).fetchall()
        return [BrokerOrder(r["broker"], r["account_id"], r["broker_order_id"],
                            r["status"], json.loads(r["raw_json"])) for r in rows]

    def close(self) -> None:
        self._db.close()
