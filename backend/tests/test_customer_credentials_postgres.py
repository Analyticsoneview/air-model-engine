"""PostgreSQL customer credential-store integration tests.

Run after Alembic upgrade head with AIR_TEST_CUSTOMER_DATABASE_URL configured.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from app.auth_store import AuthStore
from app.customer_credentials_postgres import PostgresAuthStore


def _test_database_url() -> str:
    url = os.getenv("AIR_TEST_CUSTOMER_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("AIR_TEST_CUSTOMER_DATABASE_URL not configured")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("AIR_TEST_CUSTOMER_DATABASE_URL must point to PostgreSQL")
    if "test" not in url.rsplit("/", 1)[-1].lower():
        pytest.fail("Customer credential integration requires a disposable test database")
    return url


def test_postgres_auth_store_round_trip_and_case_insensitive_email(monkeypatch):
    url = _test_database_url()
    customer_id = "credential-test-" + uuid.uuid4().hex
    email = customer_id + "@example.test"
    monkeypatch.setenv("AIR_CUSTOMER_DATABASE_URL", url)
    monkeypatch.delenv("AIR_CUSTOMER_DATABASE_URL_FILE", raising=False)

    store = AuthStore()
    engine = create_engine(url)
    try:
        assert isinstance(store, PostgresAuthStore)
        store.create_customer(customer_id, email.upper(), "argon2id-test-hash")
        row = store.get_by_email(email.swapcase())
        assert row is not None
        assert row["customer_id"] == customer_id
        assert row["email"] == email
        assert row["password_hash"] == "argon2id-test-hash"
        assert store.is_active(customer_id)

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE customers SET is_active=false WHERE customer_id=:id"),
                {"id": customer_id},
            )
        assert not store.is_active(customer_id)
        assert store.get_by_email(email)["is_active"] is False
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM customers WHERE customer_id=:id"), {"id": customer_id})
        store.close()
        engine.dispose()


def test_postgres_auth_store_rejects_duplicate_email_case_insensitively(monkeypatch):
    url = _test_database_url()
    customer_a = "credential-test-" + uuid.uuid4().hex
    customer_b = "credential-test-" + uuid.uuid4().hex
    email = customer_a + "@example.test"
    monkeypatch.setenv("AIR_CUSTOMER_DATABASE_URL", url)
    monkeypatch.delenv("AIR_CUSTOMER_DATABASE_URL_FILE", raising=False)
    store = AuthStore()
    engine = create_engine(url)
    try:
        store.create_customer(customer_a, email, "hash-a")
        with pytest.raises(Exception):
            store.create_customer(customer_b, email.upper(), "hash-b")
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM customers WHERE customer_id IN (:a,:b)"),
                {"a": customer_a, "b": customer_b},
            )
        store.close()
        engine.dispose()
