"""Customer invoice APIs and restricted operator settlement/reconciliation endpoints."""
from __future__ import annotations

import os
from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import require_customer, require_admin
from app.customer_auth_postgres import PostgresAccessStore
from app.billing import BillingStore, BillingConflict

router=APIRouter(prefix="/api/v1/billing",tags=["billing"])


@lru_cache(maxsize=1)
def _store():
    return BillingStore()


def _tenant(customer_id):
    url=PostgresAccessStore._secret_setting("AIR_CUSTOMER_DATABASE_URL")
    if url:
        store=PostgresAccessStore(database_url=url)
        tenant=store.tenant_for_customer(customer_id)
        if not tenant:
            raise HTTPException(status_code=403,detail="An active tenant membership is required")
        return tenant
    return customer_id


class InvoiceLine(BaseModel):
    description: str = Field(min_length=1,max_length=200)
    quantity: int = Field(gt=0,le=1_000_000)
    unit_amount_minor: int = Field(ge=0)
    tax_breakdown: list[dict] = Field(default_factory=list,max_length=12)


class InvoiceCreate(BaseModel):
    invoice_number: str = Field(min_length=1,max_length=64)
    currency: str = Field(min_length=3,max_length=3)
    lines: list[InvoiceLine] = Field(min_length=1,max_length=100)
    idempotency_key: str = Field(min_length=1,max_length=200)


class InvoiceIssue(BaseModel):
    idempotency_key: str = Field(min_length=1,max_length=200)


class RefundCreate(BaseModel):
    tenant_id: str = Field(min_length=1,max_length=36)
    amount_minor: int = Field(gt=0)
    reason: str = Field(min_length=3,max_length=500)
    idempotency_key: str = Field(min_length=1,max_length=200)


class SettlementCreate(BaseModel):
    tenant_id: str = Field(min_length=1,max_length=36)
    provider: str = Field(min_length=1,max_length=64)
    provider_reference: str = Field(min_length=1,max_length=200)
    currency: str = Field(min_length=3,max_length=3)
    amount_minor: int = Field(ge=0)


class ReconciliationCreate(BaseModel):
    tenant_id: str = Field(min_length=1,max_length=36)
    settlement_id: str = Field(min_length=1,max_length=36)
    expected_amount_minor: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1,max_length=200)
    notes: str = Field(default="",max_length=500)


@router.post("/invoices",status_code=201)
def create_invoice(body:InvoiceCreate,customer_id:str=Depends(require_customer)):
    try:
        return _store().create_invoice(_tenant(customer_id),customer_id,body.invoice_number,body.currency,
            [line.model_dump() for line in body.lines],body.idempotency_key,customer_id)
    except BillingConflict as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    except (ValueError,RuntimeError) as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    except HTTPException: raise
    except Exception as exc: raise HTTPException(status_code=503,detail="Invoice ledger is unavailable") from exc


@router.get("/invoices")
def list_invoices(customer_id:str=Depends(require_customer)):
    try: return {"items":_store().list_invoices(_tenant(customer_id))}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(status_code=503,detail="Invoice ledger is unavailable") from exc


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id:str,customer_id:str=Depends(require_customer)):
    try:
        item=_store().get_invoice(_tenant(customer_id),invoice_id)
        if not item: raise HTTPException(status_code=404,detail="Invoice not found")
        return item
    except HTTPException: raise
    except Exception as exc: raise HTTPException(status_code=503,detail="Invoice ledger is unavailable") from exc


@router.post("/invoices/{invoice_id}/issue")
def issue_invoice(invoice_id:str,body:InvoiceIssue,customer_id:str=Depends(require_customer)):
    try: return _store().issue_invoice(_tenant(customer_id),invoice_id,customer_id,body.idempotency_key)
    except KeyError as exc: raise HTTPException(status_code=404,detail="Invoice not found") from exc
    except BillingConflict as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@router.post("/invoices/{invoice_id}/refunds",status_code=201)
def refund_invoice(invoice_id:str,body:RefundCreate,admin=Depends(require_admin)):
    # Refunds create credit notes only; they do not initiate a money transfer.
    try:
        return _store().refund_invoice(body.tenant_id,invoice_id,
            body.amount_minor,body.reason,admin["admin_id"],body.idempotency_key)
    except KeyError as exc: raise HTTPException(status_code=404,detail="Invoice not found") from exc
    except BillingConflict as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@router.post("/admin/settlements",status_code=201)
def record_settlement(body:SettlementCreate,admin=Depends(require_admin)):
    try:
        return _store().record_settlement(body.tenant_id,body.provider,body.provider_reference,
            body.currency,body.amount_minor)
    except BillingConflict as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@router.post("/admin/reconciliations",status_code=201)
def reconcile_settlement(body:ReconciliationCreate,admin=Depends(require_admin)):
    try:
        return _store().reconcile_settlement(body.tenant_id,body.settlement_id,body.expected_amount_minor,
            admin["admin_id"],body.idempotency_key,body.notes)
    except KeyError as exc: raise HTTPException(status_code=404,detail="Settlement not found") from exc
    except BillingConflict as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@router.get("/admin/audit")
def billing_audit(tenant_id:str,entity_type:str|None=None,entity_id:str|None=None,admin=Depends(require_admin)):
    try: return {"items":_store().audit_events(tenant_id,entity_type,entity_id)}
    except Exception as exc: raise HTTPException(status_code=503,detail="Billing audit ledger is unavailable") from exc
