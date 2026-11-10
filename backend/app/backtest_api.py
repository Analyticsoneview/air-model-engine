"""Authenticated discovery and historical-report API for AIR backtests."""
from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query

from app.backtest_registry import registered_backtest_strategies
from app.expiry_case_study_27oct2026 import (
    COHORT_ID, EXPIRY, SOURCE_WORKBOOK, historical_expired_contracts,
)
from app.security import require_customer

router = APIRouter(prefix="/api/v1/backtest", tags=["AIR Historical Backtest"])


@router.get("/strategies")
async def list_backtest_strategies(customer_id: str = Depends(require_customer)) -> dict:
    """List only existing AIR strategies and disclose their data eligibility."""
    strategies = registered_backtest_strategies()
    return {
        "strategies": strategies,
        "daily_candle_eligible": [item["id"] for item in strategies if item.get("available_for_daily_backtest")],
        "intraday_only": [item["id"] for item in strategies if not item.get("available_for_daily_backtest") and item["id"] != "EXPIRYSCAN"],
        "historical_report_available": [item["id"] for item in strategies if item.get("available_for_historical_report")],
        "selection_modes": ["SINGLE", "MULTIPLE", "ALL"],
        "execution": "HISTORICAL_RESEARCH_ONLY_NO_BROKER_ORDERS",
        "note": "Strategy discovery only; each report endpoint discloses its actual data coverage and limitations.",
    }


@router.get("/expiryscan")
async def expiryscan_historical_report(
    start_date: date = Query(..., description="Inclusive report start YYYY-MM-DD"),
    end_date: date = Query(..., description="Inclusive report end YYYY-MM-DD"),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Return preserved historical EXPIRYSCAN expiry-cohort outcomes for a date range.

    This first implementation reports the pinned 27-Oct-2026 cohort. It does
    not fabricate missing daily rows or replay live bid/ask checks from EOD bars.
    """
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date")
    if (end_date - start_date).days > 370:
        raise HTTPException(status_code=422, detail="EXPIRYSCAN historical report is limited to 371 calendar days per request")

    expiry_date = date.fromisoformat(EXPIRY)
    if not (start_date <= expiry_date <= end_date):
        return {
            "strategy": "EXPIRYSCAN", "mode": "HISTORICAL",
            "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            "cohorts": [], "contracts": [], "contract_count": 0,
            "data_status": "NO_PRESERVED_COHORT_IN_PERIOD",
            "note": "No preserved EXPIRYSCAN historical cohort is registered inside this period. This is not proof that no contracts qualified.",
        }

    contracts = historical_expired_contracts()
    report_rows = []
    for item in contracts:
        evidence = item.get("evidence") or {}
        report_rows.append({
            "signal_id": item["signal_id"],
            "cohort_id": item["cohort_id"],
            "qualification_status": "HISTORICAL_COHORT_MEMBER",
            "classification": "EXPIRED",
            "symbol": item["symbol"],
            "instrument_type": item["instrument_type"],
            "option_type": item["option_type"],
            "strike": item["strike"],
            "expiry": item["expiry"],
            "entry_date": item["entry_date"],
            "entry_premium": item["entry_price"],
            "expected_closing_date": "2026-10-26",
            "expected_closing_date_basis": "Verified prior-session date from the preserved 26-Oct-2026 option bhavcopy source",
            "lowest_daily_low": evidence.get("lowest_daily_low"),
            "highest_daily_high": evidence.get("highest_daily_high"),
            "last_traded_close": evidence.get("last_traded_close"),
            "expiry_intrinsic": evidence.get("expiry_intrinsic"),
            "expiry_outcome_points": item.get("pnl_points"),
            "expiry_outcome_pct": item.get("pnl_pct"),
            "daily_observation_count": evidence.get("daily_rows"),
            "daily_detail_status": "SOURCE_WORKBOOK_NOT_PRESENT_IN_REPOSITORY",
            "source": evidence.get("source_bhavcopy"),
            "source_workbook": evidence.get("source_workbook"),
        })

    return {
        "strategy": "EXPIRYSCAN",
        "mode": "HISTORICAL",
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "cohorts": [{
            "cohort_id": COHORT_ID, "expiry": EXPIRY,
            "contract_count": len(report_rows),
            "daily_observation_count": sum(int(row["daily_observation_count"] or 0) for row in report_rows),
            "source": "Preserved AIR QOC/Master cohort and 26-Oct-2026 option bhavcopy",
            "daily_detail_source": SOURCE_WORKBOOK,
        }],
        "contracts": report_rows,
        "contract_count": len(report_rows),
        "daily_observation_count": sum(int(row["daily_observation_count"] or 0) for row in report_rows),
        "data_status": "CONTRACT_SUMMARY_VERIFIED_DAILY_DETAIL_PENDING",
        "limitations": [
            "The 11-contract cohort summary is preserved in source code; its referenced daily-detail workbook is not present in this repository branch.",
            "Daily OHLC sequence, per-session qualification checks and exact stop/exit chronology are therefore not returned.",
            "Expected closing date is a planned pre-expiry review date, not proof of an executed close.",
            "Expiry outcome points and percentages are contract premium/intrinsic comparisons, not rupee P&L; lot quantity, charges and slippage are not assumed.",
            "No broker orders are submitted.",
        ],
        "source_workbook": SOURCE_WORKBOOK,
    }
