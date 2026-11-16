import os
from uuid import uuid4

import pytest

from app.support_center import SupportStore
from app.tenant_provisioning import TenantRegistry

_DATABASE_CONFIGURED = bool(os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_DATABASE_URL"))


@pytest.mark.skipif(not _DATABASE_CONFIGURED, reason="requires disposable PostgreSQL integration workflow")
def test_support_tickets_and_activity_use_postgres_with_customer_isolation():
    customer_a = "+91" + str(7000000000 + (uuid4().int % 999999999)).zfill(10)
    customer_b = "+91" + str(7000000000 + (uuid4().int % 999999999)).zfill(10)
    registry = TenantRegistry()
    registry.create_or_update_tenant(owner_customer_id=customer_a, name="Support test A")
    registry.create_or_update_tenant(owner_customer_id=customer_b, name="Support test B")
    store = SupportStore()
    try:
        ticket = store.create(customer_a, "Cannot access portfolio", "ACCOUNT",
                              "The portfolio page returns an access error.")
        ticket_id = ticket["ticket_id"]
        assert store.get_customer_ticket(customer_b, ticket_id) is None
        assert store.list_customer(customer_b) == []
        updated = store.admin_update(ticket_id, "admin-postgres-test", "Please sign out and back in.",
                                     status="WAITING_CUSTOMER", priority="HIGH")
        assert updated["status"] == "WAITING_CUSTOMER"
        events = updated["events"]
        # Creating a ticket, changing status, changing priority and replying
        # are four distinct audited actions; none may be silently collapsed.
        assert [event["event_type"] for event in events] == [
            "TICKET_CREATED", "STATUS_CHANGED", "PRIORITY_CHANGED", "ADMIN_REPLY"
        ]
        assert events[1]["metadata"] == {"from": "OPEN", "to": "WAITING_CUSTOMER"}
        assert events[2]["metadata"] == {"from": "NORMAL", "to": "HIGH"}
        assert events[-1]["message"] == "Please sign out and back in."
        assert store.get_customer_ticket(customer_a, ticket_id)["events"] == events
    finally:
        store.close()
        registry.close()
