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
from app.model_engine_expiryscan import scan_expiries
from app.brokers.dhan import DhanHQClient, DhanAPIError
from app.brokers.customer_accounts import CustomerAccountDirectory
from app.credential_vault import CredentialVault
from app.air_qoc_universe import DETAILED_MASTER_URL, parse_dhan_instrument_master
from app.market_data.runtime import market_data_router, market_data_instruments, market_data_service
import httpx

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


async def capture_dhan_eod_snapshots(*, force: bool = False, account_id_override: str | None = None) -> dict:
    if not force and os.getenv("AIR_QOC_SCHEDULER_ENABLED", "false").lower() != "true":
        return {"status": "disabled"}
    customer_ids = [x.strip() for x in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",") if x.strip()]
    account_id = (account_id_override or os.getenv("AIR_QOC_DHAN_ACCOUNT_ID", "")).strip()
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
    # Discover the complete NSE F&O universe automatically. A configured static
    # list is retained only as a fallback if the official master is unavailable.
    try:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as session:
            master_response = await session.get(DETAILED_MASTER_URL)
            master_response.raise_for_status()
        master = parse_dhan_instrument_master(master_response.text)
        underlyings = [
            {"security_id": item["security_id"], "segment": item["exchange_segment"],
             "label": item["symbol"]}
            for item in master["underlyings"] if item["validated"]
        ]
        if not underlyings:
            raise RuntimeError("Dhan master returned no validated NSE F&O underlyings")
        log.info("Discovered %s NSE F&O underlyings (%s stocks, %s indices)",
                 len(underlyings), master["stock_underlying_count"], master["index_underlying_count"])
    except (httpx.HTTPError, ValueError) as exc:
        underlyings = _configured_underlyings()
        if not underlyings:
            raise RuntimeError("Automatic Dhan F&O universe discovery failed and no fallback universe is configured") from exc
        log.warning("Using configured fallback universe because Dhan master discovery failed")
    client = DhanHQClient(client_id, access_token)
    if os.getenv("AIR_QOC_DHAN_AUTO_RENEW_ENABLED", "false").lower() == "true":
        try:
            renewed = await client.renew_token()
            credentials["access_token"] = renewed["accessToken"]
            vault.put(customer_id, "dhan", account_id, credentials)
            await client.close()
            client = DhanHQClient(client_id, renewed["accessToken"])
            log.info("Renewed active Dhan Web token for configured AIR QOC account")
        except DhanAPIError:
            # Dhan only renews active tokens originally generated from Dhan Web.
            # API-key/OAuth tokens or already-expired tokens must use their own flow.
            log.warning("Dhan Web token renewal was unavailable; validating the existing token")
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
        expiry_scan = scan_expiries(
            store, account_id=account_id,
            max_dte=int(os.getenv("AIR_EXPIRYSCAN_MAX_DTE", "45")),
            limit=int(os.getenv("AIR_EXPIRYSCAN_MAX_ROWS", "2000")),
        )
        return {
            "status": "completed_with_errors" if errors else "completed",
            "underlyings": len(underlyings),
            "expiry_chains": expiry_count,
            "contract_observations": total,
            "expiry_scan": {
                "status": "completed",
                "contracts": expiry_scan["total_contracts"],
                "survivors_0_7_dte": expiry_scan["survivor_count"],
                "max_dte": expiry_scan["max_dte"],
            },
            "errors": errors,
            "observed_at": datetime.now(IST).isoformat(),
            "classification": "DATA_CAPTURE_ONLY_NOT_A_SIGNAL",
        }
    finally:
        await client.close()
        store.close()
        vault.close()
        accounts.close()


async def capture_selected_provider_option_chains(*, force: bool = False) -> dict:
    """Capture option-chain observations using the selected normalized live provider.

    Non-Dhan providers must have their official F&O instrument master imported into
    AIR's provider/account-scoped instrument directory. Dhan keeps its dedicated
    exchange option-chain endpoint as the fallback where no complete master exists.
    """
    if not force and os.getenv("AIR_QOC_SCHEDULER_ENABLED", "false").lower() != "true":
        return {"status": "disabled"}
    source = market_data_router.resolve("live")
    if not source:
        raise RuntimeError("No connected live market-data provider is selected")
    provider, account_id, _adapter = source[0]
    mappings = market_data_instruments.list_all(provider, account_id, limit=50000)
    if provider == "dhan":
        # Dhan's official option-chain endpoint carries OI and bid/ask snapshots;
        # keep using it rather than reconstructing the chain from websocket ticks.
        return await capture_dhan_eod_snapshots(force=force, account_id_override=account_id)
    option_rows = [row for row in mappings
                   if str(row.get("option_type") or "").upper() in {"CE", "PE"}
                   and row.get("expiry")]
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in option_rows:
        underlying = str(row.get("underlying_symbol") or "").upper()
        if not underlying:
            continue
        groups.setdefault((underlying, str(row["expiry"])[:10]), []).append(row)
    if not groups:
        raise RuntimeError(
            f"No F&O instrument master is loaded for {provider}/{account_id}; "
            "import the provider's official instrument master first."
        )
    store = AirQocStore()
    captured = errors = 0
    failed = []
    try:
        for (symbol, expiry), rows in sorted(groups.items()):
            try:
                snapshot = await market_data_service.option_chain_snapshot(
                    symbol, expiry, wait_seconds=float(os.getenv("AIR_QOC_LIVE_WAIT_SECONDS", "4")))
                underlying_segment = "IDX_I" if any(
                    "INDEX" in str(row.get("instrument_type") or "").upper()
                    for row in rows) else "NSE_FNO"
                captured += store.save_option_chain(
                    provider=provider, account_id=account_id,
                    underlying_scrip=symbol, underlying_segment=underlying_segment,
                    expiry=expiry, underlying_price=snapshot.get("underlying_price"),
                    observed_at=snapshot["observed_at"], chain=snapshot["chain"],
                )
            except Exception as exc:
                errors += 1
                failed.append({"symbol": symbol, "expiry": expiry,
                               "error_type": type(exc).__name__})
                log.exception("AIR option-chain capture failed for %s %s", symbol, expiry)
        expiry_scan = scan_expiries(
            store, provider=provider, account_id=account_id,
            max_dte=int(os.getenv("AIR_EXPIRYSCAN_MAX_DTE", "45")),
            limit=int(os.getenv("AIR_EXPIRYSCAN_MAX_ROWS", "2000")),
        )
        return {
            "status": "completed_with_errors" if errors else "completed",
            "provider": provider, "account_id": account_id,
            "underlying_expiry_groups": len(groups),
            "contract_observations": captured, "failed_groups": failed,
            "expiry_scan": {"contracts": expiry_scan["total_contracts"],
                            "survivors_0_7_dte": expiry_scan["survivor_count"],
                            "expired": expiry_scan["expired_count"]},
            "observed_at": datetime.now(IST).isoformat(),
            "classification": "DATA_CAPTURE_ONLY_NOT_A_SIGNAL",
        }
    finally:
        store.close()


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
        capture_selected_provider_option_chains,
        CronTrigger(hour=15, minute=20, day_of_week="mon-fri", timezone=IST),
        id="air-qoc-selected-provider-eod-snapshots",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    log.info("AIR QOC selected-provider snapshot scheduler enabled for 15:20 IST weekdays")


def stop_qoc_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
