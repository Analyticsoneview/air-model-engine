"""Secure Telegram notifications for AIR strategy qualification events.

Configuration is supplied only through backend secrets/environment:
  AIR_TELEGRAM_BOT_TOKEN
  AIR_TELEGRAM_CHAT_IDS (comma-separated private/group chat IDs)
  AIR_TELEGRAM_DEDUPE_DB_PATH (optional SQLite path)

No token or chat ID is embedded in source code.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx


def _settings() -> tuple[str, list[str]]:
    token = os.getenv("AIR_TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [value.strip() for value in
                os.getenv("AIR_TELEGRAM_CHAT_IDS", "").split(",") if value.strip()]
    return token, chat_ids


def _db_path() -> str:
    return os.getenv("AIR_TELEGRAM_DEDUPE_DB_PATH", "data/air_telegram_notifications.sqlite3")


def _connect() -> sqlite3.Connection:
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("""
        CREATE TABLE IF NOT EXISTS telegram_deliveries (
            event_key TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (event_key, chat_id)
        )
    """)
    db.commit()
    return db


def _candidate_key(strategy: str, row: dict[str, Any]) -> str:
    identity = row.get("signal_id") or "|".join(str(row.get(key) or "") for key in (
        "symbol", "underlying_scrip", "expiry", "strike", "option_type"
    ))
    status = (row.get("classification") or row.get("position_status")
              or row.get("scan_status") or "QUALIFIED")
    material = f"{strategy.upper()}|{identity}|{str(status).upper()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _format_message(strategy: str, row: dict[str, Any]) -> str:
    symbol = row.get("symbol") or row.get("underlying_scrip") or "Unknown"
    option = row.get("option_type") or ""
    strike = row.get("strike")
    expiry = row.get("expiry") or "—"
    status = (row.get("classification") or row.get("position_status")
              or row.get("scan_status") or "QUALIFIED")
    lines = [f"AIR {strategy} | {str(status).replace('_', ' ')}",
             f"Contract: {symbol} {option} {strike if strike is not None else ''}".strip(),
             f"Expiry: {expiry}"]
    fields = (
        ("Entry", row.get("entry_price", row.get("entry"))),
        ("LTP / Premium", row.get("latest_price", row.get("last_price"))),
        ("Underlying", row.get("underlying_price")),
        ("Stop loss", row.get("stop_loss")),
        ("Target 1", row.get("target_1")),
        ("Target 2", row.get("target_2")),
        ("Target 3", row.get("target_3")),
        ("DTE", row.get("days_to_expiry")),
        ("Volume", row.get("volume")),
        ("OI", row.get("open_interest")),
        ("OI change", row.get("oi_change")),
        ("Spread %", row.get("spread_pct")),
        ("QOC score", row.get("qoc_score", row.get("score"))),
    )
    for label, value in fields:
        if value is not None:
            lines.append(f"{label}: {value}")
    if strategy.upper() == "RECOVERED":
        lines.append("NOTICE: Watch/backtest candidate only; not a live position or order.")
    elif strategy.upper() == "EXPIRYSCAN":
        lines.append("NOTICE: Liquidity-screen pass only; not an AIR QOC trade qualification.")
    else:
        lines.append("NOTICE: Research alert only; no broker order has been placed.")
    return "\n".join(lines)[:3900]


async def send_telegram_message(text: str) -> dict[str, Any]:
    """Send a test/operational message to every configured destination."""
    token, chat_ids = _settings()
    if not token or not chat_ids:
        return {"configured": False, "sent": 0,
                "reason": "Set AIR_TELEGRAM_BOT_TOKEN and AIR_TELEGRAM_CHAT_IDS."}
    sent, failures = 0, []
    async with httpx.AsyncClient(timeout=10) as client:
        for chat_id in chat_ids:
            try:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok"):
                    raise RuntimeError("Telegram API returned ok=false")
                sent += 1
            except Exception as exc:  # noqa: BLE001 - delivery failures are reported, not fatal to scans
                failures.append({"chat_id": chat_id, "error": str(exc)[:240]})
    return {"configured": True, "sent": sent, "failures": failures}


async def notify_candidates(strategy: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Notify once per candidate/status/destination; safe to call on repeated API polls."""
    token, chat_ids = _settings()
    if not token or not chat_ids or not rows:
        return {"configured": bool(token and chat_ids), "attempted": 0, "sent": 0}
    attempted = sent = 0
    failures: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=10) as client:
        for row in rows:
            event_key = _candidate_key(strategy, row)
            message = _format_message(strategy, row)
            for chat_id in chat_ids:
                attempted += 1
                db = _connect()
                try:
                    cur = db.execute(
                        "INSERT OR IGNORE INTO telegram_deliveries(event_key, chat_id, status) "
                        "VALUES (?, ?, 'PENDING')", (event_key, chat_id)
                    )
                    db.commit()
                    if cur.rowcount == 0:
                        continue
                    response = await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
                    )
                    response.raise_for_status()
                    if not response.json().get("ok"):
                        raise RuntimeError("Telegram API returned ok=false")
                    db.execute(
                        "UPDATE telegram_deliveries SET status='SENT' "
                        "WHERE event_key=? AND chat_id=?", (event_key, chat_id)
                    )
                    db.commit()
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    db.execute("DELETE FROM telegram_deliveries WHERE event_key=? AND chat_id=?",
                               (event_key, chat_id))
                    db.commit()
                    failures.append({"chat_id": chat_id, "error": str(exc)[:240]})
                finally:
                    db.close()
    return {"configured": True, "attempted": attempted, "sent": sent, "failures": failures}
