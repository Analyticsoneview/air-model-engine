"""AIR commercial catalogue and fail-closed feature entitlement contract.

This module is intentionally provider- and database-neutral. It does not
activate billing, payment collection, regulated research or broker execution.
"""
from __future__ import annotations

from typing import Any

CATALOGUE_VERSION = "2026-11-17.1"

# Public pricing is deliberately unpublished until finance, tax, data rights,
# payment and legal approvals are recorded.
B2C_PLANS: tuple[dict[str, Any], ...] = (
    {
        "code": "B2C_FREE",
        "name": "AIR Free",
        "billing_period": "FREE",
        "currency": None,
        "price_minor": None,
        "price_status": "NOT_PUBLISHED",
        "features": ("dashboard_basic", "watchlists_basic", "charts_basic", "screener_basic",
            "historical_analysis", "historical_strategy_replay"),
    },
    {
        "code": "B2C_ESSENTIAL_ANNUAL",
        "name": "AIR Essential",
        "billing_period": "ANNUAL",
        "currency": None,
        "price_minor": None,
        "price_status": "NOT_PUBLISHED",
        "features": (
            "dashboard_basic", "watchlists_basic", "charts_basic", "screener_basic",
            "historical_strategy_replay",
            "charts_advanced", "screeners_standard", "watchlists_alerts",
            "historical_analysis", "portfolio_monitoring",
        ),
    },
    {
        "code": "B2C_TRADER_ANNUAL",
        "name": "AIR Trader",
        "billing_period": "ANNUAL",
        "currency": None,
        "price_minor": None,
        "price_status": "NOT_PUBLISHED",
        "features": (
            "dashboard_basic", "watchlists_basic", "charts_basic", "screener_basic",
            "historical_strategy_replay",
            "charts_advanced", "screeners_standard", "watchlists_alerts",
            "historical_analysis", "portfolio_monitoring", "options_analytics",
            "oi_volume_analytics", "strategy_builder", "paper_trading",
            "backtesting_standard", "workflow_alerts",
        ),
    },
    {
        "code": "B2C_PROFESSIONAL_ANNUAL",
        "name": "AIR Professional",
        "billing_period": "ANNUAL",
        "currency": None,
        "price_minor": None,
        "price_status": "NOT_PUBLISHED",
        "features": (
            "dashboard_basic", "watchlists_basic", "charts_basic", "screener_basic",
            "historical_strategy_replay",
            "charts_advanced", "screeners_standard", "watchlists_alerts",
            "historical_analysis", "portfolio_monitoring", "options_analytics",
            "oi_volume_analytics", "strategy_builder", "paper_trading",
            "backtesting_standard", "workflow_alerts", "backtesting_advanced",
            "multi_strategy_research", "portfolio_risk_analytics",
            "custom_indicators", "workflow_builder", "extended_research_workspace",
        ),
    },
    {
        "code": "B2C_ELITE_ANNUAL",
        "name": "AIR Elite",
        "billing_period": "ANNUAL",
        "currency": None,
        "price_minor": None,
        "price_status": "NOT_PUBLISHED",
        "features": (
            "dashboard_basic", "watchlists_basic", "charts_basic", "screener_basic",
            "historical_strategy_replay",
            "charts_advanced", "screeners_standard", "watchlists_alerts",
            "historical_analysis", "portfolio_monitoring", "options_analytics",
            "oi_volume_analytics", "strategy_builder", "paper_trading",
            "backtesting_standard", "workflow_alerts", "backtesting_advanced",
            "multi_strategy_research", "portfolio_risk_analytics",
            "custom_indicators", "workflow_builder", "extended_research_workspace",
            "multi_market_analytics", "higher_compute_limits",
            "advanced_workflow_controls", "approved_integrations", "priority_support",
        ),
    },
)

B2B_PLANS: tuple[dict[str, Any], ...] = (
    {
        "code": "B2B_TEAM_ANNUAL",
        "name": "AIR Team",
        "billing_period": "ANNUAL",
        "currency": None,
        "price_minor": None,
        "price_status": "QUOTE_REQUIRED",
        "quote_required": True,
        "features": ("organisation_workspace", "seat_management", "shared_admin", "audit_history"),
    },
    {
        "code": "B2B_BUSINESS_ANNUAL",
        "name": "AIR Business",
        "billing_period": "ANNUAL",
        "currency": None,
        "price_minor": None,
        "price_status": "QUOTE_REQUIRED",
        "quote_required": True,
        "features": (
            "organisation_workspace", "seat_management", "shared_admin", "audit_history",
            "enterprise_reporting", "api_access", "workflow_governance",
            "private_deployment_option",
        ),
    },
    {
        "code": "B2B_INSTITUTIONAL_ANNUAL",
        "name": "AIR Institutional",
        "billing_period": "ANNUAL",
        "currency": None,
        "price_minor": None,
        "price_status": "QUOTE_REQUIRED",
        "quote_required": True,
        "features": (
            "organisation_workspace", "seat_management", "shared_admin", "audit_history",
            "enterprise_reporting", "api_access", "workflow_governance",
            "private_deployment_option", "white_label_option",
            "custom_sla_option", "regional_deployment_option",
        ),
    },
)

# These capabilities remain globally disabled. No subscription tier can grant
# them; a separate legal, broker and release approval path is mandatory.
RESTRICTED_FEATURES = frozenset({
    "personalised_investment_advice",
    "paid_public_security_recommendations",
    "automated_broker_order_execution",
    "broker_order_submission",
    "unlicensed_data_redistribution",
    "customer_research_publication",
})

# Existing DAILY/MONTHLY/SIX_MONTHS/YEARLY subscriptions are retained for
# backwards compatibility while the commercial contract ledger is built.
# They grant only the pre-existing generic strategy-workspace entitlement.
LEGACY_PLAN_CODES = frozenset({"DAILY", "MONTHLY", "SIX_MONTHS", "YEARLY"})
LEGACY_ACTIVE_FEATURES = frozenset({"strategy_workspace"})
OPERATOR_FEATURES = frozenset().union(
    *(frozenset(plan["features"]) for plan in (*B2C_PLANS, *B2B_PLANS))
)


def public_catalogue() -> dict[str, Any]:
    """Return a copy-safe catalogue; prices remain unpublished."""
    return {
        "catalogue_version": CATALOGUE_VERSION,
        "commercial_status": "PRE_LAUNCH",
        "payment_collection_enabled": False,
        "b2c": [dict(plan, features=list(plan["features"])) for plan in B2C_PLANS],
        "b2b": [dict(plan, features=list(plan["features"])) for plan in B2B_PLANS],
        "commercial_rules": {
            "paid_b2c_billing_period": "ANNUAL",
            "b2b_contract_period": "ANNUAL",
            "monthly_paid_checkout_available": False,
            "prices_published": False,
            "taxes_and_market_data_charges": "To be confirmed per country and provider entitlement",
        },
        "globally_disabled_features": sorted(RESTRICTED_FEATURES),
    }


def resolve_entitlements(subscription: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve a customer's effective feature set; unknown/inactive plans fail closed."""
    if not subscription or subscription.get("status") != "ACTIVE":
        return {
            "plan_code": "B2C_FREE",
            "features": list(B2C_PLANS[0]["features"]),
            "restricted_features": sorted(RESTRICTED_FEATURES),
            "entitlement_status": "FREE",
        }

    code = str(subscription.get("plan_code") or "").upper()
    if code == "OPERATOR":
        features = OPERATOR_FEATURES
        status = "OPERATOR_OVERRIDE"
        catalogue_code = None
    elif code in LEGACY_PLAN_CODES:
        features = LEGACY_ACTIVE_FEATURES
        status = "LEGACY_ACTIVE"
        catalogue_code = None
    else:
        plan = next((p for p in (*B2C_PLANS, *B2B_PLANS) if p["code"] == code), None)
        if plan is None:
            return {
                "plan_code": code or "UNKNOWN",
                "features": [],
                "restricted_features": sorted(RESTRICTED_FEATURES),
                "entitlement_status": "UNKNOWN_PLAN_DENIED",
            }
        features = frozenset(plan["features"])
        status = "ACTIVE"
        catalogue_code = code

    return {
        "plan_code": code,
        "catalogue_plan": catalogue_code,
        "features": sorted(features),
        "restricted_features": sorted(RESTRICTED_FEATURES),
        "entitlement_status": status,
    }


def has_entitlement(subscription: dict[str, Any] | None, feature: str) -> bool:
    """Return false for restricted, unknown, inactive or ungranted features."""
    key = str(feature or "").strip().lower()
    if not key or key in RESTRICTED_FEATURES:
        return False
    resolved = resolve_entitlements(subscription)
    return key in resolved["features"]


def catalogue_plan(code: str) -> dict[str, Any] | None:
    key = str(code or "").strip().upper()
    plan = next((p for p in (*B2C_PLANS, *B2B_PLANS) if p["code"] == key), None)
    return dict(plan, features=list(plan["features"])) if plan else None
