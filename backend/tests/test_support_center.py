import pytest
from app.support_center import SupportStore


def test_customer_tickets_are_tenant_scoped_and_history_is_append_only():
    store = SupportStore(":memory:")
    try:
        ticket = store.create("+919876543210", "Cannot access account", "ACCOUNT",
                              "I cannot sign in after changing my device.")
        ticket_id = ticket["ticket_id"]
        assert ticket["status"] == "OPEN"
        assert len(ticket["events"]) == 1
        assert store.get_customer_ticket("+919876543211", ticket_id) is None
        assert store.list_customer("+919876543211") == []
        with pytest.raises(Exception, match="append-only"):
            store.db.execute("UPDATE air_support_ticket_events SET message='tampered'")
        with pytest.raises(Exception, match="append-only"):
            store.db.execute("DELETE FROM air_support_ticket_events")
    finally:
        store.close()


def test_customer_reply_and_admin_resolution_are_audited():
    store = SupportStore(":memory:")
    try:
        ticket = store.create("+919876543210", "Broker connection issue", "BROKER",
                              "My broker connection stopped working today.")
        ticket_id = ticket["ticket_id"]
        replied = store.customer_reply("+919876543210", ticket_id, "I have refreshed my broker token.")
        assert replied["status"] == "OPEN"
        updated = store.admin_update(ticket_id, "admin-1", "Please reconnect the account.",
                                     status="WAITING_CUSTOMER", priority="HIGH", assigned_admin_id="admin-1")
        assert updated["status"] == "WAITING_CUSTOMER"
        assert updated["priority"] == "HIGH"
        assert updated["assigned_admin_id"] == "admin-1"
        assert [event["event_type"] for event in updated["events"]] == [
            "TICKET_CREATED","CUSTOMER_REPLY","STATUS_CHANGED","PRIORITY_CHANGED","ASSIGNED","ADMIN_REPLY"
        ]
    finally:
        store.close()


def test_closed_ticket_rejects_new_customer_replies_and_invalid_states():
    store = SupportStore(":memory:")
    try:
        ticket = store.create("+919876543210", "Billing plan query", "BILLING",
                              "Please explain the expiry date of my plan.")
        store.admin_update(ticket["ticket_id"], "admin-1", status="CLOSED")
        with pytest.raises(ValueError, match="Closed tickets"):
            store.customer_reply("+919876543210", ticket["ticket_id"], "I need more help with this issue.")
        with pytest.raises(ValueError, match="Unsupported ticket status"):
            store.admin_update(ticket["ticket_id"], "admin-1", status="INVALID")
    finally:
        store.close()


def test_support_input_validation_and_admin_queue_priority_order():
    store = SupportStore(":memory:")
    try:
        with pytest.raises(ValueError):
            store.create("+919876543210", "bad", "GENERAL", "short")
        normal = store.create("+919876543210", "General question", "GENERAL",
                              "Please help me understand this feature.")
        urgent = store.create("+919876543211", "Account locked today", "ACCOUNT",
                               "My account has been locked and I cannot sign in.")
        store.admin_update(normal["ticket_id"], "admin-1", priority="NORMAL")
        store.admin_update(urgent["ticket_id"], "admin-1", priority="URGENT")
        assert [x["ticket_id"] for x in store.list_admin()] == [urgent["ticket_id"], normal["ticket_id"]]
    finally:
        store.close()
