"""Sandbox-only checkout and signed provider webhook endpoints (Gate 17F-4)."""
from __future__ import annotations

from functools import lru_cache
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.security import require_customer
from app.payment_providers import (
    PaymentConfigurationError, PaymentProviderError, PaymentWebhookConflict, PaymentWebhookEventStore,
    get_payment_adapter, verify_webhook_signature, webhook_secret,
)

router = APIRouter(prefix="/api/v1/payments", tags=["payments-sandbox"])


@lru_cache(maxsize=1)
def _events() -> PaymentWebhookEventStore:
    return PaymentWebhookEventStore()


class SandboxCheckoutRequest(BaseModel):
    amount_minor: int = Field(gt=0, le=100_000_000)
    currency: str = Field(min_length=3, max_length=3)
    description: str = Field(min_length=1, max_length=200)


@router.post("/sandbox/checkout", status_code=201)
def create_sandbox_checkout(
    body: SandboxCheckoutRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    customer_id: str = Depends(require_customer),
):
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    try:
        return get_payment_adapter().create_checkout_session(
            tenant_id=customer_id, amount_minor=body.amount_minor,
            currency=body.currency, description=body.description,
            idempotency_key=idempotency_key.strip(),
        )
    except PaymentProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/webhooks/{provider}")
async def receive_payment_webhook(
    provider: str,
    request: Request,
    x_air_timestamp: str | None = Header(default=None, alias="X-AIR-Timestamp"),
    x_air_signature: str | None = Header(default=None, alias="X-AIR-Signature"),
):
    if provider.strip().lower() != "sandbox":
        raise HTTPException(status_code=404, detail="Payment provider is not enabled")
    raw_body = await request.body()
    if len(raw_body) > 256_000:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    if not x_air_timestamp or not x_air_signature:
        raise HTTPException(status_code=401, detail="Signed webhook headers are required")
    try:
        verify_webhook_signature(raw_body, x_air_timestamp, x_air_signature, secret=webhook_secret())
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise PaymentProviderError("Webhook body must be a JSON object")
        event_id = payload.get("event_id")
        event_type = payload.get("event_type")
        return _events().record(provider, event_id, event_type, raw_body)
    except PaymentConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PaymentWebhookConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (PaymentProviderError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Payment webhook ledger is unavailable") from exc
