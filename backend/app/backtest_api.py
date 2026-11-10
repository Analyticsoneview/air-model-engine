"""Authenticated discovery API for the AIR historical backtest registry."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.backtest_registry import registered_backtest_strategies
from app.security import require_customer

router = APIRouter(prefix="/api/v1/backtest", tags=["AIR Historical Backtest"])


@router.get("/strategies")
async def list_backtest_strategies(customer_id: str = Depends(require_customer)) -> dict:
    """List only existing AIR strategies and disclose their data eligibility."""
    strategies = registered_backtest_strategies()
    return {
        "strategies": strategies,
        "daily_candle_eligible": [item["id"] for item in strategies if item["available_for_daily_backtest"]],
        "intraday_only": [item["id"] for item in strategies if not item["available_for_daily_backtest"]],
        "selection_modes": ["SINGLE", "MULTIPLE", "ALL"],
        "execution": "HISTORICAL_RESEARCH_ONLY_NO_BROKER_ORDERS",
        "note": (
            "This endpoint is the strategy catalog. A run is not marked complete "
            "until its historical data, strategy-specific replay, P&L calculation "
            "and persisted result have all passed validation."
        ),
    }
