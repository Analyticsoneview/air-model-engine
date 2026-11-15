import os
from uuid import uuid4

import pytest

from app.support_center import SupportStore

_DATABASE_CONFIGURED = bool(os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_DATABASE_URL"))


@pytest.mark.skipif(not _DATABASE_CONFIGURED, reason="requires disposable PostgreSQL integration workflow")
def test_support_tickets_and_activity_use_postgres_with_customer_isolation():
    customer_a = "+91" + str(7000000000 + (uuid4().int % 999999999)).zfill(10)
    customer_b = "+91" + str(7000000000 + (uuid4().int % 999999999)).zfill(10)
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
        assert len(updated["events"]) == 3
        assert store.get_customer_ticket(customer_a, ticket_id)["events"][-1]["event_type"] == "ADMIN_REPLY"
    finally:
        store.close()
