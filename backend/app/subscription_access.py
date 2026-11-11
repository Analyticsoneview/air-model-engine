"""Shared subscription entitlement checks for customer strategy APIs."""
from __future__ import annotations

import os

from fastapi import Depends, HTTPException

from app.access_control import access_store
from app.security import require_customer


def is_operator_customer(customer_id: str) -> bool:
    allowed = {
        value.strip()
        for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    }
    if not allowed:
        return False
    mobile = access_store.mobile_for_request_id(customer_id)
    return customer_id in allowed or (mobile or "") in allowed


def active_subscription(customer_id: str) -> dict | None:
    if is_operator_customer(customer_id):
        return {"status": "ACTIVE", "plan_code": "OPERATOR", "expires_at": None}
    return access_store.get_subscription(customer_id)


def require_strategy_subscription(customer_id: str) -> dict:
    subscription = active_subscription(customer_id)
    if not subscription or subscription.get("status") != "ACTIVE":
        raise HTTPException(
            status_code=403,
            detail="An active AIR subscription is required to access this strategy.",
        )
    return subscription


def require_strategy_access(customer_id: str = Depends(require_customer)) -> str:
    """FastAPI dependency that returns the authenticated customer after entitlement validation."""
    require_strategy_subscription(customer_id)
    return customer_id
