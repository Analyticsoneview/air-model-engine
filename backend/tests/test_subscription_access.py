import pytest
from fastapi import HTTPException

from app import subscription_access


def test_strategy_access_denies_customer_without_subscription(monkeypatch):
    monkeypatch.delenv("AIR_OPERATOR_CUSTOMER_IDS", raising=False)
    monkeypatch.setattr(subscription_access.access_store, "mobile_for_request_id", lambda _value: None)
    monkeypatch.setattr(subscription_access.access_store, "get_subscription", lambda _value: None)

    with pytest.raises(HTTPException) as error:
        subscription_access.require_strategy_subscription("customer-1")

    assert error.value.status_code == 403


def test_strategy_access_denies_expired_subscription(monkeypatch):
    monkeypatch.delenv("AIR_OPERATOR_CUSTOMER_IDS", raising=False)
    monkeypatch.setattr(subscription_access.access_store, "mobile_for_request_id", lambda _value: None)
    monkeypatch.setattr(
        subscription_access.access_store,
        "get_subscription",
        lambda _value: {"status": "EXPIRED", "plan_code": "MONTHLY"},
    )

    with pytest.raises(HTTPException) as error:
        subscription_access.require_strategy_subscription("customer-2")

    assert error.value.status_code == 403


def test_operator_customer_has_strategy_access_without_paid_plan(monkeypatch):
    monkeypatch.setenv("AIR_OPERATOR_CUSTOMER_IDS", "+919876543210")
    monkeypatch.setattr(
        subscription_access.access_store,
        "mobile_for_request_id",
        lambda request_id: "+919876543210" if request_id == "operator-request" else None,
    )
    monkeypatch.setattr(
        subscription_access.access_store,
        "get_subscription",
        lambda _value: (_ for _ in ()).throw(AssertionError("operator bypass must not query paid plan")),
    )

    result = subscription_access.require_strategy_subscription("operator-request")

    assert result["status"] == "ACTIVE"
    assert result["plan_code"] == "OPERATOR"


def test_fastapi_strategy_dependency_returns_customer_after_entitlement_check(monkeypatch):
    monkeypatch.delenv("AIR_OPERATOR_CUSTOMER_IDS", raising=False)
    monkeypatch.setattr(subscription_access.access_store, "mobile_for_request_id", lambda _value: None)
    monkeypatch.setattr(
        subscription_access.access_store,
        "get_subscription",
        lambda _value: {"status": "ACTIVE", "plan_code": "MONTHLY"},
    )

    assert subscription_access.require_strategy_access("customer-3") == "customer-3"


def test_feature_entitlement_dependency_allows_exact_active_plan_feature(monkeypatch):
    monkeypatch.delenv("AIR_OPERATOR_CUSTOMER_IDS", raising=False)
    monkeypatch.setattr(subscription_access.access_store, "mobile_for_request_id", lambda _value: None)
    monkeypatch.setattr(
        subscription_access.access_store,
        "get_subscription",
        lambda _value: {"status": "ACTIVE", "plan_code": "B2C_TRADER_ANNUAL"},
    )

    dependency = subscription_access.require_feature_entitlement("options_analytics")
    assert dependency("customer-feature") == "customer-feature"


def test_feature_entitlement_dependency_denies_ungranted_feature(monkeypatch):
    monkeypatch.delenv("AIR_OPERATOR_CUSTOMER_IDS", raising=False)
    monkeypatch.setattr(subscription_access.access_store, "mobile_for_request_id", lambda _value: None)
    monkeypatch.setattr(
        subscription_access.access_store,
        "get_subscription",
        lambda _value: {"status": "ACTIVE", "plan_code": "B2C_ESSENTIAL_ANNUAL"},
    )

    dependency = subscription_access.require_feature_entitlement("options_analytics")
    with pytest.raises(HTTPException) as error:
        dependency("customer-feature")
    assert error.value.status_code == 403


def test_feature_entitlement_dependency_denies_restricted_capability(monkeypatch):
    monkeypatch.delenv("AIR_OPERATOR_CUSTOMER_IDS", raising=False)
    monkeypatch.setattr(subscription_access.access_store, "mobile_for_request_id", lambda _value: None)
    monkeypatch.setattr(
        subscription_access.access_store,
        "get_subscription",
        lambda _value: {"status": "ACTIVE", "plan_code": "B2C_ELITE_ANNUAL"},
    )

    dependency = subscription_access.require_feature_entitlement("broker_order_submission")
    with pytest.raises(HTTPException) as error:
        dependency("customer-feature")
    assert error.value.status_code == 403


def test_signed_enterprise_license_is_authoritative_for_feature_gates(monkeypatch):
    monkeypatch.setenv("AIR_ENTERPRISE_LICENSE_TOKEN", "installed-token")
    monkeypatch.setattr("app.enterprise_licensing.runtime_enterprise_license",
                        lambda: {"features": ["api_access"]})
    monkeypatch.setattr(subscription_access, "active_subscription",
                        lambda _customer: {"status": "ACTIVE", "plan_code": "OPERATOR"})
    assert subscription_access.require_feature_entitlement("api_access")("customer-1") == "customer-1"
    with pytest.raises(HTTPException) as error:
        subscription_access.require_feature_entitlement("options_analytics")("customer-1")
    assert error.value.status_code == 403


def test_invalid_enterprise_license_does_not_fall_back_to_operator_override(monkeypatch):
    from app.enterprise_licensing import EnterpriseLicenseError
    monkeypatch.setenv("AIR_ENTERPRISE_LICENSE_TOKEN", "invalid-token")
    monkeypatch.setattr("app.enterprise_licensing.runtime_enterprise_license",
                        lambda: (_ for _ in ()).throw(EnterpriseLicenseError("bad signature")))
    monkeypatch.setattr(subscription_access, "active_subscription",
                        lambda _customer: {"status": "ACTIVE", "plan_code": "OPERATOR"})
    with pytest.raises(HTTPException) as error:
        subscription_access.require_feature_entitlement("api_access")("customer-1")
    assert error.value.status_code == 403


def test_free_plan_includes_historical_replay_but_not_live_options():
    from app.commercial_catalogue import has_entitlement

    assert has_entitlement(None, "historical_analysis")
    assert has_entitlement(None, "historical_strategy_replay")
    assert not has_entitlement(None, "options_analytics")


def test_paid_options_plan_includes_historical_replay_and_options_analytics():
    from app.commercial_catalogue import has_entitlement

    subscription = {"status": "ACTIVE", "plan_code": "B2C_TRADER_ANNUAL"}
    assert has_entitlement(subscription, "historical_strategy_replay")
    assert has_entitlement(subscription, "options_analytics")
