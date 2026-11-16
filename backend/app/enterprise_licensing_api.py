"""Operator-protected enterprise licensing and deployment binding API."""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import require_customer
from app.main import require_air_operator
from app.tenant_context import current_customer_id
from app.enterprise_licensing import EnterpriseLicenseStore, EnterpriseLicenseError

router = APIRouter(prefix="/api/v1/enterprise-licensing", tags=["enterprise-licensing"])


@lru_cache(maxsize=1)
def _store():
    return EnterpriseLicenseStore()


class DeploymentRegistration(BaseModel):
    instance_key: str = Field(min_length=1, max_length=128)
    profile_id: str = Field(min_length=1, max_length=64)
    fingerprint: str = Field(min_length=16, max_length=4096)
    label: str = Field(default="AIR deployment", max_length=160)


class LicenseIssue(BaseModel):
    contract_id: str = Field(min_length=1, max_length=36)
    deployment_id: str = Field(min_length=1, max_length=36)
    max_seats: int = Field(ge=1, le=100000)
    max_deployments: int = Field(default=1, ge=1, le=100)
    valid_from: date
    valid_until: date
    grace_until: date | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)


def _actor():
    actor = current_customer_id()
    if not actor:
        raise HTTPException(status_code=403, detail="Authenticated operator identity is unavailable")
    return actor


@router.post("/deployments/register")
def register_deployment(body: DeploymentRegistration, actor: str = Depends(require_air_operator)):
    try:
        return _store().register_deployment(
            tenant_id=actor, instance_key=body.instance_key, profile_id=body.profile_id,
            fingerprint=body.fingerprint, label=body.label,
        )
    except EnterpriseLicenseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/licenses/issue")
def issue_enterprise_license(body: LicenseIssue, actor: str = Depends(require_air_operator)):
    private_key = os.getenv("AIR_LICENSE_SIGNING_PRIVATE_KEY", "").strip()
    if not private_key:
        raise HTTPException(status_code=503, detail="Enterprise licence issuer signing key is not configured")
    try:
        return _store().issue_and_bind(
            tenant_id=actor, contract_id=body.contract_id, deployment_id=body.deployment_id,
            max_seats=body.max_seats, max_deployments=body.max_deployments,
            valid_from=body.valid_from, valid_until=body.valid_until,
            grace_until=body.grace_until, actor_id=actor,
            idempotency_key=body.idempotency_key, private_key_b64=private_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EnterpriseLicenseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/licenses/{license_id}/revoke")
def revoke_enterprise_license(
    license_id: str, idempotency_key: str = Depends(lambda: None),
    actor: str = Depends(require_air_operator),
):
    try:
        _store().revoke(actor, license_id, actor, str(idempotency_key or "revoke:" + license_id))
        return {"license_id": license_id, "status": "REVOKED"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/deployments/{deployment_id}/status")
def deployment_license_status(deployment_id: str, actor: str = Depends(require_air_operator)):
    row = _store().active_license(actor, deployment_id)
    if not row:
        return {"deployment_id": deployment_id, "license_status": "UNLICENSED", "features": []}
    return {"deployment_id": deployment_id, "license_id": row["license_id"],
            "license_status": row["status"], "plan_code": row["plan_code"],
            "max_seats": row["max_seats"], "features": row["features"]}


@router.post("/licenses/verify")
def verify_enterprise_license(body: dict, actor: str = Depends(require_customer)):
    from app.enterprise_licensing import verify_license
    public_key = os.getenv("AIR_LICENSE_VERIFY_PUBLIC_KEY", "").strip()
    if not public_key:
        raise HTTPException(status_code=503, detail="Enterprise licence verification key is not configured")
    try:
        payload = verify_license(
            body.get("license_token", ""), public_key, tenant_id=body.get("tenant_id", ""),
            deployment_id=body.get("deployment_id", ""), profile_id=body.get("profile_id", ""),
            fingerprint=body.get("fingerprint", ""),
        )
        if payload["tenant_id"] != actor:
            raise EnterpriseLicenseError("Licence organisation does not match authenticated organisation")
        return {"valid": True, "license": payload}
    except EnterpriseLicenseError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
