"""Authenticated AIR strategy discovery and EXPIRYSCAN forward reports."""
from __future__ import annotations

import os
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.backtest_registry import registered_backtest_strategies
from app.security import require_customer
from app.brokers.customer_accounts import CustomerAccountDirectory
from app.air_qoc_store import AirQocStore
from app.model_engine_expiryscan import scan_expiries

router = APIRouter(prefix="/api/v1/backtest", tags=["AIR Historical Backtest"])
_accounts = CustomerAccountDirectory(os.getenv("AIR_ACCOUNT_DB_PATH", "data/customer_accounts.sqlite3"))
_qoc_store = AirQocStore()


def _require_operator(customer_id: str) -> str:
    allowed = {x.strip() for x in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",") if x.strip()}
    if customer_id not in allowed:
        raise HTTPException(status_code=403, detail="AIR operator permission is required")
    return customer_id


@router.get("/strategies")
async def list_backtest_strategies(customer_id: str = Depends(require_customer)) -> dict:
    """List existing AIR strategies and disclose historical/forward data eligibility."""
    _require_operator(customer_id)
    strategies = registered_backtest_strategies()
    return {
        "strategies": strategies,
        "daily_candle_eligible": [item["id"] for item in strategies if item["available_for_daily_backtest"]],
        "intraday_only": [item["id"] for item in strategies if not item["available_for_daily_backtest"]],
        "selection_modes": ["SINGLE", "MULTIPLE", "ALL"],
        "execution": "RESEARCH_ONLY_NO_BROKER_ORDERS",
        "note": "Catalog discovery only; historical runs require a validated replay implementation.",
    }


@router.get("/expiryscan/forward/{account_id}")
async def expiryscan_forward_report(
    account_id: str,
    horizon_days: int = Query(default=30, ge=1, le=31),
    provider: str = Query(default="dhan", pattern="^dhan$"),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Report existing EXPIRYSCAN liquidity-screen results for the next month.

    The existing scan_expiries function remains the sole qualification source.
    This endpoint does not invent entry, stop, target or forecast prices.
    """
    operator_id = _require_operator(customer_id)
    owned = {(a.broker, a.account_id) for a in _accounts.list_for_customer(operator_id)}
    if (provider, account_id) not in owned:
        raise HTTPException(status_code=404, detail="Dhan account not found for this operator")

    as_of = date.today()
    scan = scan_expiries(
        _qoc_store, account_id=account_id, provider=provider,
        today=as_of, max_dte=horizon_days, limit=2000,
    )
    rows = []
    for item in scan["rows"]:
        screen_passed = item["scan_status"] == "LIQUIDITY_SCREEN_PASSED"
        rows.append({
            **item,
            "qualification_status": "SCREEN_QUALIFIED" if screen_passed else item["scan_status"],
            "qualified": screen_passed,
            "expected_closing_date": item["close_before_expiry_date"],
            "expected_closing_date_basis": "previous_weekday_before_expiry; exchange holidays not adjusted",
            "expected_closing_premium": None,
            "outcome_status": "PENDING_EXPIRY",
            "realized_outcome": None,
        })

    qualified = [r for r in rows if r["qualified"]]
    return {
        "strategy": "EXPIRYSCAN",
        "report_type": "FORWARD",
        "as_of": as_of.isoformat(),
        "window_start": as_of.isoformat(),
        "window_end": (as_of + timedelta(days=horizon_days)).isoformat(),
        "horizon_days": horizon_days,
        "provider": provider,
        "account_id": account_id,
        "contracts_seen": len(rows),
        "qualified_contracts": len(qualified),
        "watch_contracts": len(rows) - len(qualified),
        "qualified_trade_signals": 0,
        "qualification_basis": "Existing EXPIRYSCAN checks: positive volume, positive OI, valid two-sided bid/ask and spread at most 10%. This is a liquidity-screen pass, not an AIR QOC trade signal.",
        "outcome_policy": "Future contracts remain pending. Realized outcomes are populated only after expiry when verified historical observations/settlement are available.",
        "data_quality": {
            "missing_evidence_contracts": sum(bool(r["missing_evidence"]) for r in rows),
            "source_observation_timestamps_required": True,
        },
        "rows": rows,
        "expired_rows_excluded": scan["expired_count"],
        "note": "Research report only. No order placement, auto-close, forecast premium, entry, stop-loss or target is generated. Expected closing date is a weekday estimate; exchange holiday calendar adjustment is not yet implemented.",
    }
