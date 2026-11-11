import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.access_control import AccessStore


class AccessStoreTests(unittest.TestCase):
    def test_new_device_waits_for_explicit_admin_approval_before_session(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            request = store.request_access("+14155550123", "device-identifier-0001")
            self.assertEqual(request["status"], "PENDING")
            with self.assertRaises(PermissionError):
                store.create_session(request["request_id"])
            self.assertTrue(store.review(request["request_id"], "APPROVED"))
            session_id = store.create_session(request["request_id"])
            self.assertTrue(store.is_session_active(session_id))
            store.close()

    def test_blocking_request_revokes_existing_device_sessions(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            request = store.request_access("+447700900123", "device-identifier-0002")
            store.review(request["request_id"], "APPROVED")
            session_id = store.create_session(request["request_id"])
            self.assertTrue(store.is_session_active(session_id))

            store.review(request["request_id"], "BLOCKED", "Administrator blocked access")
            self.assertFalse(store.is_session_active(session_id))
            store.close()

    def test_device_request_resolves_to_stable_mobile_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            request = store.request_access("+919876543210", "device-identifier-0004")
            self.assertEqual(
                store.mobile_for_request_id(request["request_id"]),
                "+919876543210",
            )
            store.close()

    def test_subscription_plan_is_saved_and_expires(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            store.assign_subscription("+919876543210", "MONTHLY",
                "2026-01-01T00:00:00+00:00", "2026-01-31T00:00:00+00:00")
            subscription = store.get_subscription("+919876543210")
            self.assertEqual(subscription["plan_code"], "MONTHLY")
            self.assertEqual(subscription["status"], "EXPIRED")
            store.close()

    def test_subscription_is_pending_before_its_start_date(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            starts = datetime.now(timezone.utc) + timedelta(days=1)
            expires = starts + timedelta(days=30)
            store.assign_subscription(
                "+919876543210", "MONTHLY", starts.isoformat(), expires.isoformat()
            )
            subscription = store.get_subscription("+919876543210")
            self.assertEqual(subscription["status"], "PENDING")
            store.close()

    def test_subscription_window_must_have_expiry_after_start(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            starts = datetime.now(timezone.utc)
            with self.assertRaises(ValueError):
                store.assign_subscription(
                    "+919876543210", "MONTHLY",
                    starts.isoformat(), (starts - timedelta(seconds=1)).isoformat(),
                )
            store.close()

    def test_invalid_subscription_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            with self.assertRaises(ValueError):
                store.assign_subscription("+919876543210", "LIFETIME",
                    "2026-01-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00")
            store.close()
    def test_international_mobile_format_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            with self.assertRaises(ValueError):
                store.request_access("9876543210", "device-identifier-0003")
            store.close()


if __name__ == "__main__":
    unittest.main()
