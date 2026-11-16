"""Owner-only boundary for AIR's private technical-analysis workspace.

This API is a guardrail foundation, not the workspace UI or a legal exemption.
External distribution and automated execution remain disabled.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.internal_workspace_store import InternalWorkspaceStore

from app.security import require_admin

router = APIRouter(prefix="/api/v1/internal-workspace", tags=["AIR Internal Workspace"])
_store: InternalWorkspaceStore | None = None


def get_internal_workspace_store() -> InternalWorkspaceStore:
    global _store
    if _store is None:
        _store = InternalWorkspaceStore()
    return _store


class WatchlistInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    symbols: list[str] = Field(min_length=1, max_length=500)


class ResearchNoteInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    related_symbols: list[str] = Field(default_factory=list, max_length=100)


def _watchlist_payload(body: WatchlistInput) -> dict:
    symbols = list(dict.fromkeys(item.strip().upper() for item in body.symbols if item.strip()))
    if not symbols:
        raise HTTPException(status_code=422, detail="At least one non-empty symbol is required")
    return {"symbols": symbols}


def _note_payload(body: ResearchNoteInput) -> dict:
    return {
        "content": body.content.strip(),
        "tags": list(dict.fromkeys(tag.strip() for tag in body.tags if tag.strip())),
        "related_symbols": list(dict.fromkeys(symbol.strip().upper() for symbol in body.related_symbols if symbol.strip())),
    }


def _owner_id(admin: dict) -> str:
    return str(admin["admin_id"])


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
        "note": "Private persistence API is available; workspace screens and live analysis integrations remain a subsequent implementation slice.",
    }



@router.get("/watchlists")
async def list_internal_watchlists(
    admin: dict = Depends(require_internal_owner),
) -> dict:
    return {"items": get_internal_workspace_store().list_items(_owner_id(admin), "WATCHLIST")}


@router.post("/watchlists", status_code=201)
async def create_internal_watchlist(
    body: WatchlistInput,
    admin: dict = Depends(require_internal_owner),
) -> dict:
    item = get_internal_workspace_store().create_item(
        _owner_id(admin), "WATCHLIST", body.name, _watchlist_payload(body)
    )
    return {"item": item}


@router.put("/watchlists/{item_id}")
async def update_internal_watchlist(
    item_id: str,
    body: WatchlistInput,
    admin: dict = Depends(require_internal_owner),
) -> dict:
    item = get_internal_workspace_store().update_item(
        _owner_id(admin), item_id, "WATCHLIST", body.name, _watchlist_payload(body)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Private watchlist not found")
    return {"item": item}


@router.delete("/watchlists/{item_id}")
async def delete_internal_watchlist(
    item_id: str,
    admin: dict = Depends(require_internal_owner),
) -> dict:
    if not get_internal_workspace_store().delete_item(_owner_id(admin), item_id, "WATCHLIST"):
        raise HTTPException(status_code=404, detail="Private watchlist not found")
    return {"deleted": True, "item_id": item_id}


@router.get("/notes")
async def list_internal_research_notes(
    admin: dict = Depends(require_internal_owner),
) -> dict:
    return {"items": get_internal_workspace_store().list_items(_owner_id(admin), "RESEARCH_NOTE")}


@router.post("/notes", status_code=201)
async def create_internal_research_note(
    body: ResearchNoteInput,
    admin: dict = Depends(require_internal_owner),
) -> dict:
    item = get_internal_workspace_store().create_item(
        _owner_id(admin), "RESEARCH_NOTE", body.title, _note_payload(body)
    )
    return {"item": item}


@router.put("/notes/{item_id}")
async def update_internal_research_note(
    item_id: str,
    body: ResearchNoteInput,
    admin: dict = Depends(require_internal_owner),
) -> dict:
    item = get_internal_workspace_store().update_item(
        _owner_id(admin), item_id, "RESEARCH_NOTE", body.title, _note_payload(body)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Private research note not found")
    return {"item": item}


@router.delete("/notes/{item_id}")
async def delete_internal_research_note(
    item_id: str,
    admin: dict = Depends(require_internal_owner),
) -> dict:
    if not get_internal_workspace_store().delete_item(_owner_id(admin), item_id, "RESEARCH_NOTE"):
        raise HTTPException(status_code=404, detail="Private research note not found")
    return {"deleted": True, "item_id": item_id}


@router.get("/audit")
async def list_internal_workspace_audit(
    limit: int = Query(default=100, ge=1, le=500),
    admin: dict = Depends(require_internal_owner),
) -> dict:
    return {"events": get_internal_workspace_store().audit(_owner_id(admin), limit)}
