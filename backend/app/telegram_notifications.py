"""Secure Telegram notifications for AIR strategy qualification events.

Configuration is supplied only through backend secrets/environment:
  AIR_TELEGRAM_BOT_TOKEN
  AIR_TELEGRAM_CHAT_IDS (comma-separated private/group chat IDs)
  AIR_TELEGRAM_DEDUPE_DB_PATH (optional SQLite path)

No token or chat ID is embedded in source code.
"""
from __future__ import annotations

import hashlib
import html
import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx


def _settings() -> tuple[str, list[str]]:
    token = os.getenv("AIR_TELEGRAM_BOT_TOKEN", "").strip()
    token_file = os.getenv("AIR_TELEGRAM_BOT_TOKEN_FILE", "").strip()
    if token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
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
    status = (row.get("scan_status") or row.get("classification")
              or row.get("position_status") or "QUALIFIED")
    material = f"{strategy.upper()}|{identity}|{str(status).upper()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _fmt(value: Any, prefix: str = "") -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{prefix}{value:,.2f}"
    return f"{prefix}{value}"


def _format_message(strategy: str, row: dict[str, Any]) -> str:
    """Trader-friendly Telegram HTML message; never overstates a screen as a trade."""
    name = strategy.upper()
    symbol = row.get("symbol") or row.get("underlying_scrip") or "Unknown"
    option = str(row.get("option_type") or "").upper()
    strike = row.get("strike")
    expiry = row.get("expiry") or "—"
    dte = row.get("days_to_expiry")
    raw_status = str(row.get("scan_status") or row.get("classification")
                     or row.get("position_status") or "QUALIFIED").upper()
    score = row.get("qoc_score", row.get("score"))

    if name == "RECOVERED":
        headline, status_label = "👀 RECOVERED WATCH CANDIDATE", "WATCH ONLY"
        disclaimer = "Historical recovery model / watchlist only. This is NOT a live position or fresh buy instruction."
    elif name == "EXPIRYSCAN":
        headline, status_label = "🔎 EXPIRYSCAN LIQUIDITY CANDIDATE", "SCREEN PASSED"
        disclaimer = "Liquidity-screen pass only. It is NOT a fully qualified AIR QOC trade signal."
    elif raw_status in ("SL", "SLHIT", "STOP_LOSS", "STOPPED"):
        headline, status_label = "🛑 EXPIRY78 STOP-LOSS UPDATE", "EXIT / SL HIT"
        disclaimer = "Status update for a model-tracked candidate. Verify live broker position before acting."
    elif raw_status in ("EXPIRED", "CLOSED", "TARGETS", "CLOSED_TARGET"):
        headline, status_label = "📌 EXPIRY78 POSITION UPDATE", raw_status.replace("_", " ")
        disclaimer = "Model research status; verify contract and broker records before acting."
    else:
        headline, status_label = "🚀 EXPIRY78 QUALIFIED CANDIDATE", "QUALIFIED / MONITOR"
        disclaimer = "Research candidate, not an order. Confirm live price, liquidity and risk before trading."

    contract = " ".join(str(part) for part in (symbol, option, strike) if part not in (None, ""))
    lines = [
        f"<b>{html.escape(headline)}</b>",
        f"<b>AIR STRATEGY:</b> {html.escape(name)}",
        f"<b>STATUS:</b> {html.escape(status_label)}",
        "",
        f"📍 <b>Contract:</b> {html.escape(contract)}",
        f"📅 <b>Expiry:</b> {html.escape(str(expiry))}"
        + (f"  |  <b>DTE:</b> {html.escape(str(dte))}" if dte is not None else ""),
    ]

    entry = row.get("entry_price", row.get("entry"))
    premium = row.get("latest_price", row.get("last_price"))
    underlying = row.get("underlying_price")
    stop = row.get("stop_loss")
    targets = [row.get(f"target_{i}") for i in (1, 2, 3)]
    if entry is not None or premium is not None or underlying is not None:
        lines += ["", "💰 <b>PRICE LEVELS</b>"]
        if premium is not None:
            lines.append(f"Current premium: <b>₹{_fmt(premium)}</b>")
        if entry is not None:
            lines.append(f"Planned / model entry: <b>₹{_fmt(entry)}</b>")
        if underlying is not None:
            lines.append(f"Underlying price: ₹{_fmt(underlying)}")
        if stop is not None:
            lines.append(f"🛑 Stop-loss: <b>₹{_fmt(stop)}</b>")
        for index, target in enumerate(targets, 1):
            if target is not None:
                lines.append(f"🎯 Target {index}: <b>₹{_fmt(target)}</b>")

    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    reason = row.get("reason") or row.get("qualification_reason") or evidence.get("qualification_reason")
    checks = row.get("checks") if isinstance(row.get("checks"), dict) else {}
    if reason or checks:
        lines += ["", "🧠 <b>WHY IT APPEARED</b>"]
        if reason:
            lines.append(html.escape(str(reason)[:450]))
        for key, value in list(checks.items())[:6]:
            lines.append(f"{'✅' if value else '⚠️'} {html.escape(str(key).replace('_', ' ').title())}")

    metrics = [
        ("QOC score", score), ("Volume", row.get("volume")),
        ("Open interest", row.get("open_interest")), ("OI change", row.get("oi_change")),
        ("Bid", row.get("bid_price")), ("Ask", row.get("ask_price")),
        ("Bid/ask spread", f"{row.get('spread_pct')}%" if row.get("spread_pct") is not None else None),
    ]
    available = [(label, value) for label, value in metrics if value is not None]
    if available:
        lines += ["", "📊 <b>MARKET EVIDENCE</b>"]
        lines.extend(f"{label}: <b>{html.escape(str(value))}</b>" for label, value in available)

    if score is not None:
        try:
            score_num = float(score)
            conviction = "🟢 HIGH CONVICTION" if score_num >= 90 else "🟢 QUALIFIED" if score_num >= 80 else "🟡 WATCH" if score_num >= 70 else "🔴 NOT QUALIFIED"
            lines += ["", f"<b>CONVICTION:</b> {conviction} ({html.escape(str(score))}/100)"]
        except (TypeError, ValueError):
            pass

    lines += ["", f"⚠️ <i>{html.escape(disclaimer)}</i>",
              "<i>AIR — Analytical Investment Research</i>"]
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
            except Exception as exc:  # noqa: BLE001
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
                        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML",
                              "disable_web_page_preview": True},
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
