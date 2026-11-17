"""Fail-closed, signed evidence gate for externally activated AIR capabilities.

No environment flag alone can authorize a commercial/research release. An
approval document must be HMAC-signed by an owner-held key and carry current
sign-offs for every mandatory control domain.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_DOMAINS = frozenset({
    "legal", "compliance", "finance", "data_rights", "security", "operations",
})
PROTECTED_CAPABILITIES = frozenset({
    "live_payment_collection",
    "paid_public_research",
    "paid_data_redistribution",
    "personalised_investment_advice",
    "automated_broker_order_execution",
    "live_aws_provisioning",
})


class ReleaseApprovalError(ValueError):
    pass


def _read_secret() -> bytes:
    path = os.getenv("AIR_RELEASE_APPROVAL_HMAC_KEY_FILE", "").strip()
    if not path:
        return b""
    try:
        value = Path(path).read_bytes().strip()
    except OSError:
        return b""
    return value if len(value) >= 32 else b""


def _canonical_payload(document: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in document.items() if key != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_release_document(document: dict[str, Any], secret: bytes) -> str:
    """Helper for controlled offline signing workflows; never exposes key material."""
    if len(secret) < 32:
        raise ReleaseApprovalError("Release approval signing key must be at least 32 bytes")
    return hmac.new(secret, _canonical_payload(document), hashlib.sha256).hexdigest()


def evaluate_release_approval(
    capability: str,
    *,
    document: dict[str, Any] | None = None,
    secret: bytes | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    key = str(capability or "").strip().lower()
    result = {"capability": key, "approved": False, "status": "DENIED", "reasons": []}
    if key not in PROTECTED_CAPABILITIES:
        result["reasons"].append("Capability is not in the protected release registry")
        return result
    if not isinstance(document, dict):
        result["reasons"].append("No release approval document is configured")
        return result
    signing_key = secret if secret is not None else _read_secret()
    if len(signing_key) < 32:
        result["reasons"].append("Owner-held release approval signing key is unavailable")
        return result
    signature = str(document.get("signature") or "").strip().lower()
    expected = sign_release_document(document, signing_key)
    if not signature or not hmac.compare_digest(signature, expected):
        result["reasons"].append("Release approval signature is missing or invalid")
        return result
    if document.get("status") != "APPROVED":
        result["reasons"].append("Release decision is not APPROVED")
    approved = document.get("approved_capabilities")
    if not isinstance(approved, list) or key not in approved:
        result["reasons"].append("Capability is not explicitly included in the approved scope")
    approvals = document.get("approvals")
    if not isinstance(approvals, dict):
        approvals = {}
    for domain in sorted(REQUIRED_DOMAINS):
        item = approvals.get(domain)
        if not isinstance(item, dict) or item.get("status") != "APPROVED" or not str(item.get("reference") or "").strip():
            result["reasons"].append(f"Missing approved evidence reference for {domain}")
    expires = document.get("expires_at")
    try:
        expiry = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if expiry.astimezone(timezone.utc) <= current.astimezone(timezone.utc):
            result["reasons"].append("Release approval has expired")
    except (TypeError, ValueError):
        result["reasons"].append("Release approval expiry is missing or invalid")
    if result["reasons"]:
        return result
    result.update({"approved": True, "status": "APPROVED", "reasons": []})
    return result


def load_release_approval() -> dict[str, Any] | None:
    path = os.getenv("AIR_RELEASE_APPROVALS_FILE", "").strip()
    if not path:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def require_release_approval(capability: str) -> dict[str, Any]:
    """Runtime guard for any future endpoint/job that activates a protected capability."""
    result = evaluate_release_approval(capability, document=load_release_approval())
    if not result["approved"]:
        raise ReleaseApprovalError("; ".join(result["reasons"]))
    return result
