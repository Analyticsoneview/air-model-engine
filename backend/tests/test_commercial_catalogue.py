from app.commercial_catalogue import (
    B2C_PLANS,
    B2B_PLANS,
    RESTRICTED_FEATURES,
    catalogue_plan,
    has_entitlement,
    public_catalogue,
    resolve_entitlements,
)


def test_paid_b2c_plans_are_annual_and_prices_are_not_published():
    paid = [plan for plan in B2C_PLANS if plan["billing_period"] != "FREE"]
    assert paid
    assert all(plan["billing_period"] == "ANNUAL" for plan in paid)
    assert all(plan["price_minor"] is None for plan in paid)
    assert all(plan["price_status"] == "NOT_PUBLISHED" for plan in paid)


def test_b2b_contracts_are_annual_and_quote_required():
    assert B2B_PLANS
    assert all(plan["billing_period"] == "ANNUAL" for plan in B2B_PLANS)
    assert all(plan["quote_required"] is True for plan in B2B_PLANS)
    assert all(plan["price_minor"] is None for plan in B2B_PLANS)


def test_catalogue_is_prelaunch_and_never_enables_payment_collection():
    result = public_catalogue()
    assert result["commercial_status"] == "PRE_LAUNCH"
    assert result["payment_collection_enabled"] is False
    assert result["commercial_rules"]["monthly_paid_checkout_available"] is False
    result["b2c"][0]["features"].append("tampered")
    assert "tampered" not in public_catalogue()["b2c"][0]["features"]


def test_no_subscription_receives_only_free_features():
    result = resolve_entitlements(None)
    assert result["plan_code"] == "B2C_FREE"
    assert "dashboard_basic" in result["features"]
    assert "strategy_builder" not in result["features"]


def test_active_legacy_subscription_preserves_only_existing_workspace_entitlement():
    result = resolve_entitlements({"status": "ACTIVE", "plan_code": "YEARLY"})
    assert result["entitlement_status"] == "LEGACY_ACTIVE"
    assert result["features"] == ["strategy_workspace"]


def test_inactive_subscription_falls_back_to_free_features():
    result = resolve_entitlements({"status": "EXPIRED", "plan_code": "YEARLY"})
    assert result["plan_code"] == "B2C_FREE"
    assert "strategy_workspace" not in result["features"]


def test_unknown_plan_fails_closed():
    result = resolve_entitlements({"status": "ACTIVE", "plan_code": "UNRECOGNISED"})
    assert result["entitlement_status"] == "UNKNOWN_PLAN_DENIED"
    assert result["features"] == []


def test_restricted_features_cannot_be_granted_by_any_plan():
    for plan in B2C_PLANS + B2B_PLANS:
        subscription = {"status": "ACTIVE", "plan_code": plan["code"]}
        for feature in RESTRICTED_FEATURES:
            assert has_entitlement(subscription, feature) is False


def test_entitlement_requires_exact_feature_grant():
    sub = {"status": "ACTIVE", "plan_code": "B2C_TRADER_ANNUAL"}
    assert has_entitlement(sub, "options_analytics")
    assert not has_entitlement(sub, "white_label_option")


def test_catalogue_plan_lookup_is_case_insensitive_and_copy_safe():
    result = catalogue_plan("b2c_essential_annual")
    assert result is not None
    result["features"].append("tampered")
    assert "tampered" not in catalogue_plan("B2C_ESSENTIAL_ANNUAL")["features"]
