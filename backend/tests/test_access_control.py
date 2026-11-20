import sqlite3
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

    def test_legacy_reviewed_at_backfills_first_approval_without_decision_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "legacy-auth.sqlite3")
            legacy = sqlite3.connect(path)
            legacy.execute("""CREATE TABLE air_access_requests(
                request_id TEXT PRIMARY KEY,mobile_e164 TEXT NOT NULL,device_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',created_at TEXT NOT NULL,
                reviewed_at TEXT,reviewer_note TEXT,UNIQUE(mobile_e164,device_id))""")
            legacy.execute("INSERT INTO air_access_requests VALUES(?,?,?,?,?,?,?)",
                ("legacy-request", "+919876543296", "legacy-device-0001", "APPROVED",
                 "2026-01-01 00:00:00", "2026-01-02 00:00:00", "legacy review"))
            legacy.commit()
            legacy.close()

            store = AccessStore(path)
            customer = store.list_marketing_customers(search="+919876543296")[0]
            self.assertEqual(customer["first_registered_at"], "2026-01-01 00:00:00")
            self.assertEqual(customer["first_approved_at"], "2026-01-02 00:00:00")
            self.assertEqual(store.decision_history("legacy-request"), [])
            store.close()

    def test_customer_lifecycle_dates_and_append_only_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            first = store.request_access("+919876543299", "device-lifecycle-0001")
            second = store.request_access("+919876543299", "device-lifecycle-0002")
            self.assertNotEqual(first["request_id"], second["request_id"])
            self.assertTrue(store.review(first["request_id"], "APPROVED", "Verified",
                reviewer_admin_id="admin-1", reviewer_role="SUPER_ADMIN", totp_counter=12345,
                verification_reference="verify-1", request_context={"source": "admin"}))
            history = store.decision_history(first["request_id"])
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["verification_reference"], "verify-1")
            self.assertEqual(history[0]["device_id"], "device-lifecycle-0001")
            self.assertIn("totp_verified_at", history[0])
            customer = store.list_marketing_customers(search="+919876543299")[0]
            self.assertEqual(customer["device_count"], 2)
            self.assertIsNotNone(customer["first_approved_at"])
            self.assertIsNone(customer["first_rejected_at"])
            with self.assertRaises(Exception):
                with store.db:
                    store.db.execute("UPDATE air_access_decision_history SET note='tampered'")
            store.close()

    def test_first_plan_date_is_preserved_across_plan_reassignment(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            store.request_access("+919876543298", "device-lifecycle-0003")
            starts = datetime.now(timezone.utc)
            store.assign_subscription("+919876543298", "MONTHLY", starts.isoformat(),
                                      (starts + timedelta(days=30)).isoformat())
            first_plan = store.list_marketing_customers(search="+919876543298")[0]["first_plan_availed_at"]
            store.assign_subscription("+919876543298", "YEARLY", starts.isoformat(),
                                      (starts + timedelta(days=365)).isoformat())
            customer = store.list_marketing_customers(search="+919876543298")[0]
            self.assertEqual(customer["first_plan_availed_at"], first_plan)
            self.assertEqual(store.db.execute("SELECT COUNT(*) FROM air_customer_subscription_history").fetchone()[0], 2)
            store.close()

    def test_international_mobile_format_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            with self.assertRaises(ValueError):
                store.request_access("9876543210", "device-identifier-0003")
            store.close()


    def test_subscription_assignment_history_is_append_only(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            store.request_access("+919876543297", "device-lifecycle-0004")
            starts = datetime.now(timezone.utc)
            store.assign_subscription("+919876543297", "MONTHLY", starts.isoformat(),
                                      (starts + timedelta(days=30)).isoformat())
            with self.assertRaises(Exception):
                with store.db:
                    store.db.execute("UPDATE air_customer_subscription_history SET plan_code='YEARLY'")
            with self.assertRaises(Exception):
                with store.db:
                    store.db.execute("DELETE FROM air_customer_subscription_history")
            store.close()


    def test_customer_pin_allows_returning_device_without_second_admin_approval(self):
        from app.security import hash_pin
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            first = store.request_access("+919876543210", "device-initial-0001")
            self.assertEqual(first["status"], "PENDING")
            self.assertTrue(store.review(first["request_id"], "APPROVED",
                reviewer_admin_id="admin-1", reviewer_role="SUPER_ADMIN", totp_counter=101))
            legacy_session = store.create_session(first["request_id"])
            store.set_customer_pin("+919876543210", "device-initial-0001", hash_pin("123456"))
            self.assertFalse(store.is_session_active(legacy_session))
            self.assertTrue(store.verify_customer_pin("+919876543210", "123456"))
            second = store.register_approved_device("+919876543210", "device-returning-0002")
            self.assertEqual(second["status"], "APPROVED")
            self.assertIn("Automatically registered", second["reviewer_note"])
            self.assertEqual(len(store.list_marketing_customers(search="+919876543210")), 1)
            self.assertEqual(store.list_marketing_customers(search="+919876543210")[0]["device_count"], 2)
            store.close()

    def test_pending_duplicate_device_is_auto_approved_after_valid_pin(self):
        from app.security import hash_pin
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            first = store.request_access("+919876543211", "device-first-0001")
            second = store.request_access("+919876543211", "device-second-0002")
            store.review(first["request_id"], "APPROVED", reviewer_admin_id="admin-1",
                         reviewer_role="SUPER_ADMIN", totp_counter=102)
            pending_row = next(row for row in store.list_requests("PENDING") if row["request_id"] == second["request_id"])
            self.assertEqual(pending_row["requires_admin_approval"], 0)
            store.set_customer_pin("+919876543211", "device-first-0001", hash_pin("654321"))
            self.assertTrue(store.verify_customer_pin("+919876543211", "654321"))
            returning = store.register_approved_device("+919876543211", "device-second-0002")
            self.assertEqual(returning["request_id"], second["request_id"])
            self.assertEqual(returning["status"], "APPROVED")
            self.assertIn("Authenticated with", returning["reviewer_note"])
            store.close()

    def test_customer_pin_lockout_and_admin_reset_revoke_sessions(self):
        from app.security import hash_pin
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            request = store.request_access("+919876543212", "device-reset-0001")
            store.review(request["request_id"], "APPROVED", reviewer_admin_id="admin-1",
                         reviewer_role="SUPER_ADMIN", totp_counter=103)
            store.set_customer_pin("+919876543212", "device-reset-0001", hash_pin("111222"))
            session = store.create_session(request["request_id"])
            for _ in range(5):
                self.assertFalse(store.verify_customer_pin("+919876543212", "999999"))
            with self.assertRaises(PermissionError):
                store.verify_customer_pin("+919876543212", "111222")
            store.reset_customer_pin("+919876543212", "admin-1")
            self.assertFalse(store.is_session_active(session))
            self.assertTrue(store.customer_pin_state("+919876543212")["must_reset"])
            store.set_customer_pin("+919876543212", "device-new-reset-0002", hash_pin("333444"))
            new_device = store.register_approved_device("+919876543212", "device-new-reset-0002")
            self.assertEqual(new_device["status"], "APPROVED")
            self.assertTrue(store.verify_customer_pin("+919876543212", "333444"))
            store.close()



    def test_approved_customer_identity_survives_a_new_browser_device(self):
        from app.security import hash_pin
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            first = store.request_access("+919876543211", "original-device-0001")
            self.assertTrue(store.review(first["request_id"], "APPROVED"))
            self.assertTrue(store.customer_has_approved_access("+919876543211"))
            state = store.customer_pin_state("+919876543211")
            self.assertFalse(state["pin_set"])
            store.set_customer_pin("+919876543211", "original-device-0001", hash_pin("654321"))
            state = store.customer_pin_state("+919876543211")
            self.assertTrue(state["pin_set"])
            self.assertTrue(store.verify_customer_pin("+919876543211", "654321"))
            # A new browser/device has no request row yet, but the customer identity
            # and PIN remain valid and can be used to register that device.
            self.assertIsNone(store.get_request("+919876543211", "fresh-browser-device-0002"))
            self.assertTrue(store.verify_customer_pin("+919876543211", "654321"))
            registered = store.register_approved_device("+919876543211", "fresh-browser-device-0002")
            self.assertEqual(registered["status"], "APPROVED")
            self.assertTrue(store.customer_has_approved_access("+919876543211"))
            store.close()


if __name__ == "__main__":
    unittest.main()
