"""SQLite parity and optional PostgreSQL integration tests for customer auth/access."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.auth_store import AuthStore
from app.access_control import AccessStore
from app.customer_auth_postgres import PostgresAuthStore, PostgresAccessStore
from app.scripts.migrate_customer_auth_sqlite_to_postgres import migrate


class CustomerAuthAccessSQLiteTests(unittest.TestCase):
    def test_customer_auth_store_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AuthStore(str(Path(temp) / "auth.sqlite3"))
            store.create_customer("cust-1", "User@Example.com", "hash")
            row = store.get_by_email("user@example.com")
            self.assertEqual(row["customer_id"], "cust-1")
            self.assertTrue(store.is_active("cust-1"))
            self.assertFalse(store.is_active("missing"))
            store.close()

    def test_device_access_contract_and_revocation(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccessStore(str(Path(temp) / "auth.sqlite3"))
            request = store.request_access("+14155550123", "device-identifier-0001")
            self.assertEqual(request["status"], "PENDING")
            with self.assertRaises(PermissionError):
                store.create_session(request["request_id"])
            self.assertTrue(store.review(request["request_id"], "APPROVED"))
            session_id = store.create_session(request["request_id"])
            self.assertTrue(store.is_session_active(session_id))
            self.assertEqual(store.mobile_for_request_id(request["request_id"]), "+14155550123")
            self.assertTrue(store.review(request["request_id"], "BLOCKED", "revoked"))
            self.assertFalse(store.is_session_active(session_id))
            self.assertEqual(len(store.list_requests("BLOCKED")), 1)
            store.close()


def _source_db(path: Path):
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE customers(customer_id TEXT PRIMARY KEY,email TEXT,password_hash TEXT,is_active INTEGER,created_at TEXT);
    CREATE TABLE air_access_requests(request_id TEXT PRIMARY KEY,mobile_e164 TEXT,device_id TEXT,status TEXT,created_at TEXT,reviewed_at TEXT,reviewer_note TEXT);
    CREATE TABLE air_device_sessions(session_id TEXT PRIMARY KEY,request_id TEXT,active INTEGER,created_at TEXT);
    """)
    db.execute("INSERT INTO customers VALUES(?,?,?,?,?)", ("cust-1", "user@example.com", "hash", 1, "2026-01-01 00:00:00"))
    db.execute("INSERT INTO air_access_requests VALUES(?,?,?,?,?,?,?)", ("req-1", "+14155550123", "device-0001", "APPROVED", "2026-01-01 00:00:00", "2026-01-01 00:01:00", "approved"))
    db.execute("INSERT INTO air_device_sessions VALUES(?,?,?,?)", ("sid-1", "req-1", 1, "2026-01-01 00:02:00"))
    db.commit()
    db.close()


@pytest.fixture
def postgres_url():
    value = os.getenv("AIR_TEST_CUSTOMER_DATABASE_URL")
    if not value:
        pytest.skip("AIR_TEST_CUSTOMER_DATABASE_URL not configured")
    if not value.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("AIR_TEST_CUSTOMER_DATABASE_URL must be PostgreSQL")
    return value


def test_customer_access_import_reconciles_all_rows(postgres_url, tmp_path):
    source = tmp_path / "source.sqlite3"
    _source_db(source)
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM air_device_sessions"))
            conn.execute(text("DELETE FROM air_access_requests"))
            conn.execute(text("DELETE FROM customers"))
        counts = migrate(str(source), postgres_url)
        assert counts == {"customers": 1, "air_access_requests": 1, "air_device_sessions": 1}
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM customers")).scalar_one() == 1
            assert conn.execute(text("SELECT COUNT(*) FROM air_device_sessions")).scalar_one() == 1
    finally:
        engine.dispose()


def test_customer_access_import_conflict_rolls_back(postgres_url, tmp_path):
    source = tmp_path / "source.sqlite3"
    _source_db(source)
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM air_device_sessions"))
            conn.execute(text("DELETE FROM air_access_requests"))
            conn.execute(text("DELETE FROM customers"))
            conn.execute(text("""INSERT INTO customers(customer_id,email,password_hash,is_active,created_at)
                VALUES('cust-1','user@example.com','different',true,'2026-01-01 00:00:00+00')"""))
        with pytest.raises(RuntimeError, match="Data conflict"):
            migrate(str(source), postgres_url)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM air_access_requests")).scalar_one() == 0
            assert conn.execute(text("SELECT COUNT(*) FROM air_device_sessions")).scalar_one() == 0
    finally:
        engine.dispose()


def test_postgres_store_contract(postgres_url):
    auth = PostgresAuthStore(postgres_url)
    access = PostgresAccessStore(postgres_url)
    customer_id = "pg-test-" + os.urandom(8).hex()
    mobile = "+1415" + "".join(str(x % 10) for x in os.urandom(7))
    device = "pg-test-device-" + os.urandom(6).hex()
    try:
        auth.create_customer(customer_id, f"{customer_id}@example.test", "argon-hash")
        row = auth.get_by_email(f"{customer_id}@example.test")
        assert row["customer_id"] == customer_id
        assert auth.is_active(customer_id)
        request = access.request_access(mobile, device)
        assert request["status"] == "PENDING"
        assert access.mobile_for_request_id(request["request_id"]) == mobile
        assert access.review(request["request_id"], "APPROVED")
        session_id = access.create_session(request["request_id"])
        assert access.is_session_active(session_id)
        assert access.review(request["request_id"], "BLOCKED", "integration test")
        assert not access.is_session_active(session_id)
    finally:
        with auth.engine.begin() as conn:
            conn.execute(text("DELETE FROM customers WHERE customer_id=:id"), {"id": customer_id})
            conn.execute(text("DELETE FROM air_access_requests WHERE mobile_e164=:mobile AND device_id=:device"),
                         {"mobile": mobile, "device": device})
        auth.close()
        access.close()
