from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.internal_workspace_api import router, require_internal_owner
from app.security import require_admin


def _client(admin, monkeypatch, owner_email="owner@example.com"):
    if owner_email is None:
        monkeypatch.delenv("AIR_INTERNAL_OWNER_EMAIL", raising=False)
    else:
        monkeypatch.setenv("AIR_INTERNAL_OWNER_EMAIL", owner_email)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = lambda: admin
    return TestClient(app)


def test_internal_policy_is_available_only_to_configured_super_admin(monkeypatch):
    client = _client(
        {"admin_id": "owner-1", "email": "owner@example.com", "role": "SUPER_ADMIN"},
        monkeypatch,
    )
    response = client.get("/api/v1/internal-workspace/policy")
    assert response.status_code == 200
    policy = response.json()
    assert policy["access"] == "OWNER_ONLY"
    assert policy["classification_label"] == "INTERNAL — NOT FOR DISTRIBUTION"
    assert policy["customer_sharing"] is False
    assert policy["publication"] is False
    assert policy["personalised_investment_advice"] is False
    assert policy["automated_order_execution"] is False
    assert policy["broker_order_submission"] is False


def test_internal_policy_rejects_other_super_admin(monkeypatch):
    client = _client(
        {"admin_id": "other-1", "email": "other@example.com", "role": "SUPER_ADMIN"},
        monkeypatch,
    )
    assert client.get("/api/v1/internal-workspace/policy").status_code == 403


def test_internal_policy_rejects_non_super_admin_even_with_owner_email(monkeypatch):
    client = _client(
        {"admin_id": "owner-1", "email": "owner@example.com", "role": "ADMIN"},
        monkeypatch,
    )
    assert client.get("/api/v1/internal-workspace/policy").status_code == 403


def test_internal_policy_fails_closed_when_owner_is_not_configured(monkeypatch):
    client = _client(
        {"admin_id": "owner-1", "email": "owner@example.com", "role": "SUPER_ADMIN"},
        monkeypatch,
        owner_email=None,
    )
    assert client.get("/api/v1/internal-workspace/policy").status_code == 503
