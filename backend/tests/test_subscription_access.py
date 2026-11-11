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
