from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import app.main as main
from app.access_control import AccessStore


@pytest.mark.asyncio
async def test_customer_register_date_filters_and_daily_conversion_report(monkeypatch):
    store = AccessStore(":memory:")
    monkeypatch.setattr(main, "access_store", store)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    mobile = "+919876543210"
    first = store.request_access(mobile, "android-device-0001")
    second = store.request_access(mobile, "ios-device-0002")
    pending = store.request_access("+919876543211", "android-device-0003")

    now = datetime.now(timezone.utc)
    store.review(first["request_id"], "APPROVED", "approved",
                 reviewer_admin_id="admin-1", reviewer_role="SUPER_ADMIN", totp_counter=70000001,
                 authenticator_verified_at=now.isoformat())
    store.assign_subscription(mobile, "MONTHLY", now.isoformat(),
                              (now + timedelta(days=30)).isoformat(), assigned_by_admin_id="admin-1")

    result = await main.admin_customer_register(
        registered_from=None, registered_to=None, approved_from=today, approved_to=today,
        rejected_from=None, rejected_to=None, plan_availed_from=None, plan_availed_to=None,
        expires_from=None, expires_to=None, as_of_date=today, segment="ALL", search="",
        limit=5000, admin={"role": "ADMIN"},
    )
    assert result["count"] == 1
    assert result["customers"][0]["customer_type"] == "NEW"
    assert result["customers"][0]["first_approved_at_ist"]
    assert result["customers"][0]["first_plan_availed_at_ist"]

    report = await main.admin_customer_daily_report(today, {"role": "ADMIN"})
    metrics = report["metrics"]
    assert metrics["new_registrations"] == 2
    assert metrics["existing_customer_requests"] == 1
    assert metrics["approved"] == 1
    assert metrics["pending"] == 1
    assert metrics["first_time_plan_availed"] == 1
    assert report["conversion"]["registration_to_approval_percent"] == 50.0
    store.db.close()
