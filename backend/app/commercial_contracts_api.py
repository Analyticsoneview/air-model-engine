"""Customer-scoped API for annual commercial contract lifecycle."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import require_customer
from app.commercial_contracts import CommercialContractStore, ContractConflict\nfrom app.customer_auth_postgres import PostgresAccessStore\nimport os

router = APIRouter(prefix="/api/v1/commercial/contracts", tags=["commercial-contracts"])

@lru_cache(maxsize=1)
def _store() -> CommercialContractStore:
    return CommercialContractStore()

class ContractCreate(BaseModel):
    product_code: str = Field(min_length=1, max_length=64)
    plan_code: str = Field(min_length=1, max_length=64)
    start_date: date
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    amount_minor: int | None = Field(default=None, ge=0)
    grace_days: int = Field(default=0, ge=0, le=90)
    auto_renew: bool = False
    idempotency_key: str = Field(min_length=1, max_length=200)

class ContractTransition(BaseModel):
    to_status: str = Field(min_length=1, max_length=16)
    idempotency_key: str = Field(min_length=1, max_length=200)
    payload: dict = Field(default_factory=dict)

def _tenant_id(customer_id: str) -> str:
    database_url = os.getenv("AIR_CUSTOMER_DATABASE_URL", "").strip()
    if database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        tenant = PostgresAccessStore(database_url=database_url).tenant_for_customer(customer_id)
        if not tenant:
            raise HTTPException(status_code=403, detail="An active tenant membership is required")
        return tenant
    # Local SQLite mode is an isolated individual workspace until Gate 17F-7
    # provisions organisation memberships and seat-level administration.
    return customer_id

@router.post("", status_code=201)
def create_contract(body: ContractCreate, customer_id: str = Depends(require_customer)):
    try:
        return _store().create_contract(
            tenant_id=_tenant_id(customer_id), customer_id=customer_id, actor_id=customer_id,
            **body.model_dump(exclude={"idempotency_key"}),
            idempotency_key=body.idempotency_key,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("")
def list_contracts(customer_id: str = Depends(require_customer)):
    try:
        return {"items": _store().list_contracts(_tenant_id(customer_id))}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Commercial contract store is not ready") from exc

@router.get("/{contract_id}")
def get_contract(contract_id: str, customer_id: str = Depends(require_customer)):
    item = _store().get_contract(_tenant_id(customer_id), contract_id)
    if not item:
        raise HTTPException(status_code=404, detail="Contract not found")
    return item

@router.get("/{contract_id}/events")
def contract_events(contract_id: str, customer_id: str = Depends(require_customer)):
    if not _store().get_contract(customer_id, contract_id):
        raise HTTPException(status_code=404, detail="Contract not found")
    return {"items": _store().events(_tenant_id(customer_id), contract_id)}

@router.post("/{contract_id}/transitions")
def transition_contract(contract_id: str, body: ContractTransition, customer_id: str = Depends(require_customer)):
    try:
        return _store().transition(_tenant_id(customer_id), contract_id, body.to_status, actor_id=customer_id,
                                   idempotency_key=body.idempotency_key, payload=body.payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Contract not found") from exc
    except ContractConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
