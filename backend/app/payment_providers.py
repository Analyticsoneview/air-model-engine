"""Provider-neutral sandbox payment adapter and signed webhook ledger.

Gate 17F-4 deliberately has no live payment implementation or network client.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


class PaymentProviderError(ValueError):
    pass


class PaymentConfigurationError(PaymentProviderError):
    """Required payment verification configuration is missing or invalid."""


class PaymentWebhookConflict(PaymentProviderError):
    pass


class PaymentProviderAdapter(ABC):
    provider_name: str

    @abstractmethod
    def create_checkout_session(self, *, tenant_id: str, amount_minor: int,
                                 currency: str, description: str,
                                 idempotency_key: str) -> dict:
        raise NotImplementedError


class SandboxPaymentAdapter(PaymentProviderAdapter):
    """Deterministic, offline sandbox adapter; it never contacts a payment vendor."""

    provider_name = "sandbox"

    def create_checkout_session(self, *, tenant_id: str, amount_minor: int,
                                currency: str, description: str,
                                idempotency_key: str) -> dict:
        if not tenant_id or not idempotency_key or len(idempotency_key) > 200:
            raise PaymentProviderError("Tenant and bounded idempotency key are required")
        if int(amount_minor) <= 0:
            raise PaymentProviderError("amount_minor must be positive")
        code = str(currency).upper()
        if len(code) != 3 or not code.isalpha():
            raise PaymentProviderError("currency must be a three-letter ISO code")
        if not description.strip() or len(description) > 200:
            raise PaymentProviderError("A bounded description is required")
        digest = hashlib.sha256(f"{tenant_id}:{idempotency_key}".encode()).hexdigest()[:24]
        return {
            "provider": self.provider_name,
            "mode": "sandbox",
            "status": "CREATED",
            "session_reference": f"air_sandbox_{digest}",
            "amount_minor": int(amount_minor),
            "currency": code,
            "description": description,
            "redirect_url": None,
            "live_collection": False,
        }


def get_payment_adapter() -> PaymentProviderAdapter:
    mode = os.getenv("AIR_PAYMENT_MODE", "disabled").strip().lower()
    if os.getenv("AIR_PAYMENT_LIVE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        raise PaymentProviderError("Live payment collection is disabled by Gate 17F-4")
    if mode != "sandbox":
        raise PaymentProviderError("Payment provider is disabled; explicitly enable sandbox mode")
    provider = os.getenv("AIR_PAYMENT_PROVIDER", "sandbox").strip().lower()
    if provider != "sandbox":
        raise PaymentProviderError("No live or external payment provider is enabled in Gate 17F-4")
    return SandboxPaymentAdapter()


def webhook_secret() -> bytes:
    secret_file = os.getenv("AIR_PAYMENT_WEBHOOK_SECRET_FILE", "").strip()
    secret = Path(secret_file).read_bytes().strip() if secret_file else os.getenv("AIR_PAYMENT_WEBHOOK_SECRET", "").encode()
    if len(secret) < 32:
        raise PaymentConfigurationError("A webhook secret of at least 32 bytes must be configured")
    return secret


def verify_webhook_signature(raw_body: bytes, timestamp_header: str,
                             signature_header: str, *, secret: bytes,
                             now: int | None = None, tolerance_seconds: int = 300) -> None:
    try:
        timestamp = int(timestamp_header)
    except (TypeError, ValueError) as exc:
        raise PaymentProviderError("Invalid webhook timestamp") from exc
    current = int(time.time()) if now is None else int(now)
    if abs(current - timestamp) > tolerance_seconds:
        raise PaymentProviderError("Webhook timestamp is outside the allowed tolerance")
    supplied = signature_header.strip()
    if supplied.startswith("v1="):
        supplied = supplied[3:]
    expected = hmac.new(secret, str(timestamp).encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise PaymentProviderError("Invalid webhook signature")


class PaymentWebhookEventStore:
    """Append-only receipt ledger; payload contents are not retained."""

    def __init__(self, database_url: str | None = None, sqlite_path: str | None = None):
        self.database_url = database_url if database_url is not None else os.getenv("AIR_CUSTOMER_DATABASE_URL", "")
        self.sqlite_path = sqlite_path or os.getenv("AIR_PAYMENT_DB_PATH", "data/payment_events.sqlite3")
        self.engine = None
        if self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            self.engine = create_engine(self.database_url, pool_pre_ping=True, future=True)
            with self.engine.connect() as conn:
                if not conn.execute(text("SELECT to_regclass('public.air_payment_webhook_events')")).scalar():
                    raise RuntimeError("Payment webhook migration 0024 must be applied before use")
        elif self.database_url:
            raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must use PostgreSQL")
        else:
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.sqlite_path) as db:
                db.execute("""CREATE TABLE IF NOT EXISTS air_payment_webhook_events (
                    provider TEXT NOT NULL, event_id TEXT NOT NULL, event_type TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, status TEXT NOT NULL CHECK(status='RECEIVED'),
                    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(provider,event_id))""")

    def record(self, provider: str, event_id: str, event_type: str, raw_body: bytes) -> dict:
        provider = str(provider).strip().lower()
        event_id = str(event_id).strip()
        event_type = str(event_type).strip()
        if not provider or len(provider) > 64 or not event_id or len(event_id) > 200:
            raise PaymentProviderError("Provider and bounded event ID are required")
        if not event_type or len(event_type) > 100:
            raise PaymentProviderError("A bounded event type is required")
        digest = hashlib.sha256(raw_body).hexdigest()
        if self.engine:
            try:
                with self.engine.begin() as conn:
                    row = conn.execute(text("""SELECT payload_sha256 FROM air_payment_webhook_events
                        WHERE provider=:provider AND event_id=:event_id"""),
                        {"provider": provider, "event_id": event_id}).first()
                    if row:
                        if row[0] != digest:
                            raise PaymentWebhookConflict("Webhook event ID was replayed with a different payload")
                        return {"provider": provider, "event_id": event_id, "status": "DUPLICATE"}
                    conn.execute(text("""INSERT INTO air_payment_webhook_events
                        (provider,event_id,event_type,payload_sha256,status)
                        VALUES (:provider,:event_id,:event_type,:digest,'RECEIVED')"""),
                        {"provider": provider, "event_id": event_id, "event_type": event_type, "digest": digest})
            except IntegrityError:
                # A concurrent delivery may win the unique-key insert after our read.
                with self.engine.connect() as conn:
                    row = conn.execute(text("""SELECT payload_sha256 FROM air_payment_webhook_events
                        WHERE provider=:provider AND event_id=:event_id"""),
                        {"provider": provider, "event_id": event_id}).first()
                if not row or row[0] != digest:
                    raise PaymentWebhookConflict("Webhook event ID was concurrently reused with a different payload")
                return {"provider": provider, "event_id": event_id, "status": "DUPLICATE"}
        else:
            with sqlite3.connect(self.sqlite_path, timeout=20) as db:
                row = db.execute("""SELECT payload_sha256 FROM air_payment_webhook_events
                    WHERE provider=? AND event_id=?""", (provider, event_id)).fetchone()
                if row:
                    if row[0] != digest:
                        raise PaymentWebhookConflict("Webhook event ID was replayed with a different payload")
                    return {"provider": provider, "event_id": event_id, "status": "DUPLICATE"}
                try:
                    db.execute("""INSERT INTO air_payment_webhook_events
                        (provider,event_id,event_type,payload_sha256,status)
                        VALUES (?,?,?,?,'RECEIVED')""", (provider, event_id, event_type, digest))
                except sqlite3.IntegrityError:
                    row = db.execute("""SELECT payload_sha256 FROM air_payment_webhook_events
                        WHERE provider=? AND event_id=?""", (provider, event_id)).fetchone()
                    if not row or row[0] != digest:
                        raise PaymentWebhookConflict("Webhook event ID was concurrently reused with a different payload")
                    return {"provider": provider, "event_id": event_id, "status": "DUPLICATE"}
        return {"provider": provider, "event_id": event_id, "status": "RECEIVED"}
