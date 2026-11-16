"""Integration coverage for PostgreSQL customer access and marketing storage.

Run after Alembic upgrade head with AIR_TEST_CUSTOMER_DATABASE_URL configured.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, event, text

from app.customer_auth_postgres import PostgresAccessStore
from app.tenant_context import install_tenant_context, tenant_scope
from app.scripts.migrate_customer_sqlite_to_postgres import migrate


TABLES = (
    "air_access_decision_history", "air_customer_subscription_history",
    "air_customer_lifecycle", "air_marketing_audit", "air_marketing_offers",
    "air_customer_marketing_preferences", "air_customer_subscriptions",
    "air_device_sessions", "air_access_requests", "air_tenant_members", "air_tenants",
)


def _database_url():
    url = os.getenv("AIR_TEST_CUSTOMER_DATABASE_URL")
    if not url:
        pytest.skip("AIR_TEST_CUSTOMER_DATABASE_URL not configured")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("AIR_TEST_CUSTOMER_DATABASE_URL must point to PostgreSQL")
    database_name = urlparse(url).path.lstrip("/")
    if "test" not in database_name.lower():
        pytest.fail("Customer integration tests are destructive and require a disposable database with test in its name")
    return url


def _clear_database(url):
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            # TRUNCATE bypasses row-level append-only audit triggers in this disposable test database.
            conn.execute(text("TRUNCATE TABLE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE"))
            # Recreate the system tenant using the same explicit admin context
            # required by FORCE ROW LEVEL SECURITY in production.
            conn.execute(text("SELECT set_config('air.is_admin','true',false)"))
            conn.execute(text("""
                INSERT INTO air_tenants
                    (tenant_id,name,owner_customer_id,plan_code,status,storage_prefix,rabbitmq_vhost,
                     max_members,max_api_calls_per_day,max_storage_bytes)
                VALUES
                    ('00000000-0000-4000-8000-000000000000','AIR System Administration',
                     'AIR_SYSTEM_ADMIN','ENTERPRISE','ACTIVE','system/','air-system-admin',
                     1000,1000000,10737418240)
            """))
            conn.execute(text("""
                INSERT INTO air_tenant_members(tenant_id,customer_id,role,status)
                VALUES('00000000-0000-4000-8000-000000000000',
                       'AIR_SYSTEM_ADMIN','OWNER','ACTIVE')
            """))
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
    assert customer_store.review(request["request_id"], "APPROVED", "Verified by Admin",
                                  reviewer_admin_id="admin-test", reviewer_role="SUPER_ADMIN", totp_counter=60000001)
    session_id = customer_store.create_session(request["request_id"])
    tenant_id = customer_store.tenant_for_customer("+919876543210")
    with tenant_scope(tenant_id=tenant_id, customer_id="+919876543210"):
        assert customer_store.is_session_active(session_id)
    assert customer_store.review(request["request_id"], "BLOCKED", "Access withdrawn",
                                  reviewer_admin_id="admin-test", reviewer_role="SUPER_ADMIN", totp_counter=60000002)
    with tenant_scope(is_admin=True):
        history = customer_store.decision_history(request["request_id"])
    assert [item["new_status"] for item in history] == ["APPROVED", "BLOCKED"]
    assert history[-1]["reviewer_admin_id"] == "admin-test"
    with tenant_scope(tenant_id=tenant_id, customer_id="+919876543210"):
        assert not customer_store.is_session_active(session_id)
    with tenant_scope(is_admin=True):
        assert customer_store.list_requests("BLOCKED")[0]["request_id"] == request["request_id"]


def test_device_deduplication_consent_and_subscription_segmentation(customer_store):
    first = customer_store.request_access("+919876543211", "android-device-0002")
    second = customer_store.request_access("+919876543211", "android-device-0003")
    assert first["request_id"] != second["request_id"]
    with tenant_scope(is_admin=True):
        listed = {row["request_id"]: row for row in customer_store.list_requests()}
    assert listed[first["request_id"]]["customer_type"] == "NEW"
    assert listed[second["request_id"]]["customer_type"] == "EXISTING"
    customer_store.review(first["request_id"], "APPROVED", reviewer_admin_id="admin-test",
                            reviewer_role="SUPER_ADMIN", totp_counter=60000003)
    customer_store.set_marketing_consent("+919876543211", True)
    with tenant_scope(is_admin=True):
        customers = customer_store.list_marketing_customers()
    assert len(customers) == 1
    assert customers[0]["device_count"] == 2
    assert customers[0]["marketing_status"] == "OPTED_IN"
    with tenant_scope(is_admin=True):
        assert customer_store.marketing_segment_counts()["ELIGIBLE_FOR_PROMOTIONS"] == 1

    now = datetime.now(timezone.utc)
    with tenant_scope(is_admin=True):
        customer_store.assign_subscription("+919876543211", "MONTHLY", now.isoformat(),
                                        (now + timedelta(days=30)).isoformat())
    with tenant_scope(is_admin=True):
        assert customer_store.marketing_segment_counts()["ELIGIBLE_FOR_PROMOTIONS"] == 0
        assert customer_store.list_marketing_customers("ACTIVE")[0]["plan_code"] == "MONTHLY"
    customer_store.set_marketing_consent("+919876543211", False)
    with tenant_scope(is_admin=True):
        assert customer_store.list_marketing_customers("OPTED_OUT")[0]["marketing_status"] == "OPTED_OUT"



def test_lifecycle_dates_subscription_history_and_immutable_decision_audit(customer_store):
    first = customer_store.request_access("+919876543299", "lifecycle-device-0001")
    second = customer_store.request_access("+919876543299", "lifecycle-device-0002")
    assert first["request_id"] != second["request_id"]
    assert customer_store.review(
        first["request_id"], "APPROVED", "First approval",
        reviewer_admin_id="admin-lifecycle", reviewer_role="SUPER_ADMIN", totp_counter=70000001,
        verification_reference="verify-lifecycle-0001",
        request_context={"source": "admin-console", "ip": "127.0.0.1"},
    )
    with tenant_scope(is_admin=True):
        history = customer_store.decision_history(first["request_id"])
    assert len(history) == 1
    assert history[0]["reviewer_admin_id"] == "admin-lifecycle"
    assert history[0]["verification_reference"] == "verify-lifecycle-0001"
    assert history[0]["totp_verified_at"] is not None
    assert history[0]["device_id"] == "lifecycle-device-0001"
    assert history[0]["request_context"]["source"] == "admin-console"

    with tenant_scope(is_admin=True):
        customer = customer_store.list_marketing_customers(search="+919876543299")[0]
    assert customer["device_count"] == 2
    assert customer["first_registered_at"] is not None
    assert customer["first_approved_at"] is not None
    assert customer["first_rejected_at"] is None

    now = datetime.now(timezone.utc)
    with tenant_scope(is_admin=True):
        customer_store.assign_subscription("+919876543299", "MONTHLY", now.isoformat(),
                                            (now + timedelta(days=30)).isoformat())
        first_plan_at = customer_store.list_marketing_customers(search="+919876543299")[0]["first_plan_availed_at"]
        customer_store.assign_subscription("+919876543299", "YEARLY", now.isoformat(),
                                            (now + timedelta(days=365)).isoformat())
        refreshed = customer_store.list_marketing_customers(search="+919876543299")[0]
    assert refreshed["first_plan_availed_at"] == first_plan_at
    with tenant_scope(is_admin=True):
        with customer_store.engine.connect() as conn:
            assert conn.execute(text("""SELECT COUNT(*) FROM air_customer_subscription_history
            WHERE customer_id='+919876543299'""")).scalar_one() == 2
    with tenant_scope(is_admin=True):
        with pytest.raises(Exception):
            with customer_store.engine.begin() as conn:
                conn.execute(text("""UPDATE air_access_decision_history SET note='tampered'
                WHERE request_id=:request"""), {"request": first["request_id"]})
    with tenant_scope(is_admin=True):
        with pytest.raises(Exception):
            with customer_store.engine.begin() as conn:
                conn.execute(text("""UPDATE air_customer_subscription_history SET plan_code='DAILY'
                WHERE customer_id='+919876543299'"""))
    with tenant_scope(is_admin=True):
        with pytest.raises(Exception):
            with customer_store.engine.begin() as conn:
                conn.execute(text("""DELETE FROM air_customer_subscription_history
                WHERE customer_id='+919876543299'"""))


def test_offer_requires_approval_and_can_be_revoked(customer_store):
    now = datetime.now(timezone.utc)
    offer = customer_store.create_marketing_offer(
        "Monthly welcome", "WELCOME10", "MONTHLY", 10,
        now.isoformat(), (now + timedelta(days=10)).isoformat(),
        "New customers only", "admin-1",
    )
    assert offer["status"] == "DRAFT"
    with tenant_scope(is_admin=True):
        with customer_store.engine.connect() as conn:
            audit_tenant = conn.execute(text("""
                SELECT tenant_id FROM air_marketing_audit
                WHERE actor_customer_id='admin-1'
                  AND action='MARKETING_OFFER_CREATED'
                  AND target_id=:offer_id
            """), {"offer_id": offer["offer_id"]}).scalar_one()
    assert audit_tenant == "00000000-0000-4000-8000-000000000000"
    approved = customer_store.approve_marketing_offer(offer["offer_id"], "super-admin-1")
    assert approved["status"] == "APPROVED"
    assert customer_store.revoke_marketing_offer(offer["offer_id"], "super-admin-1")
    assert customer_store.get_marketing_offer(offer["offer_id"])["status"] == "REVOKED"


def test_state_persists_after_store_recreation(customer_store):
    request = customer_store.request_access("+919876543212", "android-device-0004")
    customer_store.review(request["request_id"], "APPROVED", reviewer_admin_id="admin-test",
                            reviewer_role="SUPER_ADMIN", totp_counter=60000004)
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
            CREATE TABLE air_access_decision_history(
                decision_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,mobile_e164 TEXT NOT NULL,
                previous_status TEXT NOT NULL,new_status TEXT NOT NULL,reviewer_admin_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL,note TEXT NOT NULL,totp_counter INTEGER NOT NULL,decided_at TEXT NOT NULL);
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
        source.execute("INSERT INTO air_access_decision_history VALUES(?,?,?,?,?,?,?,?,?,?)",
                       ("decision-1", "request-1", "+919876543213", "PENDING", "APPROVED",
                        "admin-1", "SUPER_ADMIN", "legacy approval", 12345, "2026-01-01 00:01:00"))
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
        assert first["air_access_decision_history"] == 1
        assert first["air_device_sessions"] == 1
        assert first["air_customer_subscriptions"] == 1
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                assert conn.execute(text("SELECT COUNT(*) FROM air_access_requests WHERE request_id='request-1'")).scalar_one() == 1
                assert conn.execute(text("SELECT COUNT(*) FROM air_access_decision_history WHERE decision_id='decision-1'")).scalar_one() == 1
                assert conn.execute(text("SELECT totp_verified_at FROM air_access_decision_history WHERE decision_id='decision-1'")).scalar_one() is None
                lifecycle = conn.execute(text("SELECT first_approved_at,first_plan_availed_at FROM air_customer_lifecycle WHERE customer_id='+919876543213'")).one()
                assert lifecycle.first_approved_at.isoformat() == "2026-01-01T00:01:00+00:00"
                assert lifecycle.first_plan_availed_at.isoformat() == "2026-01-02T00:00:00+00:00"
                assert conn.execute(text("SELECT COUNT(*) FROM air_customer_subscription_history WHERE customer_id='+919876543213'")).scalar_one() == 1
                assert conn.execute(text("SELECT active FROM air_device_sessions WHERE session_id='session-1'")).scalar_one() is True
                assert conn.execute(text("SELECT promotional_consent FROM air_customer_marketing_preferences WHERE customer_id='+919876543213'")).scalar_one() is False
                assert conn.execute(text("SELECT status FROM air_marketing_offers WHERE offer_id='offer-1'")).scalar_one() == "REVOKED"
                assert conn.execute(text("SELECT COUNT(*) FROM air_marketing_audit WHERE event_id='event-1'")).scalar_one() == 1
        finally:
            engine.dispose()



def test_postgres_tenant_isolation_survives_pool_reuse_and_concurrent_requests(customer_store):
    """RLS must isolate two tenants on a reused connection and under concurrency."""
    url = os.environ["AIR_TEST_CUSTOMER_DATABASE_URL"]
    customer_a = "+919876543221"
    customer_b = "+919876543222"
    customer_store.request_access(customer_a, "tenant-a-device-0001")
    customer_store.request_access(customer_b, "tenant-b-device-0001")
    tenant_a = customer_store.tenant_for_customer(customer_a)
    tenant_b = customer_store.tenant_for_customer(customer_b)
    assert tenant_a and tenant_b and tenant_a != tenant_b

    # A one-connection pool forces tenant A and tenant B to reuse the same
    # physical PostgreSQL connection. before_cursor_execute must reset all
    # three AIR GUCs before every statement.
    # The CI database owner is a PostgreSQL superuser, which bypasses RLS even
    # with FORCE ROW LEVEL SECURITY. Execute the acceptance checks as a separate
    # least-privilege role so the test actually exercises PostgreSQL policies.
    role_engine = create_engine(url, pool_pre_ping=True)
    try:
        with role_engine.begin() as conn:
            conn.execute(text("""
                DO $role$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='air_tenant_rls_test') THEN
                        CREATE ROLE air_tenant_rls_test NOLOGIN NOSUPERUSER NOCREATEDB
                            NOCREATEROLE NOINHERIT NOBYPASSRLS;
                    END IF;
                END;
                $role$
            """))
            conn.execute(text("ALTER ROLE air_tenant_rls_test NOSUPERUSER NOBYPASSRLS"))
            conn.execute(text("GRANT USAGE ON SCHEMA public TO air_tenant_rls_test"))
            conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO air_tenant_rls_test"))
            conn.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO air_tenant_rls_test"))
    finally:
        role_engine.dispose()

    pooled_engine = create_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    install_tenant_context(pooled_engine)

    def _assume_rls_role(connection, cursor, statement, parameters, context, executemany):
        cursor.execute("SET ROLE air_tenant_rls_test")

    event.listen(pooled_engine, "before_cursor_execute", _assume_rls_role, insert=True)
    try:
        for customer, tenant in ((customer_a, tenant_a), (customer_b, tenant_b)):
            with tenant_scope(tenant_id=tenant, customer_id=customer):
                with pooled_engine.connect() as conn:
                    visible = conn.execute(text(
                        "SELECT DISTINCT mobile_e164 FROM air_access_requests ORDER BY mobile_e164"
                    )).scalars().all()
            assert visible == [customer]

        # Missing tenant context must fail closed for customer-owned rows.
        with tenant_scope():
            with pooled_engine.connect() as conn:
                assert conn.execute(text(
                    "SELECT COUNT(*) FROM air_access_requests"
                )).scalar_one() == 0

        # A tenant cannot create a row for another tenant, even when it knows
        # the other customer's mobile number.
        with tenant_scope(tenant_id=tenant_b, customer_id=customer_b):
            with pytest.raises(Exception, match="tenant context mismatch"):
                with pooled_engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO air_access_requests
                            (request_id,mobile_e164,device_id,status)
                        VALUES ('cross-tenant-write',:customer,'cross-tenant-device','PENDING')
                    """), {"customer": customer_a})
    finally:
        pooled_engine.dispose()

    # Exercise simultaneous tenant scopes on separate pooled connections.
    concurrent_engine = create_engine(url, pool_size=2, max_overflow=0, pool_pre_ping=True)
    install_tenant_context(concurrent_engine)
    event.listen(concurrent_engine, "before_cursor_execute", _assume_rls_role, insert=True)
    barrier = Barrier(2)

    def read_only_tenant(customer: str, tenant: str) -> list[str]:
        observed = []
        with tenant_scope(tenant_id=tenant, customer_id=customer):
            barrier.wait(timeout=10)
            for _ in range(20):
                with concurrent_engine.connect() as conn:
                    rows = conn.execute(text(
                        "SELECT DISTINCT mobile_e164 FROM air_access_requests ORDER BY mobile_e164"
                    )).scalars().all()
                assert rows == [customer]
                observed.extend(rows)
        return observed

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(read_only_tenant, customer_a, tenant_a)
            future_b = executor.submit(read_only_tenant, customer_b, tenant_b)
            assert future_a.result(timeout=30) == [customer_a] * 20
            assert future_b.result(timeout=30) == [customer_b] * 20
    finally:
        concurrent_engine.dispose()
