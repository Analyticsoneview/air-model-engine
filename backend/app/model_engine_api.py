"""Read-only Model Engine ledger API plus operator-only signal ingestion."""
from __future__ import annotations

import os
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.model_engine_ledger import ModelEngineLedger
from app.model_engine_master import build_master
from app.model_engine_expiryscan import scan_expiries
from app.model_engine_expiry78 import RULES as EXPIRY78_RULES, evaluate_expiry78_rows
from app.model_engine_original366 import ORIGINAL366_RULES, evaluate_original366_rows
from app.model_engine_strategies import ORIGINAL366_BASELINE
from app.expiry_case_study_27oct2026 import historical_expired_contracts
from app.air_qoc_store import AirQocStore
from app.access_control import access_store
from app.brokers.customer_accounts import CustomerAccountDirectory
from app.security import require_customer
from app.telegram_notifications import notify_candidates, send_telegram_message
from app.market_data.runtime import execution_policy
from app.market_data.customer_runtime import get_customer_market_data_service

router = APIRouter(prefix="/api/v1/model-engine", tags=["AIR Model Engine"])
_ledger = ModelEngineLedger()


def _has_strategy_membership(row: dict, strategy: str) -> bool:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    memberships = evidence.get("strategy_memberships") or evidence.get("strategies") or []
    if isinstance(memberships, str):
        memberships = [memberships]
    normalized = {str(value).upper().replace(" ", "") for value in memberships}
    single = evidence.get("strategy") or row.get("strategy")
    if single:
        normalized.add(str(single).upper().replace(" ", ""))
    return strategy.upper().replace(" ", "") in normalized


def _strategy_rows_for_customer(customer_id: str, limit: int) -> list[dict]:
    """Share the operator-published strategy feed while retaining tenant overrides."""
    publishers = [
        value.strip() for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    ]
    publisher_id = publishers[0] if publishers else customer_id
    published = _ledger.list_signals(publisher_id, limit)
    if publisher_id == customer_id:
        return published
    customer_rows = _ledger.list_signals(customer_id, limit)
    merged = {str(row.get("signal_id")): row for row in published}
    # Tenant-owned records override the published baseline only for that tenant.
    for row in customer_rows:
        merged[str(row.get("signal_id"))] = row
    return list(merged.values())[:limit]


async def _customer_market_data_service(customer_id: str):
    try:
        return await get_customer_market_data_service(customer_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Customer market-data source is unavailable: {type(exc).__name__}",
        ) from exc


def _is_operator_customer(customer_id: str) -> bool:
    allowed = {x.strip() for x in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",") if x.strip()}
    if customer_id in allowed:
        return True
    return (access_store.mobile_for_request_id(customer_id) or "") in allowed


def _operator(customer_id: str = Depends(require_customer)) -> str:
    if not _is_operator_customer(customer_id):
        raise HTTPException(status_code=403, detail="AIR operator permission is required")
    return customer_id


async def _notify_operator_candidates(
    strategy: str, rows: list[dict], customer_id: str
) -> dict:
    # Strategy endpoints are customer-authenticated, but Telegram destinations
    # are operator-owned. Never forward a non-operator customer's records.
    if not _is_operator_customer(customer_id):
        return {"configured": False, "attempted": 0, "sent": 0}
    return await notify_candidates(strategy, rows)


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
    customer_service = await get_customer_market_data_service(customer_id)
    rows = await customer_service.hydrate_strategy_rows(_ledger.list_signals(customer_id, limit))
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
    customer_service = await get_customer_market_data_service(customer_id)
    rows = await customer_service.hydrate_strategy_rows(_strategy_rows_for_customer(customer_id, limit), max_contracts=2000)
    # Valid past-expiry observations from EXPIRYSCAN also belong in EXPIRED.
    try:
        scan = await _expiry_scan_for_customer(customer_id, max_dte=45, limit=2000)
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


async def _expiry_scan_for_customer(customer_id: str, *, max_dte: int = 45,
                                     limit: int = 2000) -> dict:
    service = await get_customer_market_data_service(customer_id)
    source = service.router.resolve("live")
    if not source:
        raise HTTPException(
            status_code=503,
            detail="No live broker market-data connection is enabled for this customer",
        )
    provider, account_id, _adapter = source[0]
    store = AirQocStore()
    try:
        return service.expiry_scan(
            store, provider=provider, account_id=account_id,
            max_dte=max_dte, limit=limit)
    finally:
        store.close()


@router.get("/original366")
async def get_original366_engine(
    limit: int = Query(default=2000, ge=1, le=2000),
    as_of: str | None = Query(default=None, description="Replay cutoff date YYYY-MM-DD"),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Build the RECOVERED watch from the ORIGINAL366 cohort and post-stop daily closes."""
    customer_service = await get_customer_market_data_service(customer_id)
    rows = await customer_service.hydrate_strategy_rows(_ledger.list_signals(customer_id, limit), max_contracts=2000)
    contracts = evaluate_original366_rows(rows, as_of=as_of)
    trades = [trade for contract in contracts
              for trade in (contract.get("original366") or {}).get("trades", [])]
    winners = [trade for trade in trades if trade.get("classification") == "EXPIRED_WIN"]
    expiry_losses = [trade for trade in trades if trade.get("classification") == "EXPIRED_LOSS"]
    stopped = [trade for trade in trades if trade.get("classification") == "SLHIT"]
    recovered_watch = []
    recovered_groups = {key: [] for key in ("OPEN", "TARGETS", "SLHIT", "EXPIRED", "WAIT")}
    original_sl_hits = stopped
    cutoff_day = date.fromisoformat(as_of[:10]) if as_of else date.today()
    for trade in stopped:
        watch = trade.get("recovered_watch")
        if not watch:
            continue
        exit_model = watch.get("exit_model") or {}
        outcome = str(exit_model.get("outcome") or "UNRESOLVED").upper()
        row = {
            **trade, "classification": "RECOVERED_WATCH", "watch": watch,
            "signal_date": watch["trigger_date"],
            "latest_price": watch["trigger_close"],
            "entry_price": watch.get("reference_entry_price", trade.get("entry_price")),
            "stop_loss": exit_model.get("stop_loss"),
            "target_1": exit_model.get("target"),
            "exit_date": exit_model.get("exit_date"),
            "exit_price": exit_model.get("exit_price"),
            "exit_reason": exit_model.get("exit_reason"),
            "pnl_points": exit_model.get("pnl_points"),
            "pnl_pct": exit_model.get("return_pct"),
            "recovered_outcome": outcome,
            "position_status": "WATCH_ONLY_NOT_OPEN",
            "reason": "Post-stop close above original entry; alternative exits use original entry with 10% SL / 45% target",
        }
        recovered_watch.append(row)
        if outcome == "TARGET_FIRST":
            row["classification"] = "TARGETS"
            row["position_status"] = "CLOSED_TARGET"
            recovered_groups["TARGETS"].append(row)
        elif outcome == "STOP_FIRST":
            row["classification"] = "SLHIT"
            row["position_status"] = "CLOSED_STOP"
            recovered_groups["SLHIT"].append(row)
        elif outcome == "EXPIRY_SETTLEMENT":
            row["classification"] = "EXPIRED"
            row["position_status"] = "EXPIRED"
            recovered_groups["EXPIRED"].append(row)
        else:
            expiry_text = str(trade.get("expiry") or "")[:10]
            try:
                active = bool(expiry_text and date.fromisoformat(expiry_text) > cutoff_day)
            except ValueError:
                active = False
            if active:
                row["classification"] = "OPEN"
                row["position_status"] = "OPEN"
                recovered_groups["OPEN"].append(row)
            else:
                row["classification"] = "WAIT"
                row["position_status"] = "WAIT_EXPIRY_VALUATION"
                recovered_groups["WAIT"].append(row)
    new_rows = [
        row for row in rows
        if str(row.get("classification") or "").upper() == "NEW"
        and _has_strategy_membership(row, "ORIGINAL366")
    ]
    telegram_delivery = await _notify_operator_candidates("RECOVERED", recovered_groups["OPEN"], customer_id)
    return {
        "telegram_notifications": telegram_delivery,
        "strategy": "RECOVERED",
        "execution_policy": execution_policy.get(),
        "cohort_id": "ORIGINAL366",
        "as_of": as_of,
        "rules": ORIGINAL366_RULES,
        "cohort_reference": dict(ORIGINAL366_BASELINE),
        "baseline_status": "COHORT_FILTER_ONLY",
        "contracts_replayed": len(contracts),
        "trade_count": len(trades),
        "expiry_winners": len(winners),
        "expiry_losses": len(expiry_losses),
        "stop_losses": len(stopped),
        "recovered_watch_count": len(recovered_watch),
        "counts": {**{key: len(value) for key, value in recovered_groups.items()},
                   "EXPIRED": len(recovered_groups["EXPIRED"]) + len(winners) + len(expiry_losses),
                   "RECOVERED": len(recovered_watch), "ORIGINAL_SLHIT": len(original_sl_hits)},
        "groups": {
            **recovered_groups,
            "ORIGINAL_SLHIT": original_sl_hits,
            "RECOVERED": recovered_watch,
            "NEW": [trade for trade in trades if trade.get("classification") == "NEW"],
            "HOLD": [trade for trade in trades if trade.get("classification") == "HOLD"],
            "REENTRY": [
                row for row in rows
                if str(row.get("classification") or "").upper() in ("RE-ENTRY", "REENTRY")
                and isinstance(row.get("evidence"), dict)
                and row["evidence"].get("reentry_verified") is True
                and _has_strategy_membership(row, "ORIGINAL366")
            ],
            "EXPIRED": recovered_groups["EXPIRED"] + winners + expiry_losses,
            "EXPIRED_WIN": winners,
            "EXPIRED_LOSS": expiry_losses,
        },
        "contracts": contracts,
        "new_candidates_pending_replay": len(new_rows),
        "data_status": "POPULATED" if contracts else "AWAITING_VERIFIED_DAILY_OHLCV",
        "note": "RECOVERED is a watch/backtest section for the ORIGINAL366 reference cohort. A post-original-5%-SL daily close above original entry adds a watch row; its retrospective alternative exit uses the same original entry price with 10% SL / 45% target. Alternative-model points are historical analysis only; no live position, re-entry or broker order is created.",
    }


@router.get("/expiry78")
async def get_expiry78_engine(
    limit: int = Query(default=2000, ge=1, le=2000),
    as_of: str | None = Query(default=None, description="Replay cutoff date YYYY-MM-DD"),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Replay verified daily option OHLCV for explicitly tagged EXPIRY78 contracts."""
    customer_service = await get_customer_market_data_service(customer_id)
    rows = await customer_service.hydrate_strategy_rows(_ledger.list_signals(customer_id, limit), max_contracts=2000)
    contracts = evaluate_expiry78_rows(rows, as_of=as_of)
    trades = [trade for contract in contracts
              for trade in (contract.get("expiry78") or {}).get("trades", [])]
    verified_reentries = []
    for row in rows:
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        memberships = evidence.get("strategy_memberships") or evidence.get("strategies") or []
        if isinstance(memberships, str):
            memberships = [memberships]
        membership_set = {str(value).upper().replace(" ", "") for value in memberships}
        if (str(row.get("classification") or "").upper() in ("RE-ENTRY", "REENTRY")
                and evidence.get("reentry_verified") is True
                and ("EXPIRY78" in membership_set or
                     str(evidence.get("strategy") or row.get("strategy") or "").upper() == "EXPIRY78")):
            verified_reentries.append(row)
    waiting_contracts = [
        contract for contract in contracts
        if not (contract.get("expiry78") or {}).get("trades")
    ]
    new_trades = [trade for trade in trades if trade.get("classification") == "NEW"]
    hold_trades = [trade for trade in trades if trade.get("classification") == "HOLD"]
    telegram_rows = new_trades + hold_trades + verified_reentries + [
        trade for trade in trades if trade.get("classification") in ("SL", "EXPIRED")
    ]
    telegram_delivery = await _notify_operator_candidates("EXPIRY78", telegram_rows, customer_id)
    return {
        "telegram_notifications": telegram_delivery,
        "strategy": "EXPIRY78",
        "execution_policy": execution_policy.get(),
        "as_of": as_of,
        "rules": EXPIRY78_RULES,
        "contracts_replayed": len(contracts),
        "trade_count": len(trades),
        "expiry_survivors": sum(bool(trade.get("expiry_survivor")) for trade in trades),
        "stop_losses": sum(trade.get("classification") == "SL" for trade in trades),
        "groups": {
            "OPEN": new_trades + hold_trades + verified_reentries,
            "NEW": new_trades,
            "HOLD": hold_trades,
            "WAIT": [trade for trade in trades if trade.get("classification") == "WAIT"],
            "SLHIT": [trade for trade in trades if trade.get("classification") == "SL"],
            "REENTRY": verified_reentries,
            "EXPIRED": [trade for trade in trades if trade.get("classification") == "EXPIRED"],
        },
        "waiting_contracts": waiting_contracts,
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
    """Read-only scan of option-chain observations from the selected live provider."""
    result = await _expiry_scan_for_customer(customer_id, max_dte=max_dte, limit=limit)
    result["execution_policy"] = execution_policy.get()
    # This endpoint currently produces a liquidity-screen pass, not a full QOC
    # trade qualification. Telegram labels these notifications accordingly.
    qualified = [row for row in result.get("rows", [])
                 if row.get("scan_status") == "LIQUIDITY_SCREEN_PASSED"]
    result["telegram_notifications"] = await _notify_operator_candidates("EXPIRYSCAN", qualified, customer_id)
    return result


@router.get("/physical-settlement")
async def get_physical_settlement_review(
    customer_id: str = Depends(require_customer),
) -> dict:
    """Read-only physical-delivery review for the historical EXPIRY78 cohort."""
    from app.model_engine_physical_settlement import build_physical_settlement_review
    result = build_physical_settlement_review()
    result["customer_scope"] = "authenticated_customer"
    return result


@router.get("/pnl-calendar")
async def get_model_engine_pnl_calendar(
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    limit: int = Query(default=2000, ge=1, le=2000),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Calendar P&L with separate entry-capital and exit-realization dates."""
    from app.model_engine_pnl_calendar import build_pnl_calendar
    from app.model_engine_physical_settlement import build_physical_settlement_review
    customer_service = await get_customer_market_data_service(customer_id)
    rows = await customer_service.hydrate_strategy_rows(_ledger.list_signals(customer_id, limit), max_contracts=2000)
    master = build_master(rows)
    physical_review = build_physical_settlement_review()
    return build_pnl_calendar(master.get("strategies") or {},
                              physical_review=physical_review, year=year, month=month)


@router.post("/telegram/test")
async def test_air_telegram_notifications(
    customer_id: str = Depends(_operator),
) -> dict:
    """Send a test message to all configured AIR Telegram destinations."""
    result = await send_telegram_message(
        "AIR Model Engine Telegram connection test\n"
        "Private and group destinations are configured for strategy alerts."
    )
    if not result.get("configured"):
        raise HTTPException(status_code=503, detail=result.get("reason"))
    return {"status": "sent" if result.get("sent") else "failed", **result}
