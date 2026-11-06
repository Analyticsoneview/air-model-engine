"""Read-only Model Engine ledger API plus operator-only signal ingestion."""
from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.model_engine_ledger import ModelEngineLedger
from app.model_engine_master import build_master
from app.model_engine_expiryscan import scan_expiries
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
              ("SURVIVOR", "NEW", "HOLD", "RE-ENTRY", "SL", "TARGETS", "EXPIRED", "EXPIRYSCAN")}
    for row in rows:
        groups[row["classification"]].append(row)
        # Survivor is a high-priority cross-cutting watchlist, not a replacement
        # for the signal lifecycle classification. Keep original classification.
        dte = row.get("days_to_expiry")
        if dte is not None and 0 <= dte <= 7 and row["classification"] != "EXPIRED":
            groups["SURVIVOR"].append(row)
    groups["SURVIVOR"].sort(key=lambda row: (row.get("days_to_expiry", 999), -(row.get("score") or 0), row["signal_date"]))
    return {
        "source": "AIR Model Engine signal ledger",
        "count": len(rows),
        "counts": {key: len(value) for key, value in groups.items()},
        "groups": groups,
        "updated_at": max((row["updated_at"] for row in rows), default=None),
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
    result = build_master(rows)
    result.update({
        "source": "AIR Model Engine MASTER",
        "updated_at": max((row["updated_at"] for row in rows), default=None),
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


@router.get("/expiryscan")
async def get_expiry_scan(
    max_dte: int = Query(default=45, ge=0, le=365),
    limit: int = Query(default=500, ge=1, le=2000),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Read-only scan of captured Dhan observations owned by this customer."""
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
