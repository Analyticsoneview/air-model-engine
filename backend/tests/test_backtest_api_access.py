import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backtest_api import router
from app.security import require_customer
import app.subscription_access as subscription_access


def _client(monkeypatch, subscription):
    monkeypatch.setattr(
        subscription_access,
        "active_subscription",
        lambda customer_id: subscription,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_customer] = lambda: "customer-123"
    return TestClient(app)


@pytest.mark.parametrize("subscription", [
    None,
    {"status": "PENDING", "plan_code": "MONTHLY"},
    {"status": "EXPIRED", "plan_code": "MONTHLY"},
    {"status": "CANCELLED", "plan_code": "MONTHLY"},
])
def test_backtest_strategy_catalog_rejects_non_active_subscription(monkeypatch, subscription):
    client = _client(monkeypatch, subscription)
    response = client.get("/api/v1/backtest/strategies")
    assert response.status_code == 403
    assert "active AIR subscription" in response.json()["detail"]


@pytest.mark.parametrize("subscription", [
    None,
    {"status": "PENDING", "plan_code": "MONTHLY"},
    {"status": "EXPIRED", "plan_code": "MONTHLY"},
    {"status": "CANCELLED", "plan_code": "MONTHLY"},
])
def test_expiryscan_report_rejects_non_active_subscription(monkeypatch, subscription):
    client = _client(monkeypatch, subscription)
    response = client.get(
        "/api/v1/backtest/expiryscan",
        params={"start_date": "2026-11-01", "end_date": "2026-11-02"},
    )
    assert response.status_code == 403
    assert "active AIR subscription" in response.json()["detail"]


def test_active_subscription_can_read_strategy_catalog(monkeypatch):
    client = _client(monkeypatch, {"status": "ACTIVE", "plan_code": "MONTHLY"})
    response = client.get("/api/v1/backtest/strategies")
    assert response.status_code == 200
    assert "EXPIRY78" in response.json()["daily_candle_eligible"]


def test_active_subscription_can_read_expiryscan_report(monkeypatch):
    client = _client(monkeypatch, {"status": "ACTIVE", "plan_code": "MONTHLY"})
    response = client.get(
        "/api/v1/backtest/expiryscan",
        params={"start_date": "2026-11-01", "end_date": "2026-11-02"},
    )
    assert response.status_code == 200
    assert response.json()["data_status"] == "NO_PRESERVED_COHORT_IN_PERIOD"
