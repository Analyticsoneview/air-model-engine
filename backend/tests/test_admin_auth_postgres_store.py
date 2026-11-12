"""Runtime integration tests for PostgresAdminAuthStore.

Run against a disposable PostgreSQL database after Alembic upgrade head.
Set AIR_TEST_ADMIN_DATABASE_URL. Set AIR_TEST_ADMIN_REDIS_URL to exercise
real Redis; omitting it exercises the supported PostgreSQL-only mode.
"""
import base64
import hashlib
import hmac
import os
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

import app.admin_auth_postgres as admin_auth_postgres
from app.admin_auth_postgres import PostgresAdminAuthStore


class MemoryRedis:
    """Deterministic Redis substitute for local runs without a Redis service."""

    def __init__(self):
        self.values = {}
        self.sets = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = str(value)

    def incr(self, key):
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = str(value)
        return value

    def expire(self, key, ttl):
        return key in self.values

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

    def flushdb(self):
        self.values.clear()
        self.sets.clear()

    def close(self):
        pass


def _totp(secret: str, timestamp: int) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    counter = timestamp // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000
    return f"{value:06d}"


def _clear_database(url: str):
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            for table in ("air_admin_audit", "air_admin_login_limits", "air_admin_sessions", "air_admin_users"):
                conn.execute(text(f"DELETE FROM {table}"))
    finally:
        engine.dispose()


def _make_store(monkeypatch, redis_enabled: bool):
    url = os.getenv("AIR_TEST_ADMIN_DATABASE_URL")
    if not url:
        pytest.skip("AIR_TEST_ADMIN_DATABASE_URL not configured")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("AIR_TEST_ADMIN_DATABASE_URL must be PostgreSQL")

    monkeypatch.setenv("AIR_ADMIN_MFA_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("AIR_REDIS_URL", raising=False)
    monkeypatch.delenv("AIR_REDIS_URL_FILE", raising=False)
    _clear_database(url)

    store = PostgresAdminAuthStore(database_url=url, redis_url="")
    if redis_enabled:
        redis_url = os.getenv("AIR_TEST_ADMIN_REDIS_URL")
        if redis_url:
            from redis import Redis
            store.redis = Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
            store.redis.ping()
            store.redis.flushdb()
        else:
            store.redis = MemoryRedis()
    else:
        store.redis = None
    return store


def _cleanup_store(store):
    url = os.getenv("AIR_TEST_ADMIN_DATABASE_URL")
    try:
        if store.redis is not None and hasattr(store.redis, "flushdb"):
            store.redis.flushdb()
    finally:
        store.close()
        if url:
            _clear_database(url)


@pytest.fixture
def admin_store(monkeypatch):
    store = _make_store(monkeypatch, redis_enabled=True)
    try:
        yield store
    finally:
        _cleanup_store(store)


@pytest.fixture
def admin_store_without_redis(monkeypatch):
    store = _make_store(monkeypatch, redis_enabled=False)
    try:
        yield store
    finally:
        _cleanup_store(store)


def _provision_admin(store, root_id: str, email: str, role: str = "ADMIN"):
    credentials, otp_uri = store.create_admin(
        {"admin_id": root_id, "role": "SUPER_ADMIN"}, email, role
    )
    secret = parse_qs(urlparse(otp_uri).query)["secret"][0]
    return credentials, secret


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


def test_concurrent_bootstrap_creates_exactly_one_super_admin(admin_store):
    barrier = threading.Barrier(2)

    def bootstrap(index):
        barrier.wait(timeout=10)
        try:
            return admin_store.bootstrap(f"root{index}@example.com", "Long-Strong-Password-123!")
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(bootstrap, (1, 2)))

    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(isinstance(result, str) and "already complete" in result for result in results) == 1
    with admin_store.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM air_admin_users WHERE role='SUPER_ADMIN' AND is_active=true")).scalar_one() == 1


def test_concurrent_totp_replay_allows_only_one_login(admin_store, monkeypatch):
    admin_id, secret = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    code = _totp(secret, now)
    barrier = threading.Barrier(2)
    original = admin_auth_postgres.matching_totp_counter

    def synchronized_counter(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(admin_auth_postgres, "matching_totp_counter", synchronized_counter)

    def login(index):
        return admin_store.authenticate("root@example.com", "Long-Strong-Password-123!", code,
                                         rate_key=f"root|parallel-{index}", now=now)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(login, (1, 2)))

    successes = [result for result in results if result is not None]
    assert len(successes) == 1
    assert successes[0]["admin_id"] == admin_id


def test_postgres_admin_successful_login_resets_redis_throttle(admin_store):
    admin_id, secret = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    rate_key = "root|redis-reset"
    for _ in range(4):
        assert admin_store.authenticate("root@example.com", "wrong-password-123", "000000",
                                        rate_key=rate_key, now=now) is None

    key = admin_store._limit_key(rate_key)
    assert admin_store.redis.get("air:admin:fail:" + key) == "4"
    login = admin_store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                     _totp(secret, now), rate_key=rate_key, now=now)
    assert login and login["admin_id"] == admin_id

    # The next bad attempt must start at one, not inherit the four old failures.
    assert admin_store.authenticate("root@example.com", "wrong-password-123", "000000",
                                    rate_key=rate_key, now=now) is None
    assert admin_store.redis.get("air:admin:lock:" + key) is None
    assert admin_store.redis.get("air:admin:fail:" + key) == "1"
    with admin_store.engine.connect() as conn:
        assert conn.execute(text("SELECT 1 FROM air_admin_login_limits WHERE rate_key=:key"),
                            {"key": key}).first() is None


def test_postgres_only_mode_enforces_and_resets_database_lockout(admin_store_without_redis):
    store = admin_store_without_redis
    admin_id, secret = store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    rate_key = "root|database-lockout"
    now = 1_800_000_000

    for _ in range(5):
        assert store.authenticate("root@example.com", "wrong-password-123", "000000",
                                  rate_key=rate_key, now=now) is None
    assert store.authenticate("root@example.com", "Long-Strong-Password-123!", _totp(secret, now),
                              rate_key=rate_key, now=now) is None

    # The 15-minute lock expires; a successful login clears the PostgreSQL counter.
    unlocked_at = now + 901
    login = store.authenticate("root@example.com", "Long-Strong-Password-123!", _totp(secret, unlocked_at),
                               rate_key=rate_key, now=unlocked_at)
    assert login and login["admin_id"] == admin_id
    assert store.authenticate("root@example.com", "wrong-password-123", "000000",
                              rate_key=rate_key, now=unlocked_at) is None
    key = store._limit_key(rate_key)
    with store.engine.connect() as conn:
        row = conn.execute(text("SELECT failures,locked_until FROM air_admin_login_limits WHERE rate_key=:key"),
                           {"key": key}).mappings().one()
    assert row["failures"] == 1
    assert row["locked_until"] == 0


def test_session_expiry_is_enforced_by_postgres_with_redis_enabled(admin_store):
    _, secret = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    login = admin_store.authenticate("root@example.com", "Long-Strong-Password-123!", _totp(secret, now),
                                     rate_key="root|expiry-redis", now=now)
    assert login and admin_store.redis.get("air:admin:session:" + login["session_id"])

    with admin_store.engine.begin() as conn:
        conn.execute(text("""UPDATE air_admin_sessions
            SET expires_at=CURRENT_TIMESTAMP - INTERVAL '1 second'
            WHERE session_id=:sid"""), {"sid": login["session_id"]})

    assert admin_store.session(login["session_id"]) is None


def test_session_expiry_is_enforced_in_postgres_only_mode(admin_store_without_redis):
    store = admin_store_without_redis
    _, secret = store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    login = store.authenticate("root@example.com", "Long-Strong-Password-123!", _totp(secret, now),
                               rate_key="root|expiry-db", now=now)
    assert login and store.session(login["session_id"]) is not None

    with store.engine.begin() as conn:
        conn.execute(text("""UPDATE air_admin_sessions
            SET expires_at=CURRENT_TIMESTAMP - INTERVAL '1 second'
            WHERE session_id=:sid"""), {"sid": login["session_id"]})

    assert store.session(login["session_id"]) is None


def test_explicit_session_revocation_clears_redis_and_database(admin_store):
    _, secret = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    login = admin_store.authenticate("root@example.com", "Long-Strong-Password-123!", _totp(secret, now),
                                     rate_key="root|revoke", now=now)
    sid = login["session_id"]
    assert admin_store.redis.get("air:admin:session:" + sid)
    admin_store.revoke(sid)
    assert admin_store.redis.get("air:admin:session:" + sid) is None
    assert admin_store.session(sid) is None


def test_password_rotation_revokes_other_sessions(admin_store):
    admin_id, secret = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    now = 1_800_000_000
    first = admin_store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                     _totp(secret, now), rate_key="root|password-1", now=now)
    second = admin_store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                      _totp(secret, now + 30), rate_key="root|password-2", now=now + 30)
    assert first and second and first["admin_id"] == admin_id
    admin_store.change_password(first, "Long-Strong-Password-123!", "New-Strong-Password-456!")
    assert admin_store.session(first["session_id"])["must_change_password"] is False
    assert admin_store.session(second["session_id"]) is None


def test_last_super_admin_cannot_be_deactivated_or_demoted(admin_store):
    admin_id, _ = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    actor = {"admin_id": "different-super-admin-actor", "role": "SUPER_ADMIN"}
    with pytest.raises(ValueError, match="At least one active Super Admin"):
        admin_store.set_admin_status(actor, admin_id, False)
    with pytest.raises(ValueError, match="At least one active Super Admin"):
        admin_store.set_admin_role(actor, admin_id, "ADMIN")


def test_admin_deactivation_revokes_sessions(admin_store):
    root_id, _ = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    credentials, secret = _provision_admin(admin_store, root_id, "operator@example.com")
    now = 1_800_000_000
    login = admin_store.authenticate(credentials["email"], credentials["temporary_password"], _totp(secret, now),
                                     rate_key="operator|status", now=now)
    sid = login["session_id"]
    assert admin_store.session(sid) is not None

    assert admin_store.set_admin_status({"admin_id": root_id, "role": "SUPER_ADMIN"}, credentials["admin_id"], False)
    assert admin_store.session(sid) is None
    assert admin_store.redis.get("air:admin:session:" + sid) is None


def test_admin_role_change_revokes_sessions_and_updates_next_login_role(admin_store):
    root_id, _ = admin_store.bootstrap("root@example.com", "Long-Strong-Password-123!")
    credentials, secret = _provision_admin(admin_store, root_id, "research@example.com")
    now = 1_800_000_000
    first = admin_store.authenticate(credentials["email"], credentials["temporary_password"], _totp(secret, now),
                                     rate_key="research|first", now=now)
    assert first and first["role"] == "ADMIN"

    assert admin_store.set_admin_role({"admin_id": root_id, "role": "SUPER_ADMIN"},
                                      credentials["admin_id"], "RESEARCH_ADMIN")
    assert admin_store.session(first["session_id"]) is None

    second = admin_store.authenticate(credentials["email"], credentials["temporary_password"], _totp(secret, now + 30),
                                       rate_key="research|second", now=now + 30)
    assert second and second["role"] == "RESEARCH_ADMIN"
