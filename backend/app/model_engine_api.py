"""Read-only Model Engine ledger API plus operator-only signal ingestion."""
from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.model_engine_ledger import ModelEngineLedger
from app.model_engine_master import build_master
from app.model_engine_expiryscan import scan_expiries
from app.model_engine_expiry78 import RULES as EXPIRY78_RULES, evaluate_expiry78_rows
from app.expiry_case_study_27oct2026 import historical_expired_contracts
from app.air_qoc_store import AirQocStore
from app.brokers.customer_accounts import CustomerAccountDirectory
from app.security import require_customer

router = APIRouter(prefix="/api/v1/model-engine", tags=["AIR Model Engine"])
_ledger = ModelEngineLedger()


def _operator(customer_id: str = Depends(require_customer)) -> str:
    allowed = {x.strip() for x in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",") if x.strip()}
    if customer_id not in allowed:
        raise HTTPException(status_code=403, detail="AIR operator permission is required")
    return customer_id


class SignalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal_id: str = Field(min_length=1, max_length=160)
    classification: str
    signal_date: str
    entry_date: str | None = None
    symbol: str = Field(min_length=1, max_length=40)
    sector: str | None = Field(default=None, max_length=80)
    instrument_type: str | None = None
    option_type: str | None = None
    expiry: str | None = None
    strike: float | None = None
    entry_price: float | None = None
    latest_price: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    target_3: float | None = None
    lot_size: int | None = None
    quantity: int | None = None
    score: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
    pnl_points: float | None = None
    shelf_life_days: int | None = Field(default=None, ge=0, le=3650)
    valid_until: str | None = None
    exit_date: str | None = None
    exit_price: float | None = None
    achieved_target: str | None = None
    reason: str | None = None
    evidence: dict = Field(default_factory=dict)


@router.get("/ledger")
async def get_model_engine_ledger(
    limit: int = Query(default=500, ge=1, le=2000),
    customer_id: str = Depends(require_customer),
) -> dict:
    rows = _ledger.list_signals(customer_id, limit)
    groups = {key: [] for key in
              ("SURVIVOR", "NEW", "HOLD", "WAIT", "RE-ENTRY", "SL", "TARGETS", "EXPIRED", "EXPIRYSCAN")}
    for row in rows:
        groups[row["classification"]].append(row)
        # Survivor is a high-priority cross-cutting watchlist, not a replacement
        # for the signal lifecycle classification. Keep original classification.
        dte = row.get("days_to_expiry")
        entry_date, expiry = row.get("entry_date"), row.get("expiry")
        if (row.get("classification") in ("NEW", "HOLD", "RE-ENTRY")
                and dte is not None and dte >= 0 and entry_date and expiry
                and str(entry_date)[:10] < str(expiry)[:10]):
            groups["SURVIVOR"].append(row)
    groups["SURVIVOR"].sort(key=lambda row: (row.get("days_to_expiry", 999), -(row.get("score") or 0), row["signal_date"]))
    return {
        "source": "AIR Model Engine signal ledger",
        "count": len(rows),
        "counts": {key: len(value) for key, value in groups.items()},
        "groups": groups,
        "updated_at": max((row.get("updated_at") for row in rows if row.get("updated_at")), default=None),
        "data_status": "POPULATED" if rows else "AWAITING_VERIFIED_SIGNALS",
        "note": "Only persisted, verified model signals are shown. No sample signals or broker orders are generated.",
    }


@router.get("/master")
async def get_model_engine_master(
    limit: int = Query(default=2000, ge=1, le=2000),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Canonical MASTER view over verified persisted signals."""
    rows = _ledger.list_signals(customer_id, limit)
    # Valid past-expiry observations from EXPIRYSCAN also belong in EXPIRED.
    try:
        scan = _expiry_scan_for_customer(customer_id, max_dte=45, limit=2000)
        for item in scan.get("expired_rows", []):
            if item.get("classification") != "EXPIRED":
                continue
            observed_at = str(item.get("observed_at") or "")
            rows.append({
                "signal_id": "EXPIRYSCAN:" + ":".join(str(item.get(k) or "") for k in
                    ("security_id", "expiry", "strike", "option_type")),
                "classification": "EXPIRED",
                "signal_date": observed_at[:10] if len(observed_at) >= 10 else scan["as_of"],
                "entry_date": None,
                "symbol": item.get("symbol") or item.get("underlying_scrip"),
                "instrument_type": "INDEX" if str(item.get("underlying_segment") or "").upper().startswith("IDX") else "STOCK",
                "option_type": item.get("option_type"),
                "expiry": item.get("expiry"),
                "strike": item.get("strike"),
                "latest_price": item.get("last_price"),
                "days_to_expiry": item.get("days_to_expiry"),
                "position_status": "EXPIRED",
                "evidence": {
                    "source": "EXPIRYSCAN",
                    "expiry_date_valid": True,
                    "expiry_status_reason": item.get("expiry_status_reason"),
                    "observed_at": observed_at,
                    "underlying_price": item.get("underlying_price"),
                    "volume": item.get("volume"),
                    "open_interest": item.get("open_interest"),
                    "bid_price": item.get("bid_price"),
                    "ask_price": item.get("ask_price"),
                },
            })
    except HTTPException as exc:
        if exc.status_code not in (503, 403):
            raise
    # Preserve the original, explicitly selected 11-contract 27-Oct-2026
    # case-study cohort in EXPIRED. Merge into matching ledger rows rather than
    # duplicating a contract. This is independent of generic EXPIRYSCAN expiry
    # transitions and all DTE/session-count subsets.
    for case in historical_expired_contracts():
        match = next((row for row in rows
                      if str(row.get("symbol") or "").upper() == case["symbol"]
                      and str(row.get("option_type") or "").upper() == case["option_type"]
                      and str(row.get("expiry") or "")[:10] == case["expiry"]
                      and row.get("strike") is not None
                      and float(row["strike"]) == float(case["strike"])), None)
        if match is None:
            rows.append(case)
        else:
            prior_evidence = match.get("evidence") if isinstance(match.get("evidence"), dict) else {}
            match.update({
                "classification": "EXPIRED",
                "position_status": "EXPIRED",
                "latest_price": case["latest_price"],
                "days_to_expiry": case["days_to_expiry"],
                "pnl_points": case["pnl_points"],
                "pnl_pct": case["pnl_pct"],
                "cohort_id": case["cohort_id"],
                "evidence": {**prior_evidence, **case["evidence"]},
            })
    result = build_master(rows)
    result.update({
        "source": "AIR Model Engine MASTER",
        "historical_expiry_cohorts": {
            "EXPIRY_2026-10-27_CASE_STUDY_11": {
                "expiry": "2026-10-27",
                "contracts": 11,
                "source": "AIR QOC/Master + op261026.csv",
                "daily_detail_source": "AIR_EXPIRYSCAN_EXPIRED_27Oct2026_11Contracts_DailyDetail.xlsx",
            }
        },
        "updated_at": max((row.get("updated_at") for row in rows if row.get("updated_at")), default=None),
        "data_status": "POPULATED" if rows else "AWAITING_VERIFIED_SIGNALS",
    })
    return result


@router.post("/signals", status_code=201)
async def upsert_model_engine_signal(
    body: SignalRecord,
    customer_id: str = Depends(_operator),
) -> dict:
    record = body.model_dump()
    if record.get('sector'):
        record.setdefault('evidence', {})['sector'] = record['sector']
    if record.get('pnl_points') is not None:
        record.setdefault('evidence', {})['pnl_points'] = record['pnl_points']
    try:
        _ledger.upsert(customer_id, record)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "saved", "signal_id": record["signal_id"],
            "classification": record["classification"].upper()}


def _expiry_scan_for_customer(customer_id: str, *, max_dte: int = 45,
                              limit: int = 2000) -> dict:
    account_id = os.getenv("AIR_QOC_DHAN_ACCOUNT_ID", "").strip()
    if not account_id:
        raise HTTPException(status_code=503, detail="Dhan snapshot account is not configured")
    directory = CustomerAccountDirectory(os.getenv("AIR_ACCOUNT_DB_PATH", "data/customer_accounts.sqlite3"))
    try:
        owned = {(account.broker, account.account_id)
                 for account in directory.list_for_customer(customer_id)}
    finally:
        directory.close()
    if ("dhan", account_id) not in owned:
        raise HTTPException(status_code=403, detail="No access to configured Dhan snapshot account")
    store = AirQocStore()
    try:
        return scan_expiries(store, account_id=account_id, max_dte=max_dte, limit=limit)
    finally:
        store.close()


@router.get("/expiry78")
async def get_expiry78_engine(
    limit: int = Query(default=2000, ge=1, le=2000),
    as_of: str | None = Query(default=None, description="Replay cutoff date YYYY-MM-DD"),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Replay verified daily option OHLCV for explicitly tagged EXPIRY78 contracts."""
    rows = _ledger.list_signals(customer_id, limit)
    contracts = evaluate_expiry78_rows(rows, as_of=as_of)
    trades = [trade for contract in contracts
              for trade in (contract.get("expiry78") or {}).get("trades", [])]
    return {
        "strategy": "EXPIRY78",
        "as_of": as_of,
        "rules": EXPIRY78_RULES,
        "contracts_replayed": len(contracts),
        "trade_count": len(trades),
        "expiry_survivors": sum(bool(trade.get("expiry_survivor")) for trade in trades),
        "stop_losses": sum(trade.get("classification") == "SL" for trade in trades),
        "groups": {
            "NEW": [trade for trade in trades if trade.get("classification") == "NEW"],
            "HOLD": [trade for trade in trades if trade.get("classification") == "HOLD"],
            "WAIT": [trade for trade in trades if trade.get("classification") == "WAIT"],
            "SLHIT": [trade for trade in trades if trade.get("classification") == "SL"],
            "EXPIRED": [trade for trade in trades if trade.get("classification") == "EXPIRED"],
        },
        "contracts": contracts,
        "data_status": "POPULATED" if contracts else "AWAITING_VERIFIED_DAILY_OHLCV",
        "note": "Read-only historical replay. Requires evidence.daily_option_bars on explicitly tagged EXPIRY78 ledger records. No orders are placed; missing bars or expiry valuation are not fabricated.",
    }


@router.get("/expiryscan")
async def get_expiry_scan(
    max_dte: int = Query(default=45, ge=0, le=365),
    limit: int = Query(default=500, ge=1, le=2000),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Read-only scan of captured Dhan option-chain observations owned by this customer."""
    return _expiry_scan_for_customer(customer_id, max_dte=max_dte, limit=limit)
