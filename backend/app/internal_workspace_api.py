"""Owner-only boundary for AIR's private technical-analysis workspace.

This API is a guardrail foundation, not the workspace UI or a legal exemption.
External distribution and automated execution remain disabled.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, HTTPException

from app.security import require_admin

router = APIRouter(prefix="/api/v1/internal-workspace", tags=["AIR Internal Workspace"])


def require_internal_owner(admin: dict = Depends(require_admin)) -> dict:
    """Require an explicitly configured Super Admin owner identity; fail closed."""
    configured_email = os.getenv("AIR_INTERNAL_OWNER_EMAIL", "").strip().lower()
    if not configured_email:
        raise HTTPException(
            status_code=503,
            detail="Internal workspace owner is not configured",
        )
    if admin.get("role") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Internal owner access is required")
    admin_email = str(admin.get("email") or "").strip().lower()
    if not admin_email or not hmac.compare_digest(admin_email, configured_email):
        raise HTTPException(status_code=403, detail="Internal owner access is required")
    return admin


@router.get("/policy")
async def internal_workspace_policy(
    admin: dict = Depends(require_internal_owner),
) -> dict:
    """Return the active owner-only policy and explicit release restrictions."""
    return {
        "workspace": "AIR_INTERNAL_PERSONAL_ANALYSIS",
        "access": "OWNER_ONLY",
        "owner_admin_id": admin["admin_id"],
        "classification_label": "INTERNAL — NOT FOR DISTRIBUTION",
        "external_distribution": "DISABLED_PENDING_COMPLIANCE_APPROVAL",
        "customer_sharing": False,
        "publication": False,
        "personalised_investment_advice": False,
        "automated_order_execution": False,
        "broker_order_submission": False,
        "permitted_scope": [
            "charts_and_indicators",
            "screeners_and_market_analytics",
            "private_watchlists_and_alerts",
            "user_authored_strategy_analysis",
            "backtests_and_paper_trading",
            "private_research_notes",
        ],
        "limitations": [
            "Owner-only technical analysis; not a service to customers or other persons.",
            "Security-specific recommendations must not be externally distributed until legal classification and required approvals are complete.",
            "Broker/API order workflows require a separate broker and legal assessment.",
            "This policy does not waive market-data licensing, privacy, insider-trading, market-manipulation, tax or cross-border obligations.",
        ],
        "note": "Policy boundary only; workspace screens and data integrations are delivered in a subsequent implementation slice.",
    }
