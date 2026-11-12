import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.access_control import AccessStore


class MarketingRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = AccessStore(str(Path(self.temp.name) / "air_auth.sqlite3"))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_registry_deduplicates_multiple_devices_and_defaults_to_no_consent(self):
        self.store.request_access("+919876543210", "device-identifier-0001")
        second = self.store.request_access("+919876543210", "device-identifier-0002")
        self.store.review(second["request_id"], "APPROVED")
        rows = self.store.list_marketing_customers()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["device_count"], 2)
        self.assertEqual(rows[0]["access_status"], "APPROVED")
        self.assertEqual(rows[0]["subscription_status"], "NEVER_SUBSCRIBED")
        self.assertFalse(rows[0]["promotional_consent"])
        self.assertEqual(rows[0]["marketing_status"], "NOT_GRANTED")

    def test_customer_controls_promotional_opt_in_and_opt_out(self):
        request = self.store.request_access("+919876543210", "device-identifier-0003")
        self.store.review(request["request_id"], "APPROVED")
        self.assertEqual(self.store.get_marketing_consent("+919876543210")["marketing_status"], "NOT_GRANTED")
        self.store.set_marketing_consent("+919876543210", True)
        self.assertEqual(self.store.get_marketing_consent("+919876543210")["marketing_status"], "OPTED_IN")
        self.assertEqual(self.store.marketing_segment_counts()["ELIGIBLE_FOR_PROMOTIONS"], 1)
        self.store.set_marketing_consent("+919876543210", False)
        self.assertEqual(self.store.get_marketing_consent("+919876543210")["marketing_status"], "OPTED_OUT")
        self.assertEqual(self.store.marketing_segment_counts()["ELIGIBLE_FOR_PROMOTIONS"], 0)
        self.assertEqual(len(self.store.list_marketing_customers("OPTED_OUT")), 1)

    def test_active_subscriber_is_never_in_promotion_eligible_segment(self):
        request = self.store.request_access("+919876543210", "device-identifier-0004")
        self.store.review(request["request_id"], "APPROVED")
        self.store.set_marketing_consent("+919876543210", True)
        starts = datetime.now(timezone.utc)
        self.store.assign_subscription("+919876543210", "MONTHLY", starts.isoformat(),
                                        (starts + timedelta(days=30)).isoformat())
        self.assertEqual(self.store.marketing_segment_counts()["ELIGIBLE_FOR_PROMOTIONS"], 0)
        self.assertEqual(len(self.store.list_marketing_customers("ACTIVE")), 1)

    def test_offer_is_draft_until_super_admin_approval_and_can_be_revoked(self):
        starts = datetime.now(timezone.utc)
        expires = starts + timedelta(days=14)
        offer = self.store.create_marketing_offer(
            "Monthly introduction", "WELCOME10", "MONTHLY", 10,
            starts.isoformat(), expires.isoformat(), "New customers only", "admin-1",
        )
        self.assertEqual(offer["status"], "DRAFT")
        approved = self.store.approve_marketing_offer(offer["offer_id"], "super-admin-1")
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(approved["approved_by"], "super-admin-1")
        self.assertTrue(self.store.revoke_marketing_offer(offer["offer_id"], "super-admin-1"))
        self.assertEqual(self.store.get_marketing_offer(offer["offer_id"])["status"], "REVOKED")

    def test_invalid_discount_and_duplicate_offer_code_are_rejected(self):
        starts = datetime.now(timezone.utc)
        expires = starts + timedelta(days=14)
        with self.assertRaises(ValueError):
            self.store.create_marketing_offer(
                "Too large", "BAD90", "MONTHLY", 95,
                starts.isoformat(), expires.isoformat(), "", "admin-1",
            )
        self.store.create_marketing_offer(
            "First", "SAVE10", "MONTHLY", 10,
            starts.isoformat(), expires.isoformat(), "", "admin-1",
        )
        with self.assertRaises(Exception):
            self.store.create_marketing_offer(
                "Duplicate", "SAVE10", "YEARLY", 10,
                starts.isoformat(), expires.isoformat(), "", "admin-1",
            )

    def test_expired_draft_offer_cannot_be_approved(self):
        starts = datetime.now(timezone.utc) - timedelta(days=3)
        expires = datetime.now(timezone.utc) - timedelta(days=1)
        offer = self.store.create_marketing_offer(
            "Expired draft", "OLDDEAL", "MONTHLY", 10,
            starts.isoformat(), expires.isoformat(), "", "admin-1",
        )
        with self.assertRaises(ValueError):
            self.store.approve_marketing_offer(offer["offer_id"], "super-admin-1")
        self.assertEqual(self.store.get_marketing_offer(offer["offer_id"])["status"], "DRAFT")

    def test_offer_expiry_must_follow_start(self):
        starts = datetime.now(timezone.utc)
        with self.assertRaises(ValueError):
            self.store.create_marketing_offer(
                "Bad dates", "BADDATE", "MONTHLY", 10,
                starts.isoformat(), (starts - timedelta(seconds=1)).isoformat(), "", "admin-1",
            )


if __name__ == "__main__":
    unittest.main()
