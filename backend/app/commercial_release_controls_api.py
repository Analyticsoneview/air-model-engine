"""Administrator-only status endpoint for Gate 17F-10 release approvals."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.security import require_admin
from app.commercial_release_controls import PROTECTED_CAPABILITIES, evaluate_release_approval, load_release_approval

router = APIRouter(prefix="/api/v1/commercial/release-controls", tags=["commercial-release-controls"])


@router.get("/status")
def release_control_status(admin: dict = Depends(require_admin)):
    document = load_release_approval()
    results = {
        capability: evaluate_release_approval(capability, document=document)
        for capability in sorted(PROTECTED_CAPABILITIES)
    }
    return {
        "commercial_release_status": "APPROVED" if all(item["approved"] for item in results.values()) else "BLOCKED",
        "approval_document_configured": document is not None,
        "capabilities": results,
        "note": "This endpoint reports signed evidence status; it does not activate any capability.",
    }
