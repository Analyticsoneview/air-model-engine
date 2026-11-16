"""Customer usage visibility and administrator quota-policy endpoints."""
from __future__ import annotations
from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from app.security import require_customer, require_admin
from app.customer_auth_postgres import PostgresAccessStore
from app.tenant_context import tenant_scope
from app.usage_metering import UsageMeter, METRICS, PERIODS, UnknownUsagePlan

router=APIRouter(prefix="/api/v1/usage",tags=["usage-metering"])

@lru_cache(maxsize=1)
def _meter(): return UsageMeter()

def _store():
    url=PostgresAccessStore._secret_setting("AIR_CUSTOMER_DATABASE_URL")
    return PostgresAccessStore(database_url=url) if url else None

def _tenant(customer_id):
    store=_store()
    if store:
        tenant=store.tenant_for_customer(customer_id)
        if not tenant: raise HTTPException(status_code=403,detail="An active tenant membership is required")
        return tenant
    return customer_id

def _active_plan(customer_id,tenant_id):
    store=_store()
    if store:
        with tenant_scope(tenant_id=tenant_id,customer_id=customer_id):
            with store.engine.connect() as conn:
                row=conn.execute(text("""SELECT plan_code FROM air_commercial_contracts
                    WHERE tenant_id=:tenant AND status='ACTIVE' ORDER BY created_at DESC LIMIT 1"""),
                    {"tenant":tenant_id}).first()
        if row: return str(row[0])
    return "B2C_FREE"

@router.get("/me")
def usage_me(customer_id:str=Depends(require_customer)):
    tenant=_tenant(customer_id)
    try:
        plan=_active_plan(customer_id,tenant)
        return {"tenant_id":tenant,"plan_code":plan,"items":_meter().get_usage(tenant,plan)}
    except UnknownUsagePlan as exc:
        raise HTTPException(status_code=403,detail="No usage allowance exists for this plan") from exc
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(status_code=503,detail="Usage ledger is unavailable") from exc

class QuotaOverride(BaseModel):
    tenant_id:str=Field(min_length=1,max_length=36)
    metric:str
    period:str
    soft_limit:int|None=Field(default=None,ge=0)
    hard_limit:int|None=Field(default=None,ge=0)

@router.put("/admin/quotas")
def update_quota_policy(body:QuotaOverride,admin=Depends(require_admin)):
    if body.metric.lower() not in METRICS or body.period.upper() not in PERIODS:
        raise HTTPException(status_code=422,detail="Unsupported usage metric or period")
    try:
        return _meter().set_quota_override(body.tenant_id,body.metric,body.period,
          soft_limit=body.soft_limit,hard_limit=body.hard_limit,actor_id=admin["admin_id"])
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    except Exception as exc: raise HTTPException(status_code=503,detail="Quota policy store is unavailable") from exc
