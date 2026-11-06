"""Optional daily AIR QOC option-chain snapshot scheduler.

Disabled by default. Configure only after confirming Dhan Data API entitlement and
permitted use. Runs at 15:45 Asia/Kolkata, fetches every active expiry for each
explicitly configured underlying, and rate-limits unique option-chain requests.
It captures observations only; it does not generate trading signals or orders.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.air_qoc_store import AirQocStore
from app.brokers.dhan import DhanHQClient
from app.brokers.customer_accounts import CustomerAccountDirectory
from app.credential_vault import CredentialVault

log = logging.getLogger("air.qoc.scheduler")
IST = ZoneInfo("Asia/Kolkata")


def _configured_underlyings() -> list[dict]:
    raw = os.getenv("AIR_QOC_DHAN_UNDERLYINGS", "[]")
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AIR_QOC_DHAN_UNDERLYINGS must be a JSON array") from exc
    if not isinstance(values, list):
        raise RuntimeError("AIR_QOC_DHAN_UNDERLYINGS must be a JSON array")
    result = []
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("security_id"), int) or item["security_id"] <= 0:
            raise RuntimeError("Each configured underlying needs an integer security_id")
        segment = str(item.get("segment", "")).strip()
        if segment not in {"IDX_I", "NSE_FNO"}:
            raise RuntimeError("Underlying segment must be IDX_I or NSE_FNO")
        result.append({
            "security_id": item["security_id"],
            "segment": segment,
            "label": str(item.get("label", item["security_id"]))[:80],
        })
    return result


async def capture_dhan_eod_snapshots(*, force: bool = False) -> dict:
    if not force and os.getenv("AIR_QOC_SCHEDULER_ENABLED", "false").lower() != "true":
        return {"status": "disabled"}
    customer_ids = [x.strip() for x in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",") if x.strip()]
    account_id = os.getenv("AIR_QOC_DHAN_ACCOUNT_ID", "").strip()
    if not customer_ids or not account_id:
        raise RuntimeError("Configure AIR_OPERATOR_CUSTOMER_IDS and AIR_QOC_DHAN_ACCOUNT_ID")
    customer_id = customer_ids[0]
    accounts = CustomerAccountDirectory(os.getenv("AIR_ACCOUNT_DB_PATH", "data/customer_accounts.sqlite3"))
    owned = {(a.broker, a.account_id) for a in accounts.list_for_customer(customer_id)}
    if ("dhan", account_id) not in owned:
        raise RuntimeError("Configured AIR QOC Dhan account is not registered to the operator")
    vault = CredentialVault(os.getenv("AIR_CREDENTIAL_DB_PATH", "data/air_credentials.sqlite3"))
    credentials = vault.get(customer_id, "dhan", account_id)
    client_id = credentials.get("client_id", account_id)
    access_token = credentials.get("access_token")
    if not access_token:
        raise RuntimeError("Dhan access token is not configured")
    underlyings = _configured_underlyings()
    if not underlyings:
        raise RuntimeError("No AIR QOC underlyings configured")
    client = DhanHQClient(client_id, access_token)
    store = AirQocStore()
    total = 0
    expiry_count = 0
    errors = []
    try:
        await client.profile()
        for underlying in underlyings:
            try:
                expiries = await client.option_expiry_list(
                    underlying_scrip=underlying["security_id"],
                    underlying_segment=underlying["segment"],
                )
                await asyncio.sleep(3.1)
                for expiry in expiries:
                    chain = await client.option_chain(
                        underlying_scrip=underlying["security_id"],
                        underlying_segment=underlying["segment"],
                        expiry=expiry,
                    )
                    observed_at = datetime.now(IST).isoformat()
                    total += store.save_option_chain(
                        account_id=account_id,
                        underlying_scrip=underlying["security_id"],
                        underlying_segment=underlying["segment"],
                        expiry=expiry,
                        underlying_price=chain.get("last_price"),
                        observed_at=observed_at,
                        chain=chain,
                    )
                    expiry_count += 1
                    await asyncio.sleep(3.1)
            except Exception as exc:
                errors.append({"underlying": underlying["label"], "error": type(exc).__name__})
                log.exception("AIR QOC snapshot failed for %s", underlying["label"])
        return {
            "status": "completed_with_errors" if errors else "completed",
            "underlyings": len(underlyings),
            "expiry_chains": expiry_count,
            "contract_observations": total,
            "errors": errors,
            "observed_at": datetime.now(IST).isoformat(),
            "classification": "DATA_CAPTURE_ONLY_NOT_A_SIGNAL",
        }
    finally:
        await client.close()
        store.close()
        vault.close()
        accounts.close()


_scheduler: AsyncIOScheduler | None = None


def start_qoc_scheduler() -> None:
    global _scheduler
    if os.getenv("AIR_QOC_SCHEDULER_ENABLED", "false").lower() != "true":
        log.info("AIR QOC scheduler disabled")
        return
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone=IST)
    _scheduler.add_job(
        capture_dhan_eod_snapshots,
        CronTrigger(hour=15, minute=45, day_of_week="mon-fri", timezone=IST),
        id="air-qoc-dhan-eod-snapshots",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    log.info("AIR QOC Dhan snapshot scheduler enabled for 15:45 IST weekdays")


def stop_qoc_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
