from datetime import datetime, timezone, timedelta

from app.commercial_release_controls import (
    PROTECTED_CAPABILITIES,
    REQUIRED_DOMAINS,
    evaluate_release_approval,
    sign_release_document,
)


def _approved_document(secret: bytes, *, capability: str = "live_payment_collection"):
    document = {
        "schema_version": 1,
        "release_id": "AIR-2026-11-17-RC1",
        "status": "APPROVED",
        "approved_capabilities": [capability],
        "expires_at": (datetime(2030, 1, 1, tzinfo=timezone.utc)).isoformat(),
        "approvals": {
            domain: {"status": "APPROVED", "reference": f"evidence/{domain}/signed-approval.pdf"}
            for domain in REQUIRED_DOMAINS
        },
    }
    document["signature"] = sign_release_document(document, secret)
    return document


def test_protected_capabilities_are_explicit_and_finite():
    assert "live_payment_collection" in PROTECTED_CAPABILITIES
    assert "paid_public_research" in PROTECTED_CAPABILITIES
    assert "automated_broker_order_execution" in PROTECTED_CAPABILITIES


def test_missing_release_document_fails_closed():
    result = evaluate_release_approval("live_payment_collection", document=None, secret=b"x" * 32)
    assert result["approved"] is False
    assert result["status"] == "DENIED"


def test_missing_signing_key_fails_closed():
    result = evaluate_release_approval("live_payment_collection", document={}, secret=b"")
    assert result["approved"] is False
    assert any("signing key" in reason for reason in result["reasons"])


def test_valid_signed_document_approves_only_explicit_capability():
    secret = b"owner-controlled-test-key-material-32bytes"
    document = _approved_document(secret)
    result = evaluate_release_approval("live_payment_collection", document=document, secret=secret)
    assert result["approved"] is True
    other = evaluate_release_approval("paid_public_research", document=document, secret=secret)
    assert other["approved"] is False


def test_modified_document_invalidates_signature():
    secret = b"owner-controlled-test-key-material-32bytes"
    document = _approved_document(secret)
    document["approved_capabilities"].append("paid_public_research")
    result = evaluate_release_approval("live_payment_collection", document=document, secret=secret)
    assert result["approved"] is False
    assert any("signature" in reason for reason in result["reasons"])


def test_each_mandatory_approval_domain_requires_reference():
    secret = b"owner-controlled-test-key-material-32bytes"
    document = _approved_document(secret)
    document["approvals"]["data_rights"] = {"status": "APPROVED", "reference": ""}
    document["signature"] = sign_release_document(document, secret)
    result = evaluate_release_approval("live_payment_collection", document=document, secret=secret)
    assert result["approved"] is False
    assert any("data_rights" in reason for reason in result["reasons"])


def test_expired_release_document_is_denied():
    secret = b"owner-controlled-test-key-material-32bytes"
    document = _approved_document(secret)
    result = evaluate_release_approval(
        "live_payment_collection",
        document=document,
        secret=secret,
        now=datetime(2031, 1, 1, tzinfo=timezone.utc),
    )
    assert result["approved"] is False
    assert any("expired" in reason for reason in result["reasons"])


def test_unknown_capability_is_denied():
    result = evaluate_release_approval("arbitrary_feature", document={}, secret=b"x" * 32)
    assert result["approved"] is False
    assert any("not in the protected" in reason for reason in result["reasons"])
