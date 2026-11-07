"""Customer-authenticated API for the two AIR ORB sessions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.market_data.customer_runtime import get_customer_market_data_service, get_customer_market_data_status
from app.market_data.contracts import MarketInstrument
from app.orb_strategy import OrbSignalEngine
from app.security import require_customer

router = APIRouter(prefix="/api/v1/orb", tags=["AIR ORB"])
_engines: dict[str, OrbSignalEngine] = {}
_attached_hubs: set[int] = set()


class OrbSubscribeRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=30)


async def _engine_for(customer_id: str) -> tuple[OrbSignalEngine, object]:
    try:
        service = await get_customer_market_data_service(customer_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Market-data service unavailable: {type(exc).__name__}") from exc
    engine = _engines.setdefault(customer_id, OrbSignalEngine())
    hub = service.hub
    if id(hub) not in _attached_hubs:
        hub.add_listener(engine.on_tick)
        _attached_hubs.add(id(hub))
    return engine, service


@router.get("/status")
async def orb_status(customer_id: str = Depends(require_customer)) -> dict:
    engine, _service = await _engine_for(customer_id)
    try:
        source = await get_customer_market_data_status(customer_id)
    except Exception:
        source = {"effective_source": "UNKNOWN", "connection_status": "unavailable"}
    return {**engine.snapshot(), "market_data_source": source,
            "execution": "SIGNAL_ONLY_NO_ORDER_PLACEMENT"}


@router.post("/subscribe")
async def orb_subscribe(body: OrbSubscribeRequest,
                        customer_id: str = Depends(require_customer)) -> dict:
    symbols = list(dict.fromkeys(str(value).strip().upper() for value in body.symbols if str(value).strip()))
    if not symbols:
        raise HTTPException(status_code=422, detail="At least one NSE symbol is required")
    engine, service = await _engine_for(customer_id)
    instruments: list[MarketInstrument] = []
    missing = []
    for symbol in symbols:
        try:
            matches = await service.search_instruments(symbol, limit=500)
            exact = [item for item in matches
                     if item.symbol.upper() == symbol
                     or (item.underlying_symbol or "").upper() == symbol]
            if not exact:
                missing.append(symbol)
                continue
            # Prefer cash/index underlying instruments; do not subscribe option chains here.
            chosen = next((item for item in exact
                           if not item.expiry and item.strike is None
                           and (item.instrument_type or "").upper() not in {"OPTSTK", "OPTIDX"}), exact[0])
            instruments.append(chosen)
        except Exception:
            missing.append(symbol)
    if not instruments:
        raise HTTPException(status_code=422, detail=f"No exact instruments found for: {', '.join(missing)}")
    try:
        result = await service.subscribe(instruments)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Live subscription failed: {type(exc).__name__}") from exc
    engine.add_symbols([item.symbol for item in instruments])
    return {"status": "subscribed", "provider": result.get("provider"),
            "account_id": result.get("account_id"),
            "symbols": [item.symbol for item in instruments],
            "not_found": missing,
            "note": "Signals only. AIR does not place orders."}
