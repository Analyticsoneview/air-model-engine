"""Optional market-hours polling for AIR Telegram strategy notifications.

This scheduler replays the existing verified Model Engine data. It does not
fetch new market data, create signals, or place broker orders. EXPIRYSCAN
therefore reports only from snapshots already captured by the AIR QOC pipeline.
"""
from __future__ import annotations

import logging
import os
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.model_engine_api import (
    get_expiry78_engine,
    get_expiry_scan,
    get_original366_engine,
)

log = logging.getLogger("air.telegram.scheduler")
IST = ZoneInfo("Asia/Kolkata")
_scheduler: AsyncIOScheduler | None = None


async def poll_air_strategy_alerts() -> dict:
    if os.getenv("AIR_TELEGRAM_SCHEDULER_ENABLED", "false").lower() != "true":
        return {"status": "disabled"}
    customer_ids = [
        value.strip()
        for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    ]
    if not customer_ids:
        log.error("Telegram scheduler enabled but AIR_OPERATOR_CUSTOMER_IDS is empty")
        return {"status": "not_configured", "customers": 0}

    results = []
    for customer_id in customer_ids:
        for strategy, operation in (
            ("RECOVERED", lambda: get_original366_engine(customer_id=customer_id)),
            ("EXPIRY78", lambda: get_expiry78_engine(customer_id=customer_id)),
            ("EXPIRYSCAN", lambda: get_expiry_scan(customer_id=customer_id)),
        ):
            try:
                result = await operation()
                delivery = result.get("telegram_notifications") or {}
                results.append({
                    "customer": customer_id,
                    "strategy": strategy,
                    "sent": delivery.get("sent", 0),
                    "configured": delivery.get("configured", False),
                })
            except Exception as exc:  # noqa: BLE001
                log.exception("AIR %s scheduled Telegram poll failed", strategy)
                results.append({
                    "customer": customer_id,
                    "strategy": strategy,
                    "error": type(exc).__name__,
                })
    return {"status": "completed", "results": results}


def start_telegram_scheduler() -> None:
    global _scheduler
    if os.getenv("AIR_TELEGRAM_SCHEDULER_ENABLED", "false").lower() != "true":
        log.info("AIR Telegram scheduler disabled")
        return
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone=IST)
    _scheduler.add_job(
        poll_air_strategy_alerts,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/5",
            timezone=IST,
        ),
        id="air-telegram-strategy-poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    log.info("AIR Telegram strategy polling enabled every 5 minutes, weekdays 09:00-15:59 IST")


def stop_telegram_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
