"""Runtime integration tests for PostgresAdminAuthStore.

Run against a disposable PostgreSQL database after Alembic upgrade head.
Set AIR_TEST_ADMIN_DATABASE_URL; tests skip when it is absent.
"""
import base64
import hashlib
import hmac
import os
import struct

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

from app.admin_auth_postgres import PostgresAdminAuthStore


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value

    def incr(self, key):
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = str(value)
        return value

    def expire(self, key, ttl):
        return True

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    def smembers(self, key):
        return self.sets.get(key, set()).copy()

    def srem(self, key, *values):
        self.sets.setdefault(key, set()).difference_update(values)

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
            self.sets.pop(key, None)

    def close(self):
        # In-memory fake owns no sockets or external resources.
        pass


def _totp(secret: str, timestamp: int) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    counter = timestamp // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000
    return f"{value:06d}"


@pytest.fixture
def admin_store(monkeypatch):
    url = os.getenv("AIR_TEST_ADMIN_DATABASE_URL")
    if not url:
        pytest.skip("AIR_TEST_ADMIN_DATABASE_URL not configured")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("AIR_TEST_ADMIN_DATABASE_URL must be PostgreSQL")
    monkeypatch.setenv("AIR_ADMIN_MFA_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("AIR_REDIS_URL", raising=False)
    monkeypatch.delenv("AIR_REDIS_URL_FILE", raising=False)
    engine = create_engine(url)
    tables = ("air_admin_audit", "air_admin_login_limits", "air_admin_sessions", "air_admin_users")
    with engine.begin() as conn:
        for table in tables:
            conn.execute(text(f"DELETE FROM {table}"))
    engine.dispose()
    store = PostgresAdminAuthStore(database_url=url, redis_url="")
    store.redis = MemoryRedis()
    try:
        yield store
    finally:
        store.close()
        engine = create_engine(url)
        with engine.begin() as conn:
            for table in tables:
                conn.execute(text(f"DELETE FROM {table}"))
        engine.dispose()


def test_postgres_admin_bootstrap_totp_login_and_replay_rejection(admin_store):
    admin_id, secret = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    code = _totp(secret, now)
    login = admin_store.authenticate("root@example.com", "Long-Strong-Password-123!", code,
                                     rate_key="root|local", now=now)
    assert login and login["admin_id"] == admin_id
    assert admin_store.session(login["session_id"])["role"] == "SUPER_ADMIN"
    assert admin_store.authenticate("root@example.com", "Long-Strong-Password-123!", code,
                                     rate_key="root|local", now=now) is None


def test_postgres_admin_successful_login_resets_redis_throttle(admin_store):
    admin_id, secret = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    rate_key = "root|local"
    for _ in range(4):
        assert admin_store.authenticate("root@example.com", "wrong-password-123", "000000",
                                        rate_key=rate_key, now=now) is None
    login = admin_store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                     _totp(secret, now), rate_key=rate_key, now=now)
    assert login and login["admin_id"] == admin_id
    assert admin_store.authenticate("root@example.com", "wrong-password-123", "000000",
                                    rate_key=rate_key, now=now) is None
    key = admin_store._limit_key(rate_key)
    assert admin_store.redis.get("air:admin:lock:" + key) is None
    assert admin_store.redis.get("air:admin:fail:" + key) == "1"


def test_postgres_admin_password_rotation_revokes_other_sessions(admin_store):
    admin_id, secret = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    first = admin_store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                     _totp(secret, now), rate_key="root|local", now=now)
    second = admin_store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                      _totp(secret, now + 30), rate_key="root|local", now=now + 30)
    assert first and second
    admin_store.change_password(first, "Long-Strong-Password-123!", "New-Strong-Password-456!")
    assert admin_store.session(first["session_id"])["must_change_password"] is False
    assert admin_store.session(second["session_id"]) is None


def test_postgres_admin_logout_revokes_session(admin_store):
    admin_id, secret = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    login = admin_store.authenticate(
        "root@example.com", "Long-Strong-Password-123!", _totp(secret, now),
        rate_key="root|logout", now=now,
    )
    assert login and admin_store.session(login["session_id"]) is not None

    admin_store.revoke(login["session_id"])

    assert admin_store.session(login["session_id"]) is None


def test_postgres_admin_cannot_remove_last_super_admin(admin_store):
    admin_id, _ = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    # Use a distinct authenticated actor identity to reach the invariant checks;
    # self-deactivation is intentionally rejected earlier by the store.
    actor = {"admin_id": "different-super-admin-actor", "role": "SUPER_ADMIN"}
    with pytest.raises(ValueError, match="At least one active Super Admin"):
        admin_store.set_admin_status(actor, admin_id, False)
    with pytest.raises(ValueError, match="At least one active Super Admin"):
        admin_store.set_admin_role(actor, admin_id, "ADMIN")


def test_postgres_admin_cannot_deactivate_own_super_admin_account(admin_store):
    admin_id, _ = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    actor = {"admin_id": admin_id, "role": "SUPER_ADMIN"}
    with pytest.raises(ValueError, match="cannot deactivate your own"):
        admin_store.set_admin_status(actor, admin_id, False)
