import pytest
from fastapi.testclient import TestClient

from app import main
from app.security import require_admin, require_customer


@pytest.fixture
def nse_admin_client():
    original_status = main.nse_data_status
    original_trigger = main.trigger_nse_bootstrap
    main.nse_data_status = lambda: {"status": "READY", "markets": {"CM": 10, "FO": 20}}
    main.trigger_nse_bootstrap = lambda: {"status": "QUEUED"}
    main.app.dependency_overrides[require_customer] = lambda: "+919876543210"
    main.app.dependency_overrides[require_admin] = lambda: {
        "admin_id": "nse-admin-1",
        "email": "admin@example.test",
        "role": "ADMIN",
        "session_id": "nse-admin-session",
        "must_change_password": False,
    }
    client = TestClient(main.app)
    yield client
    client.app.dependency_overrides.clear()
    main.nse_data_status = original_status
    main.trigger_nse_bootstrap = original_trigger


def test_nse_status_is_available_to_authenticated_admin(nse_admin_client):
    response = nse_admin_client.get("/api/v1/nse-data/status")
    assert response.status_code == 200
    assert response.json()["status"] == "READY"


def test_nse_bootstrap_can_be_triggered_by_admin(nse_admin_client):
    response = nse_admin_client.post("/api/v1/nse-data/bootstrap")
    assert response.status_code == 200
    assert response.json()["status"] == "QUEUED"


def test_nse_status_rejects_customer_only_token():
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[require_customer] = lambda: "+919876543210"
    client = TestClient(main.app)
    response = client.get("/api/v1/nse-data/status")
    assert response.status_code == 401
    client.app.dependency_overrides.clear()


def test_nse_rows_reject_customer_only_token():
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[require_customer] = lambda: "+919876543210"
    client = TestClient(main.app)
    response = client.get("/api/v1/nse-data/rows?market=CM&limit=10")
    assert response.status_code == 401
    client.app.dependency_overrides.clear()


def test_nse_status_rejects_unauthenticated_request():
    main.app.dependency_overrides.clear()
    client = TestClient(main.app)
    response = client.get("/api/v1/nse-data/status")
    assert response.status_code == 401
    client.app.dependency_overrides.clear()


def test_customer_commercial_type_is_admin_managed(nse_admin_client, monkeypatch):
    recorded = {}
    def assign(customer_id, customer_type, admin_id):
        recorded.update(customer_id=customer_id, customer_type=customer_type, admin_id=admin_id)
        return dict(recorded)
    monkeypatch.setattr(main.account_directory, "set_customer_commercial_type", assign)
    response = nse_admin_client.put(
        "/api/v1/admin/customers/retail-123/commercial-type",
        json={"customer_type": "DATA_PRODUCT"},
    )
    assert response.status_code == 200
    assert recorded == {
        "customer_id": "retail-123",
        "customer_type": "DATA_PRODUCT",
        "admin_id": "nse-admin-1",
    }


def test_customer_commercial_type_endpoint_rejects_customer_only_token():
    main.app.dependency_overrides.clear()
    from app.security import require_customer
    main.app.dependency_overrides[require_customer] = lambda: "+919876543210"
    client = TestClient(main.app)
    response = client.put(
        "/api/v1/admin/customers/retail-123/commercial-type",
        json={"customer_type": "DATA_PRODUCT"},
    )
    assert response.status_code == 401
    main.app.dependency_overrides.clear()
