"""Integration coverage for PostgreSQL customer access and marketing storage.

Run after Alembic upgrade head with AIR_TEST_CUSTOMER_DATABASE_URL configured.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.customer_auth_postgres import PostgresAccessStore
from app.scripts.migrate_customer_sqlite_to_postgres import migrate


TABLES = (
    "air_marketing_audit", "air_marketing_offers",
    "air_customer_marketing_preferences", "air_customer_subscriptions",
    "air_device_sessions", "air_access_requests",
)


def _database_url():
    url = os.getenv("AIR_TEST_CUSTOMER_DATABASE_URL")
    if not url:
        pytest.skip("AIR_TEST_CUSTOMER_DATABASE_URL not configured")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("AIR_TEST_CUSTOMER_DATABASE_URL must point to PostgreSQL")
    return url


def _clear_database(url):
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            for table in TABLES:
                conn.execute(text(f"DELETE FROM {table}"))
    finally:
        engine.dispose()


@pytest.fixture
def customer_store():
    url = _database_url()
    _clear_database(url)
    store = PostgresAccessStore(database_url=url)
    try:
        yield store
    finally:
        store.close()
        _clear_database(url)


def test_access_approval_session_and_block_revocation(customer_store):
    request = customer_store.request_access("+919876543210", "android-device-0001")
    assert request["status"] == "PENDING"
    with pytest.raises(PermissionError):
        customer_store.create_session(request["request_id"])
    assert customer_store.review(request["request_id"], "APPROVED", "Verified by Admin")
    session_id = customer_store.create_session(request["request_id"])
    assert customer_store.is_session_active(session_id)
    assert customer_store.review(request["request_id"], "BLOCKED", "Access withdrawn")
    assert not customer_store.is_session_active(session_id)
    assert customer_store.list_requests("BLOCKED")[0]["request_id"] == request["request_id"]


def test_device_deduplication_consent_and_subscription_segmentation(customer_store):
    first = customer_store.request_access("+919876543211", "android-device-0002")
    second = customer_store.request_access("+919876543211", "android-device-0003")
    assert first["request_id"] != second["request_id"]
    customer_store.review(first["request_id"], "APPROVED")
    customer_store.set_marketing_consent("+919876543211", True)
    customers = customer_store.list_marketing_customers()
    assert len(customers) == 1
    assert customers[0]["device_count"] == 2
    assert customers[0]["marketing_status"] == "OPTED_IN"
    assert customer_store.marketing_segment_counts()["ELIGIBLE_FOR_PROMOTIONS"] == 1

    now = datetime.now(timezone.utc)
    customer_store.assign_subscription("+919876543211", "MONTHLY", now.isoformat(),
                                        (now + timedelta(days=30)).isoformat())
    assert customer_store.marketing_segment_counts()["ELIGIBLE_FOR_PROMOTIONS"] == 0
    assert customer_store.list_marketing_customers("ACTIVE")[0]["plan_code"] == "MONTHLY"
    customer_store.set_marketing_consent("+919876543211", False)
    assert customer_store.list_marketing_customers("OPTED_OUT")[0]["marketing_status"] == "OPTED_OUT"


def test_offer_requires_approval_and_can_be_revoked(customer_store):
    now = datetime.now(timezone.utc)
    offer = customer_store.create_marketing_offer(
        "Monthly welcome", "WELCOME10", "MONTHLY", 10,
        now.isoformat(), (now + timedelta(days=10)).isoformat(),
        "New customers only", "admin-1",
    )
    assert offer["status"] == "DRAFT"
    approved = customer_store.approve_marketing_offer(offer["offer_id"], "super-admin-1")
    assert approved["status"] == "APPROVED"
    assert customer_store.revoke_marketing_offer(offer["offer_id"], "super-admin-1")
    assert customer_store.get_marketing_offer(offer["offer_id"])["status"] == "REVOKED"


def test_state_persists_after_store_recreation(customer_store):
    request = customer_store.request_access("+919876543212", "android-device-0004")
    customer_store.review(request["request_id"], "APPROVED")
    customer_store.set_marketing_consent("+919876543212", True)
    url = os.environ["AIR_TEST_CUSTOMER_DATABASE_URL"]
    customer_store.close()
    reopened = PostgresAccessStore(database_url=url)
    try:
        assert reopened.get_request("+919876543212", "android-device-0004")["status"] == "APPROVED"
        assert reopened.get_marketing_consent("+919876543212")["marketing_status"] == "OPTED_IN"
    finally:
        reopened.close()


def test_sqlite_migration_is_idempotent_and_preserves_all_customer_rows(customer_store):
    url = os.environ["AIR_TEST_CUSTOMER_DATABASE_URL"]
    with tempfile.TemporaryDirectory() as directory:
        source_path = str(Path(directory) / "legacy-auth.sqlite3")
        source = sqlite3.connect(source_path)
        source.executescript("""
            CREATE TABLE air_access_requests(
                request_id TEXT PRIMARY KEY,mobile_e164 TEXT NOT NULL,device_id TEXT NOT NULL,
                status TEXT NOT NULL,created_at TEXT NOT NULL,reviewed_at TEXT,reviewer_note TEXT,
                UNIQUE(mobile_e164,device_id));
            CREATE TABLE air_device_sessions(
                session_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,active INTEGER NOT NULL,
                created_at TEXT NOT NULL);
            CREATE TABLE air_customer_subscriptions(
                customer_id TEXT PRIMARY KEY,plan_code TEXT NOT NULL,starts_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE air_customer_marketing_preferences(
                customer_id TEXT PRIMARY KEY,promotional_consent INTEGER NOT NULL,
                consent_updated_at TEXT,updated_at TEXT NOT NULL);
            CREATE TABLE air_marketing_offers(
                offer_id TEXT PRIMARY KEY,name TEXT NOT NULL,offer_code TEXT NOT NULL UNIQUE,
                plan_code TEXT NOT NULL,discount_percent REAL NOT NULL,starts_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,terms TEXT NOT NULL,status TEXT NOT NULL,
                created_by TEXT NOT NULL,approved_by TEXT,created_at TEXT NOT NULL,approved_at TEXT);
            CREATE TABLE air_marketing_audit(
                event_id TEXT PRIMARY KEY,actor_customer_id TEXT NOT NULL,action TEXT NOT NULL,
                target_id TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL);
        """)
        source.execute("INSERT INTO air_access_requests VALUES(?,?,?,?,?,?,?)",
                       ("request-1", "+919876543213", "legacy-device-0001", "APPROVED",
                        "2026-01-01 00:00:00", "2026-01-01 00:01:00", "legacy approval"))
        source.execute("INSERT INTO air_device_sessions VALUES(?,?,?,?)",
                       ("session-1", "request-1", 1, "2026-01-01 00:02:00"))
        source.execute("INSERT INTO air_customer_subscriptions VALUES(?,?,?,?,?,?)",
                       ("+919876543213", "MONTHLY", "2026-01-01T00:00:00+00:00",
                        "2026-02-01T00:00:00+00:00", "CANCELLED", "2026-01-02 00:00:00"))
        source.execute("INSERT INTO air_customer_marketing_preferences VALUES(?,?,?,?)",
                       ("+919876543213", 0, "2026-01-02 00:00:00", "2026-01-02 00:00:00"))
        source.execute("INSERT INTO air_marketing_offers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("offer-1", "Legacy offer", "LEGACY10", "MONTHLY", 10,
                        "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00",
                        "Terms", "REVOKED", "admin-1", "root-1", "2026-01-01 00:00:00",
                        "2026-01-01 00:01:00"))
        source.execute("INSERT INTO air_marketing_audit VALUES(?,?,?,?,?,?)",
                       ("event-1", "admin-1", "OFFER_REVOKED", "offer-1", "Legacy event",
                        "2026-01-01 00:01:00"))
        source.commit()
        source.close()

        first = migrate(source_path, url)
        second = migrate(source_path, url)
        assert first == second
        assert first["air_access_requests"] == 1
        assert first["air_device_sessions"] == 1
        assert first["air_customer_subscriptions"] == 1
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                assert conn.execute(text("SELECT COUNT(*) FROM air_access_requests WHERE request_id='request-1'")).scalar_one() == 1
                assert conn.execute(text("SELECT active FROM air_device_sessions WHERE session_id='session-1'")).scalar_one() is True
                assert conn.execute(text("SELECT promotional_consent FROM air_customer_marketing_preferences WHERE customer_id='+919876543213'")).scalar_one() is False
                assert conn.execute(text("SELECT status FROM air_marketing_offers WHERE offer_id='offer-1'")).scalar_one() == "REVOKED"
                assert conn.execute(text("SELECT COUNT(*) FROM air_marketing_audit WHERE event_id='event-1'")).scalar_one() == 1
        finally:
            engine.dispose()
