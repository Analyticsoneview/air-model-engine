"""Customer onboarding endpoints and admin-controlled paid lifecycle actions."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from contextlib import nullcontext
from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import require_customer, require_admin
from app.customer_auth_postgres import PostgresAccessStore
from app.onboarding import OnboardingStore, OnboardingConflict, REQUIRED_CONSENTS
from app.commercial_contracts import CommercialContractStore, ContractConflict
from app.commercial_catalogue import catalogue_plan


router = APIRouter(prefix="/api/v1/onboarding", tags=["customer-onboarding"])


@lru_cache(maxsize=1)
def _store():
    return OnboardingStore()


@lru_cache(maxsize=1)
def _contracts():
    return CommercialContractStore()


def _contract_scope(tenant_id, customer_id=None, admin=False):
    if os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE"):
        from app.tenant_context import tenant_scope
        return tenant_scope(tenant_id=tenant_id, customer_id=customer_id, is_admin=admin)
    return nullcontext()


def _tenant(customer_id):
    url = PostgresAccessStore._secret_setting("AIR_CUSTOMER_DATABASE_URL")
    if url:
        tenant = PostgresAccessStore(database_url=url).tenant_for_customer(customer_id)
        if not tenant:
            raise HTTPException(status_code=403, detail="An active tenant membership is required")
        return tenant
    return customer_id


class ConsentItem(BaseModel):
    consent_type: str = Field(min_length=1, max_length=32)
    document_version: str = Field(min_length=1, max_length=64)
    accepted: bool


class TrialRequest(BaseModel):
    product_code: str = Field(min_length=1, max_length=64)
    plan_code: str = Field(min_length=1, max_length=64)
    consents: list[ConsentItem] = Field(min_length=3, max_length=4)
    idempotency_key: str = Field(min_length=1, max_length=200)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


class AdminLifecycleAction(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=36)
    customer_id: str = Field(min_length=1, max_length=128)
    onboarding_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(min_length=1, max_length=200)
    approval_reference: str = Field(min_length=3, max_length=200)
    reason: str = Field(default="", max_length=500)


@router.get("/me")
def onboarding_me(customer_id: str = Depends(require_customer)):
    tenant = _tenant(customer_id)
    item = _store().get(tenant, customer_id)
    if item and item["status"] == "TRIAL" and item.get("trial_ends_at"):
        ends = item["trial_ends_at"]
        if isinstance(ends, str):
            ends = datetime.fromisoformat(ends.replace("Z", "+00:00"))
        if ends <= datetime.now(timezone.utc):
            try:
                _store().transition(tenant, customer_id, item["onboarding_id"], "EXPIRED",
                                    customer_id, "trial-expire:" + item["onboarding_id"],
                                    {"reason": "trial_period_elapsed"})
            except OnboardingConflict:
                pass
            item = _store().get(tenant, customer_id)
    return {"onboarding": item, "consents": _store().consents(tenant, customer_id)}


@router.post("/trial", status_code=201)
def start_trial(body: TrialRequest, customer_id: str = Depends(require_customer)):
    tenant = _tenant(customer_id)
    plan = catalogue_plan(body.plan_code)
    if not plan or plan["code"].startswith("B2B_") or plan["billing_period"] != "ANNUAL":
        raise HTTPException(status_code=422, detail="A supported annual B2C plan is required for a trial")
    try:
        consents = [item.model_dump() for item in body.consents]
        _store().record_consents(tenant, customer_id, consents, body.idempotency_key)
        item = _store().create(tenant, customer_id, body.product_code, plan["code"],
                               body.idempotency_key, customer_id)
        if item["status"] == "PENDING":
            with _contract_scope(tenant, customer_id):
                contract = _contracts().create_contract(tenant_id=tenant, customer_id=customer_id,
                    product_code=body.product_code, plan_code=plan["code"], start_date=date.today(),
                    actor_id=customer_id, idempotency_key="onboarding-contract:" + body.idempotency_key)
                contract = _contracts().transition(tenant, contract["contract_id"], "TRIAL",
                    actor_id=customer_id, idempotency_key="onboarding-contract-trial:" + body.idempotency_key,
                    payload={"onboarding_id": item["onboarding_id"]})
            item = _store().transition(tenant, customer_id, item["onboarding_id"], "TRIAL",
                customer_id, "trial-start:" + body.idempotency_key,
                {"contract_id": contract["contract_id"], "trial_days": 14}, trial_days=14)
            item = _store().attach_contract(tenant, customer_id, item["onboarding_id"], contract["contract_id"])
        return {"onboarding": item, "trial_days": 14, "payment_collection_enabled": False}
    except OnboardingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContractConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/cancel")
def cancel_onboarding(body: CancelRequest, customer_id: str = Depends(require_customer)):
    tenant = _tenant(customer_id)
    item = _store().get(tenant, customer_id)
    if not item:
        raise HTTPException(status_code=404, detail="Onboarding record not found")
    try:
        updated = _store().transition(tenant, customer_id, item["onboarding_id"], "CANCELLED",
            customer_id, body.idempotency_key, {"reason": body.reason})
        contract_id = item.get("contract_id")
        if contract_id:
            with _contract_scope(tenant, customer_id):
                contract = _contracts().get_contract(tenant, contract_id)
                if contract and contract["status"] in {"TRIAL", "ACTIVE"}:
                    _contracts().transition(tenant, contract_id, "CANCELLED", actor_id=customer_id,
                        idempotency_key="onboarding-cancel-contract:" + body.idempotency_key,
                        payload={"reason": body.reason})
        return {"onboarding": updated, "money_movement": False}
    except OnboardingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/events")
def onboarding_events(customer_id: str = Depends(require_customer)):
    tenant = _tenant(customer_id)
    item = _store().get(tenant, customer_id)
    if not item:
        return {"items": []}
    return {"items": _store().events(tenant, customer_id, item["onboarding_id"])}


@router.post("/admin/activate")
def admin_activate(body: AdminLifecycleAction, admin=Depends(require_admin)):
    try:
        item = _store().get(body.tenant_id, body.customer_id)
        if not item or item["onboarding_id"] != body.onboarding_id:
            raise HTTPException(status_code=404, detail="Onboarding record not found")
        if item["status"] not in {"TRIAL", "PENDING"}:
            raise HTTPException(status_code=409, detail="Only pending or trial onboarding can be activated")
        if item["status"] == "PENDING":
            raise HTTPException(status_code=409, detail="Trial consent and trial start are required before activation")
        contract_id = item.get("contract_id")
        if not contract_id:
            raise HTTPException(status_code=409, detail="Commercial contract is missing")
        with _contract_scope(body.tenant_id, body.customer_id, admin=True):
            _contracts().transition(body.tenant_id, contract_id, "ACTIVE", actor_id=admin["admin_id"],
                idempotency_key="onboarding-activate-contract:" + body.idempotency_key,
                payload={"approval_reference": body.approval_reference, "reason": body.reason})
        updated = _store().transition(body.tenant_id, body.customer_id, body.onboarding_id, "ACTIVE",
            admin["admin_id"], body.idempotency_key,
            {"approval_reference": body.approval_reference, "reason": body.reason})
        return {"onboarding": updated, "payment_collection_enabled": False}
    except (OnboardingConflict, ContractConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Onboarding record not found") from exc


@router.post("/admin/renew")
def admin_renew(body: AdminLifecycleAction, admin=Depends(require_admin)):
    try:
        old = _store().get(body.tenant_id, body.customer_id)
        if not old or old["onboarding_id"] != body.onboarding_id:
            raise HTTPException(status_code=404, detail="Onboarding record not found")
        if old["status"] != "EXPIRED":
            raise HTTPException(status_code=409, detail="Only an expired customer contract can be renewed")
        key = "renewal:" + body.idempotency_key
        with _contract_scope(body.tenant_id, body.customer_id, admin=True):
            contract = _contracts().create_contract(tenant_id=body.tenant_id, customer_id=body.customer_id,
                product_code=old["product_code"], plan_code=old["plan_code"], start_date=date.today(),
                actor_id=admin["admin_id"], idempotency_key=key)
            contract = _contracts().transition(body.tenant_id, contract["contract_id"], "ACTIVE",
                actor_id=admin["admin_id"], idempotency_key=key + ":activate",
                payload={"approval_reference": body.approval_reference, "reason": body.reason})
        new = _store().create(body.tenant_id, body.customer_id, old["product_code"], old["plan_code"],
            "onboarding-renewal:" + body.idempotency_key, admin["admin_id"])
        new = _store().transition(body.tenant_id, body.customer_id, new["onboarding_id"], "ACTIVE",
            admin["admin_id"], body.idempotency_key,
            {"approval_reference": body.approval_reference, "renewal": True})
        new = _store().attach_contract(body.tenant_id, body.customer_id, new["onboarding_id"], contract["contract_id"])
        return {"onboarding": new, "payment_collection_enabled": False}
    except (OnboardingConflict, ContractConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/admin/expire-due")
def admin_expire_due(body: AdminLifecycleAction, admin=Depends(require_admin)):
    item = _store().get(body.tenant_id, body.customer_id)
    if not item or item["onboarding_id"] != body.onboarding_id:
        raise HTTPException(status_code=404, detail="Onboarding record not found")
    if item["status"] != "TRIAL":
        raise HTTPException(status_code=409, detail="Only trials can expire")
    ends = item["trial_ends_at"]
    if isinstance(ends, str):
        ends = datetime.fromisoformat(ends.replace("Z", "+00:00"))
    if ends > datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Trial period has not ended")
    updated = _store().transition(body.tenant_id, body.customer_id, body.onboarding_id, "EXPIRED",
        admin["admin_id"], body.idempotency_key, {"reason": "trial_period_elapsed"})
    contract_id = item.get("contract_id")
    if contract_id:
        with _contract_scope(body.tenant_id, body.customer_id, admin=True):
            _contracts().transition(body.tenant_id, contract_id, "EXPIRED", actor_id=admin["admin_id"],
                idempotency_key="onboarding-expire-contract:" + body.idempotency_key)
    return {"onboarding": updated}
