import hashlib
import hmac
import json
import pytest

from app.payment_providers import (
    PaymentProviderError, PaymentWebhookConflict, PaymentWebhookEventStore,
    SandboxPaymentAdapter, get_payment_adapter, verify_webhook_signature,
)


def test_sandbox_adapter_never_returns_live_checkout_url():
    result = SandboxPaymentAdapter().create_checkout_session(
        tenant_id="tenant-a", amount_minor=1299, currency="inr",
        description="AIR annual sandbox test", idempotency_key="checkout-1")
    assert result["mode"] == "sandbox"
    assert result["live_collection"] is False
    assert result["redirect_url"] is None
    assert result["session_reference"].startswith("air_sandbox_")


def test_sandbox_checkout_is_idempotently_referenced():
    adapter = SandboxPaymentAdapter()
    args = dict(tenant_id="tenant-a", amount_minor=1299, currency="INR",
                description="Test", idempotency_key="same-key")
    assert adapter.create_checkout_session(**args)["session_reference"] == adapter.create_checkout_session(**args)["session_reference"]


@pytest.mark.parametrize("mode,live", [("live", "false"), ("sandbox", "true"), ("disabled", "false")])
def test_live_and_unconfigured_payment_modes_fail_closed(monkeypatch, mode, live):
    monkeypatch.setenv("AIR_PAYMENT_MODE", mode)
    monkeypatch.setenv("AIR_PAYMENT_LIVE_ENABLED", live)
    with pytest.raises(PaymentProviderError):
        get_payment_adapter()


def test_webhook_signature_validates_timestamp_and_body():
    secret = b"z" * 32
    body = b'{"event_id":"evt-1","event_type":"payment.succeeded"}'
    timestamp = "1700000000"
    signature = hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    verify_webhook_signature(body, timestamp, signature, secret=secret, now=1700000000)


def test_webhook_rejects_bad_signature_and_stale_timestamp():
    secret = b"z" * 32
    with pytest.raises(PaymentProviderError, match="signature"):
        verify_webhook_signature(b"{}", "1700000000", "bad", secret=secret, now=1700000000)
    with pytest.raises(PaymentProviderError, match="tolerance"):
        verify_webhook_signature(b"{}", "1700000000", "bad", secret=secret, now=1700000400)


def test_webhook_ledger_is_idempotent_and_rejects_payload_replay(tmp_path):
    store = PaymentWebhookEventStore(database_url="", sqlite_path=str(tmp_path / "payments.sqlite3"))
    body = b'{"event_id":"evt-1","event_type":"payment.succeeded"}'
    first = store.record("sandbox", "evt-1", "payment.succeeded", body)
    duplicate = store.record("sandbox", "evt-1", "payment.succeeded", body)
    assert first["status"] == "RECEIVED"
    assert duplicate["status"] == "DUPLICATE"
    with pytest.raises(PaymentWebhookConflict):
        store.record("sandbox", "evt-1", "payment.failed", b'{"event_id":"evt-1","event_type":"payment.failed"}')


def test_webhook_secret_must_be_long_enough(monkeypatch):
    monkeypatch.setenv("AIR_PAYMENT_WEBHOOK_SECRET", "short")
    monkeypatch.delenv("AIR_PAYMENT_WEBHOOK_SECRET_FILE", raising=False)
    from app.payment_providers import webhook_secret
    with pytest.raises(PaymentProviderError):
        webhook_secret()
