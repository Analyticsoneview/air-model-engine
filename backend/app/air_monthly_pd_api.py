"""Administrator read/evaluate API for AIR MPDSM; inputs must be verified market data."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.security import require_admin
from app.air_monthly_pd import monthly_levels, evaluate_support_acceptance, classify_price_structure, classify_premium_discount
from app.air_monthly_pd_store import AirMonthlyPdStore

router=APIRouter(prefix="/api/v1/admin/monthly-pd",tags=["AIR Monthly Premium-Discount"])

class EvaluationRequest(BaseModel):
    instrument_type: str = Field(pattern="^(EQUITY|INDEX)$")
    symbol: str = Field(min_length=1,max_length=80)
    cycle_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    reference_date: date
    as_of_date: date
    previous_month_bars: list[dict] = Field(min_length=1)
    post_reference_bars: list[dict] = Field(default_factory=list)
    structure_bars: list[dict] = Field(default_factory=list)
    expiry_metadata: dict = Field(default_factory=dict)
    options_evidence: dict = Field(default_factory=dict)
    options_contracts: list[dict] = Field(default_factory=list)
    actual: dict = Field(default_factory=dict)

@router.post("/evaluate")
async def evaluate_monthly_pd(body: EvaluationRequest, admin: dict=Depends(require_admin)):
    store=AirMonthlyPdStore()
    try:
        levels=monthly_levels(body.previous_month_bars)
        support=evaluate_support_acceptance(body.post_reference_bars,levels["pml"],2,body.reference_date.isoformat())
        pattern=classify_price_structure(body.structure_bars)
        from app.air_monthly_pd import expiry_tags, classify_expiry_participation
        option_rows=[]
        for contract in body.options_contracts:
            try:
                expiry=date.fromisoformat(str(contract["expiry_date"]))
                participation=classify_expiry_participation(
                    option_volume=contract.get("option_volume"),
                    historical_volume_avg=contract.get("historical_volume_avg"),
                    oi_change_pct=contract.get("oi_change_pct"),
                    premium_change_pct=contract.get("premium_change_pct"),
                    spread_pct=contract.get("spread_pct"),
                    underlying_volume_ratio=contract.get("underlying_volume_ratio"),
                )
                option_rows.append({"expiry":expiry_tags(expiry), "option_type":contract.get("option_type"),
                    "strike":contract.get("strike"), "participation":participation,
                    "settlement_watch":bool(contract.get("is_itm") and (date.fromisoformat(body.as_of_date.isoformat()) >= expiry.replace(day=max(1,expiry.day-5))))})
            except (KeyError,ValueError,TypeError) as exc:
                option_rows.append({"classification":"DATA_INSUFFICIENT","reason":str(exc)})
        last_close=float(body.structure_bars[-1]["close"]) if body.structure_bars else None
        zone=classify_premium_discount(last_close,levels["pml"],levels["pmh"]) if last_close is not None else "DATA_INSUFFICIENT"
        cycle=store.save_cycle(instrument_type=body.instrument_type,symbol=body.symbol,
            cycle_month=body.cycle_month,reference_date=body.reference_date.isoformat(),
            pml=levels["pml"],pmh=levels["pmh"],eq=levels["eq"])
        snapshot=store.save_snapshot(cycle_id=cycle["cycle_id"],as_of_date=body.as_of_date.isoformat(),
            snapshot_type="DAILY",support_status=support["status"],pattern=pattern["pattern"],
            pattern_state=pattern["state"],expiry_metadata=body.expiry_metadata,
            evidence={"support":support,"options":body.options_evidence,"options_contracts":option_rows,"premium_discount_zone":zone},
            forecast={"pattern":pattern,"premium_discount_zone":zone},actual=body.actual)
        return {"cycle":cycle,"snapshot":snapshot,"levels":levels,"support":support,
                "pattern":pattern,"options_contracts":option_rows,"premium_discount_zone":zone,
                "disclosure":"Research-only; supplied data is not independently verified by this endpoint and no broker orders are placed."}
    except (ValueError,KeyError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc
    finally: store.close()

@router.get("/cycles")
async def list_monthly_pd_cycles(symbol: str|None=None,cycle_month: str|None=None,limit: int=500,
                                 admin: dict=Depends(require_admin)):
    store=AirMonthlyPdStore()
    try:return {"cycles":store.list_cycles(symbol=symbol,cycle_month=cycle_month,limit=limit)}
    finally:store.close()

@router.get("/snapshots")
async def list_monthly_pd_snapshots(cycle_id: str|None=None,limit: int=500,
                                    admin: dict=Depends(require_admin)):
    store=AirMonthlyPdStore()
    try:return {"snapshots":store.list_snapshots(cycle_id=cycle_id,limit=limit)}
    finally:store.close()
