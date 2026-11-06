"""Operator-only Dhan research data endpoints for AIR QOC.

These routes expose read-only data APIs. They never place orders and never persist
raw Dhan responses. AIR's research store can retain normalized derived observations.
"""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.brokers.dhan import DhanAPIError, DhanHQClient
from app.brokers.customer_accounts import CustomerAccountDirectory
from app.credential_vault import CredentialVault
from app.security import require_customer
from app.air_qoc_store import AirQocStore
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/air-qoc/dhan", tags=["AIR QOC - Dhan Data"])
_accounts = CustomerAccountDirectory(os.getenv("AIR_ACCOUNT_DB_PATH", "data/customer_accounts.sqlite3"))
_store = AirQocStore()


@lru_cache(maxsize=1)
def _vault() -> CredentialVault:
    return CredentialVault(os.getenv("AIR_CREDENTIAL_DB_PATH", "data/air_credentials.sqlite3"))


def _operator(customer_id: str = Depends(require_customer)) -> str:
    allowed = {x.strip() for x in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",") if x.strip()}
    if customer_id not in allowed:
        raise HTTPException(status_code=403, detail="AIR operator permission is required")
    return customer_id


def _client(customer_id: str, account_id: str) -> DhanHQClient:
    owned = {(a.broker, a.account_id) for a in _accounts.list_for_customer(customer_id)}
    if ("dhan", account_id) not in owned:
        raise HTTPException(status_code=404, detail="Dhan account not found")
    try:
        credentials = _vault().get(customer_id, "dhan", account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dhan credentials not found") from exc
    client_id = credentials.get("client_id", account_id)
    token = credentials.get("access_token")
    if not token:
        raise HTTPException(status_code=422, detail="Dhan access token is missing")
    return DhanHQClient(client_id, token)


class DhanUnderlyingRequest(BaseModel):
    underlying_scrip: int = Field(gt=0)
    underlying_segment: str = Field(min_length=2, max_length=30)


class DhanOptionChainRequest(DhanUnderlyingRequest):
    expiry: str = Field(pattern=r"^\\d{4}-\\d{2}-\\d{2}$")


class DhanExpiredOptionsRequest(BaseModel):
    underlying_scrip: int = Field(gt=0)
    interval: int = Field(default=5, ge=1, le=60)
    instrument: str = Field(pattern="^(OPTIDX|OPTSTK)$")
    expiry_flag: str = Field(pattern="^(WEEK|MONTH)$")
    expiry_code: int = Field(ge=1, le=3)
    strike: str = Field(min_length=1, max_length=12)
    option_type: str = Field(pattern="^(CALL|PUT)$")
    from_date: str = Field(pattern=r"^\\d{4}-\\d{2}-\\d{2}$")
    to_date: str = Field(pattern=r"^\\d{4}-\\d{2}-\\d{2}$")
    required_data: list[str] = Field(default_factory=lambda: [
        "open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot"
    ])


@router.get("/status/{account_id}")
async def dhan_data_status(account_id: str, customer_id: str = Depends(_operator)) -> dict:
    client = _client(customer_id, account_id)
    try:
        profile = await client.profile()
        return {
            "provider": "dhan", "account_id": account_id, "authenticated": True,
            "data_plan": profile.get("dataPlan"),
            "data_validity": profile.get("dataValidity"),
            "token_validity": profile.get("tokenValidity"),
            "active_segments": profile.get("activeSegment"),
            "raw_data_persistence": False,
            "order_placement": "disabled",
        }
    except DhanAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Dhan authentication or entitlement check failed") from exc
    finally:
        await client.close()


@router.post("/expiry-list/{account_id}")
async def dhan_expiry_list(account_id: str, body: DhanUnderlyingRequest,
                           customer_id: str = Depends(_operator)) -> dict:
    client = _client(customer_id, account_id)
    try:
        expiries = await client.option_expiry_list(
            underlying_scrip=body.underlying_scrip,
            underlying_segment=body.underlying_segment,
        )
        return {"provider": "dhan", "account_id": account_id, "expiries": expiries}
    except DhanAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Dhan expiry-list request failed") from exc
    finally:
        await client.close()


@router.post("/option-chain/{account_id}")
async def dhan_option_chain(account_id: str, body: DhanOptionChainRequest,
                            customer_id: str = Depends(_operator)) -> dict:
    client = _client(customer_id, account_id)
    try:
        data = await client.option_chain(
            underlying_scrip=body.underlying_scrip,
            underlying_segment=body.underlying_segment,
            expiry=body.expiry,
        )
        observed_at = datetime.now(timezone.utc).isoformat()
        saved = _store.save_option_chain(
            account_id=account_id, underlying_scrip=body.underlying_scrip,
            underlying_segment=body.underlying_segment, expiry=body.expiry,
            underlying_price=data.get("last_price"), observed_at=observed_at,
            chain=data,
        )
        return {
            "provider": "dhan", "account_id": account_id,
            "underlying_scrip": body.underlying_scrip,
            "underlying_segment": body.underlying_segment,
            "expiry": body.expiry, "observed_at": observed_at,
            "saved_contract_observations": saved, "data": data,
        }
    except DhanAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Dhan option-chain request failed") from exc
    finally:
        await client.close()


@router.post("/expired-options/{account_id}")
async def dhan_expired_options(account_id: str, body: DhanExpiredOptionsRequest,
                               customer_id: str = Depends(_operator)) -> dict:
    client = _client(customer_id, account_id)
    try:
        data = await client.expired_options(
            underlying_scrip=body.underlying_scrip, interval=body.interval,
            instrument=body.instrument, expiry_flag=body.expiry_flag,
            expiry_code=body.expiry_code, strike=body.strike,
            option_type=body.option_type, from_date=body.from_date,
            to_date=body.to_date, required_data=body.required_data,
        )
        return {"provider": "dhan", "account_id": account_id, "data": data,
                "note": "Rolling expired-option history is relative to ATM; it is not a full-universe bhavcopy replacement."}
    except DhanAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Dhan expired-options request failed") from exc
    finally:
        await client.close()



@router.get("/observations/{account_id}")
async def dhan_qoc_observations(account_id: str, limit: int = 500,
                                customer_id: str = Depends(_operator)) -> dict:
    _client_check = _client(customer_id, account_id)
    await _client_check.close()
    rows = _store.latest_observations(account_id=account_id, limit=max(1, min(limit, 2000)))
    return {"provider": "dhan", "account_id": account_id,
            "count": len(rows), "observations": rows,
            "note": "Normalized private snapshots only; no AIR QOC qualification score is inferred from one snapshot."}
