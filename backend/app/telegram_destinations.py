"""Persistent, operator-managed Telegram destinations for AIR alerts."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_ALLOWED_STRATEGIES = {"RECOVERED", "EXPIRY78", "EXPIRYSCAN"}
_CHAT_ID = re.compile(r"^-?\d{1,20}$")


def _path() -> str:
    return os.getenv("AIR_TELEGRAM_CONFIG_DB_PATH", "data/air_telegram_config.sqlite3")


@contextmanager
def _database():
    db = _connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _connect() -> sqlite3.Connection:
    path = _path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS telegram_destinations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            chat_id TEXT NOT NULL UNIQUE,
            destination_type TEXT NOT NULL CHECK(destination_type IN ('PRIVATE','GROUP')),
            strategies_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()
    return db


def _validate(name: str, chat_id: str, destination_type: str,
              strategies: list[str]) -> tuple[str, str, str, list[str]]:
    name = name.strip()
    chat_id = chat_id.strip()
    destination_type = destination_type.upper().strip()
    strategies = sorted({item.upper().strip() for item in strategies})
    if not name or len(name) > 80:
        raise ValueError("Destination name must contain 1–80 characters")
    if not _CHAT_ID.fullmatch(chat_id) or chat_id == "0":
        raise ValueError("Chat ID must be a numeric Telegram private or group chat ID")
    if destination_type not in {"PRIVATE", "GROUP"}:
        raise ValueError("Destination type must be PRIVATE or GROUP")
    if destination_type == "PRIVATE" and chat_id.startswith("-"):
        raise ValueError("Private chat IDs must be positive")
    if destination_type == "GROUP" and not chat_id.startswith("-"):
        raise ValueError("Group and supergroup chat IDs must be negative")
    if not strategies or not set(strategies).issubset(_ALLOWED_STRATEGIES):
        raise ValueError("Select at least one supported strategy: RECOVERED, EXPIRY78, EXPIRYSCAN")
    return name, chat_id, destination_type, strategies


def _serialize(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "name": row["name"], "chat_id": row["chat_id"],
        "destination_type": row["destination_type"],
        "strategies": json.loads(row["strategies_json"]),
        "enabled": bool(row["enabled"]), "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_destinations() -> list[dict[str, Any]]:
    with _database() as db:
        rows = db.execute("SELECT * FROM telegram_destinations ORDER BY id").fetchall()
        return [_serialize(row) for row in rows]


def has_managed_destinations() -> bool:
    with _database() as db:
        return db.execute("SELECT 1 FROM telegram_destinations LIMIT 1").fetchone() is not None


def destinations_for_strategy(strategy: str) -> list[str]:
    strategy = strategy.upper()
    with _database() as db:
        rows = db.execute(
            "SELECT chat_id, strategies_json FROM telegram_destinations WHERE enabled=1"
        ).fetchall()
    return [
        row["chat_id"] for row in rows
        if strategy in json.loads(row["strategies_json"])
    ]


def upsert_destination(name: str, chat_id: str, destination_type: str,
                       strategies: list[str], enabled: bool = True) -> dict[str, Any]:
    name, chat_id, destination_type, strategies = _validate(
        name, chat_id, destination_type, strategies
    )
    with _database() as db:
        db.execute("""
            INSERT INTO telegram_destinations
                (name, chat_id, destination_type, strategies_json, enabled)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                name=excluded.name,
                destination_type=excluded.destination_type,
                strategies_json=excluded.strategies_json,
                enabled=excluded.enabled,
                updated_at=CURRENT_TIMESTAMP
        """, (name, chat_id, destination_type, json.dumps(strategies), int(enabled)))
        row = db.execute(
            "SELECT * FROM telegram_destinations WHERE chat_id=?", (chat_id,)
        ).fetchone()
        return _serialize(row)


def update_destination(destination_id: int, *, name: str, chat_id: str,
                       destination_type: str, strategies: list[str],
                       enabled: bool) -> dict[str, Any] | None:
    name, chat_id, destination_type, strategies = _validate(
        name, chat_id, destination_type, strategies
    )
    with _database() as db:
        db.execute("""
            UPDATE telegram_destinations SET name=?, chat_id=?, destination_type=?,
                strategies_json=?, enabled=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (name, chat_id, destination_type, json.dumps(strategies),
              int(enabled), destination_id))
        row = db.execute(
            "SELECT * FROM telegram_destinations WHERE id=?", (destination_id,)
        ).fetchone()
        return _serialize(row) if row else None


def delete_destination(destination_id: int) -> bool:
    with _database() as db:
        cur = db.execute("DELETE FROM telegram_destinations WHERE id=?", (destination_id,))
        return cur.rowcount > 0
