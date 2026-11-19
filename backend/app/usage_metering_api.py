"""Customer usage visibility and administrator quota-policy endpoints."""
from __future__ import annotations
from functools import lru_cache
from datetime import date
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from app.security import require_customer, require_admin
from app.customer_auth_postgres import PostgresAccessStore
from app.tenant_context import tenant_scope
from app.usage_metering import UsageMeter, METRICS, PERIODS, UnknownUsagePlan, UsageQuotaExceeded

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
                    WHERE tenant_id=:tenant AND status='ACTIVE' AND start_date<=CURRENT_DATE AND end_date>CURRENT_DATE ORDER BY created_at DESC LIMIT 1"""),
                    {"tenant":tenant_id}).first()
        if row: return str(row[0])
    else:
        # Local/self-hosted mode persists contracts in the Gate 17F-2 SQLite ledger.
        from app.commercial_contracts import CommercialContractStore
        today = date.today().isoformat()
        active = [item for item in CommercialContractStore().list_contracts(tenant_id)
                  if item.get("status") == "ACTIVE"
                  and str(item.get("start_date", "")) <= today
                  and today < str(item.get("end_date", ""))]
        if active:
            active.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("contract_id", ""))))
            return str(active[-1]["plan_code"])
    return "B2C_FREE"

def require_usage(metric: str, quantity: int = 1):
    """FastAPI dependency for server-side metering of a protected operation.

    Callers must send a stable Idempotency-Key for retriable operations.
    """
    key_metric = str(metric or "").lower()
    if key_metric not in METRICS or int(quantity) <= 0:
        raise ValueError("A supported metric and positive quantity are required")

    async def enforce_usage(request: Request, customer_id: str = Depends(require_customer)):
        tenant = _tenant(customer_id)
        plan = _active_plan(customer_id, tenant)
        request_key = request.headers.get("Idempotency-Key", "").strip()
        if not request_key:
            raise HTTPException(status_code=400, detail="Idempotency-Key is required for metered operations")
        try:
            return _meter().consume(tenant, customer_id, key_metric, int(quantity), plan_code=plan,
                                    idempotency_key=f"{key_metric}:{request_key}")
        except UsageQuotaExceeded as exc:
            raise HTTPException(status_code=429, detail="Usage quota has been reached") from exc
        except UnknownUsagePlan as exc:
            raise HTTPException(status_code=403, detail="No usage allowance exists for this plan") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Usage enforcement service is unavailable") from exc
    return enforce_usage


def record_licensed_data_download(customer_id: str, customer_type: str, quantity: int,
                                  idempotency_key: str, *, metadata: dict | None = None):
    """Meter delivered bytes only for explicitly classified DATA_PRODUCT customers."""
    kind = str(customer_type or "SERVICE").strip().upper()
    if kind == "SERVICE":
        return {"metered": False, "customer_type": "SERVICE"}
    if kind != "DATA_PRODUCT":
        raise HTTPException(status_code=403, detail="Unknown customer commercial classification")
    amount, key = int(quantity), str(idempotency_key or "").strip()
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Downloaded data size must be positive")
    if not key:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required for data-product downloads")
    try:
        tenant = _tenant(customer_id)
        plan = _active_plan(customer_id, tenant)
        result = _meter().consume(
            tenant, customer_id, "licensed_data_bytes", amount, plan_code=plan,
            idempotency_key=f"licensed_data_bytes:{hashlib.sha256((customer_id + ':' + key).encode('utf-8')).hexdigest()}",
            metadata={"source": "nse_bhavcopy", **(metadata or {})},
        )
        return {"metered": True, "customer_type": "DATA_PRODUCT", **result}
    except UsageQuotaExceeded as exc:
        raise HTTPException(status_code=429, detail="Licensed data download quota has been reached") from exc
    except UnknownUsagePlan as exc:
        raise HTTPException(status_code=403, detail="No licensed-data allowance exists for this plan") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Licensed data usage ledger is unavailable") from exc


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

class UsageAdjustment(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=36)
    customer_id: str = Field(min_length=1, max_length=128)
    metric: str
    quantity: int
    plan_code: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=500)


@router.post("/admin/adjustments")
def adjust_usage(body: UsageAdjustment, admin=Depends(require_admin)):
    try:
        return _meter().adjust_usage(body.tenant_id, body.customer_id, body.metric, body.quantity,
            plan_code=body.plan_code, idempotency_key=body.idempotency_key,
            actor_id=admin["admin_id"], reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Usage adjustment could not be recorded") from exc


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
