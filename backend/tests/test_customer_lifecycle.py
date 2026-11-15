import sqlite3
from datetime import datetime, timedelta, timezone

from app.access_control import AccessStore


def test_customer_lifecycle_is_mobile_scoped_and_keeps_first_dates():
    store = AccessStore(":memory:")
    mobile = "+919876543210"
    first = store.request_access(mobile, "android-device-0001")
    second = store.request_access(mobile, "ios-device-0002")

    customers = store.list_marketing_customers()
    assert len(customers) == 1
    assert customers[0]["customer_id"] == mobile
    assert customers[0]["device_count"] == 2
    assert customers[0]["first_access_request_at"] == customers[0]["first_registered_at"]
    assert customers[0]["first_approved_at"] is None
    assert customers[0]["subscription_status"] == "NEVER_SUBSCRIBED"

    approved_at = "2026-11-15T10:00:00+00:00"
    assert store.review(
        first["request_id"], "APPROVED", "Initial approval",
        reviewer_admin_id="admin-1", reviewer_role="SUPER_ADMIN", totp_counter=70000001,
        authenticator_verified_at=approved_at,
        verification_reference="admin-action-totp:approve:70000001",
        request_context={"device_id": "android-device-0001", "ip": "192.0.2.10"},
    )
    rejected_at = "2026-11-15T10:05:00+00:00"
    assert store.review(
        second["request_id"], "REJECTED", "Second device request rejected",
        reviewer_admin_id="admin-2", reviewer_role="ADMIN", totp_counter=70000002,
        authenticator_verified_at=rejected_at,
        verification_reference="admin-action-totp:reject:70000002",
        request_context={"device_id": "ios-device-0002"},
    )

    customer = store.list_marketing_customers()[0]
    assert customer["first_approved_at"] == approved_at
    assert customer["first_rejected_at"] == rejected_at
    assert customer["subscription_status"] == "NEVER_SUBSCRIBED"

    history = store.decision_history(first["request_id"])
    assert history[0]["reviewer_admin_id"] == "admin-1"
    assert history[0]["authenticator_verified_at"] == approved_at
    assert history[0]["verification_reference"] == "admin-action-totp:approve:70000001"
    assert '"ip": "192.0.2.10"' in history[0]["request_context"]

    with store.db:
        try:
            store.db.execute(
                "UPDATE air_access_decision_history SET note='tampered' WHERE request_id=?",
                (first["request_id"],),
            )
            assert False, "decision audit update must be rejected"
        except sqlite3.IntegrityError:
            pass
        try:
            store.db.execute(
                "DELETE FROM air_access_decision_history WHERE request_id=?",
                (first["request_id"],),
            )
            assert False, "decision audit deletion must be rejected"
        except sqlite3.IntegrityError:
            pass
    store.db.close()


def test_first_plan_assignment_date_is_immutable_and_history_is_append_only():
    store = AccessStore(":memory:")
    mobile = "+919876543211"
    request = store.request_access(mobile, "android-device-0003")
    assert store.review(request["request_id"], "APPROVED", reviewer_admin_id="admin-1",
                        reviewer_role="SUPER_ADMIN", totp_counter=70000003)

    # Approval never grants a plan.
    assert store.get_subscription(mobile) is None
    first_start = datetime.now(timezone.utc)
    store.assign_subscription(mobile, "MONTHLY", first_start.isoformat(),
                              (first_start + timedelta(days=30)).isoformat(),
                              assigned_by_admin_id="admin-1")
    first_plan_date = store.list_marketing_customers()[0]["first_plan_availed_at"]
    assert first_plan_date
    assert store.list_marketing_customers()[0]["subscription_status"] == "ACTIVE"

    second_start = datetime.now(timezone.utc)
    store.assign_subscription(mobile, "YEARLY", second_start.isoformat(),
                              (second_start + timedelta(days=365)).isoformat(),
                              assigned_by_admin_id="admin-2")
    customer = store.list_marketing_customers()[0]
    assert customer["first_plan_availed_at"] == first_plan_date
    assert customer["plan_code"] == "YEARLY"
    assert store.db.execute(
        "SELECT COUNT(*) FROM air_customer_subscription_history WHERE customer_id=?", (mobile,)
    ).fetchone()[0] == 2

    with store.db:
        try:
            store.db.execute(
                "DELETE FROM air_customer_subscription_history WHERE customer_id=?", (mobile,)
            )
            assert False, "subscription audit deletion must be rejected"
        except sqlite3.IntegrityError:
            pass
    store.db.close()
