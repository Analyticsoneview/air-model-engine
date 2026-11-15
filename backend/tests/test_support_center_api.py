import pytest
from fastapi.testclient import TestClient

from app import main
from app.security import require_admin, require_customer
from app.support_center import SupportStore


@pytest.fixture
def support_client():
    original = main.support_store
    main.support_store = SupportStore(":memory:")
    app = main.app
    app.dependency_overrides[require_customer] = lambda: "+919876543210"
    app.dependency_overrides[require_admin] = lambda: {
        "admin_id": "support-admin-1", "role": "ADMIN", "email": "admin@example.test",
        "session_id": "test-session", "must_change_password": False,
    }
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    main.support_store.close()
    main.support_store = original


def test_customer_support_api_create_list_and_reply_is_scoped(support_client):
    created = support_client.post("/api/v1/customer/support/tickets", json={
        "subject": "Unable to sign in", "category": "ACCOUNT",
        "message": "I cannot sign in after resetting my device.",
    })
    assert created.status_code == 201
    ticket = created.json()["ticket"]
    ticket_id = ticket["ticket_id"]
    assert ticket["customer_id"] == "+919876543210"
    assert support_client.get("/api/v1/customer/support/tickets").json()["tickets"][0]["ticket_id"] == ticket_id
    reply = support_client.post(f"/api/v1/customer/support/tickets/{ticket_id}/replies",
                                json={"message":"I have retried and the issue still occurs."})
    assert reply.status_code == 200
    assert reply.json()["ticket"]["events"][-1]["event_type"] == "CUSTOMER_REPLY"


def test_admin_queue_and_updates_record_customer_visible_reply(support_client):
    ticket = support_client.post("/api/v1/customer/support/tickets", json={
        "subject": "Broker not connecting", "category": "BROKER",
        "message": "My broker account is not connecting this morning.",
    }).json()["ticket"]
    queue = support_client.get("/api/v1/admin/support/tickets?status=OPEN")
    assert queue.status_code == 200
    assert queue.json()["tickets"][0]["ticket_id"] == ticket["ticket_id"]
    updated = support_client.put(f"/api/v1/admin/support/tickets/{ticket['ticket_id']}", json={
        "message": "Please reconnect your broker account and retry.",
        "status": "WAITING_CUSTOMER", "priority": "HIGH",
    })
    assert updated.status_code == 200
    result = updated.json()["ticket"]
    assert result["status"] == "WAITING_CUSTOMER"
    assert result["priority"] == "HIGH"
    assert result["events"][-1]["event_type"] == "ADMIN_REPLY"


def test_customer_cannot_read_another_customers_ticket(support_client):
    ticket = support_client.post("/api/v1/customer/support/tickets", json={
        "subject": "Account question", "category": "GENERAL",
        "message": "Please explain where I can update my account details.",
    }).json()["ticket"]
    support_client.app.dependency_overrides[require_customer] = lambda: "+919876543211"
    response = support_client.get(f"/api/v1/customer/support/tickets/{ticket['ticket_id']}")
    assert response.status_code == 404
