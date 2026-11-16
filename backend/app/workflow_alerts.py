"""Operational alert evaluation and deduplicated Telegram delivery for AIR workflows."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("air.workflow.alerts")


def evaluate_runtime_alerts(
    store, *, dispatch_depth: int | None, dead_letter_depth: int | None,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    current = now or datetime.now(timezone.utc)
    alerts: list[dict[str, str]] = []
    metrics = store.runtime_metrics()
    pending = int(metrics["outbox"]["pending"])
    failed = int(metrics["outbox"]["failed"])
    backlog_limit = max(1, int(os.getenv("AIR_WORKFLOW_ALERT_BACKLOG_THRESHOLD", "100")))

    if pending >= backlog_limit:
        alerts.append({
            "key": "outbox-backlog",
            "title": "Workflow outbox backlog",
            "detail": f"{pending} events are pending publication (threshold {backlog_limit}).",
        })
    if failed:
        alerts.append({
            "key": "outbox-retry-exhaustion",
            "title": "Workflow outbox retry exhaustion",
            "detail": f"{failed} events exhausted the publisher retry budget and require inspection.",
        })
    if dispatch_depth is not None and dispatch_depth >= backlog_limit:
        alerts.append({
            "key": "dispatch-backlog",
            "title": "Workflow dispatch queue backlog",
            "detail": f"{dispatch_depth} messages are waiting in the dispatch queue (threshold {backlog_limit}).",
        })
    if dead_letter_depth is not None and dead_letter_depth > 0:
        alerts.append({
            "key": "dead-letter-depth",
            "title": "Workflow dead-letter queue is not empty",
            "detail": f"{dead_letter_depth} messages require operator review.",
        })

    for worker in store.list_worker_heartbeats(500):
        if worker.get("component") != "workflow-runtime" or worker.get("status") == "STOPPING":
            continue
        try:
            seen = datetime.fromisoformat(str(worker["last_seen"]).replace("Z", "+00:00"))
            age = max(0.0, (current - seen).total_seconds())
        except (KeyError, TypeError, ValueError):
            age = float("inf")
        if worker.get("status") != "RUNNING" or age > 45:
            reason = "heartbeat stale" if age > 45 else f"status {worker.get('status')}"
            alerts.append({
                "key": "worker-unhealthy:" + str(worker.get("worker_id", "unknown")),
                "title": "Workflow worker unhealthy",
                "detail": f"Worker {worker.get('worker_id', 'unknown')} is unhealthy ({reason}; age {int(age) if age != float('inf') else 'unknown'}s).",
            })
    return alerts


def _connect_dedupe() -> sqlite3.Connection:
    path = os.getenv(
        "AIR_WORKFLOW_ALERT_DEDUPE_DB_PATH",
        os.getenv("AIR_TELEGRAM_DEDUPE_DB_PATH", "data/air_workflow_alerts.sqlite3"),
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("""
        CREATE TABLE IF NOT EXISTS workflow_alert_deliveries (
            alert_key TEXT PRIMARY KEY,
            last_sent_at TEXT NOT NULL
        )
    """)
    db.commit()
    return db


def _claim_delivery(alert_key: str, repeat_after_minutes: int = 30) -> bool:
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=repeat_after_minutes)).isoformat()
    db = _connect_dedupe()
    try:
        cursor = db.execute(
            """INSERT INTO workflow_alert_deliveries(alert_key,last_sent_at)
               VALUES(?,?)
               ON CONFLICT(alert_key) DO UPDATE SET last_sent_at=excluded.last_sent_at
               WHERE workflow_alert_deliveries.last_sent_at<=?""",
            (alert_key, now.isoformat(), cutoff),
        )
        db.commit()
        return cursor.rowcount == 1
    finally:
        db.close()


def deliver_runtime_alerts(alerts: list[dict[str, str]]) -> dict[str, int]:
    """Deliver admin/platform alerts with per-destination deduplication.

    No customer ID is attached, so customer-owned notification destinations are
    never used for platform health information. Failed destinations remain
    retryable without resending to destinations that already accepted the alert.
    """
    if not alerts:
        return {"attempted": 0, "sent": 0}
    from app.telegram_notifications import _chat_ids, send_telegram_message

    destinations = _chat_ids("AIR_WORKFLOW", None)
    if not destinations:
        log.warning("AIR workflow runtime alerts are active but no admin Telegram destination is configured")
        return {"attempted": len(alerts), "sent": 0}

    attempted = sent = 0
    for alert in alerts:
        stable_key = hashlib.sha256(alert["key"].encode("utf-8")).hexdigest()
        message = (
            "<b>AIR WORKFLOW OPERATIONS ALERT</b>\\n"
            f"<b>{alert['title']}</b>\\n{alert['detail']}\\n\\n"
            "<i>Operator action may be required. No broker orders are placed by this service.</i>"
        )
        for chat_id in destinations:
            destination_key = hashlib.sha256(f"{stable_key}:{chat_id}".encode("utf-8")).hexdigest()
            if not _claim_delivery(destination_key):
                continue
            attempted += 1
            try:
                result = asyncio.run(send_telegram_message(message, destination_ids=[chat_id]))
                delivered = int(result.get("sent", 0))
                sent += delivered
                if delivered == 0:
                    db = _connect_dedupe()
                    try:
                        db.execute("DELETE FROM workflow_alert_deliveries WHERE alert_key=?", (destination_key,))
                        db.commit()
                    finally:
                        db.close()
            except Exception as exc:
                log.warning("AIR workflow operational alert delivery failed (%s)", type(exc).__name__)
                db = _connect_dedupe()
                try:
                    db.execute("DELETE FROM workflow_alert_deliveries WHERE alert_key=?", (destination_key,))
                    db.commit()
                finally:
                    db.close()
    return {"attempted": attempted, "sent": sent}
