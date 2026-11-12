import base64
import hashlib
import hmac
import struct

import pytest
from cryptography.fernet import Fernet

from app.admin_auth import AdminAuthStore, matching_totp_counter, verify_totp


def _totp(secret: str, timestamp: int) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    counter = timestamp // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000
    return f"{value:06d}"


def test_totp_accepts_current_code_and_clock_skew():
    secret = "JBSWY3DPEHPK3PXP"
    assert verify_totp(secret, _totp(secret, 1_800_000_000), now=1_800_000_000)
    assert verify_totp(secret, _totp(secret, 1_800_000_000), now=1_800_000_030)


def test_totp_rejects_invalid_codes():
    assert not verify_totp("JBSWY3DPEHPK3PXP", "12345", now=1_800_000_000)
    assert not verify_totp("JBSWY3DPEHPK3PXP", "abcdef", now=1_800_000_000)


def test_matching_totp_counter_returns_counter_not_boolean():
    secret = "JBSWY3DPEHPK3PXP"
    assert matching_totp_counter(secret, _totp(secret, 1_800_000_000), now=1_800_000_000) == 60_000_000


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("AIR_ADMIN_MFA_KEY", Fernet.generate_key().decode())
    store = AdminAuthStore(str(tmp_path / "admins.sqlite3"))
    return store


def test_admin_login_rejects_totp_replay_and_throttles(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    try:
        admin_id, secret = store.bootstrap("root@example.com", "Long-Strong-Password-123!")
        now = 1_800_000_000
        code = _totp(secret, now)
        first = store.authenticate("root@example.com", "Long-Strong-Password-123!", code,
                                   rate_key="root|127.0.0.1", now=now)
        assert first and first["admin_id"] == admin_id
        assert store.authenticate("root@example.com", "Long-Strong-Password-123!", code,
                                  rate_key="root|127.0.0.1", now=now) is None
        for _ in range(5):
            store.authenticate("root@example.com", "wrong-password-123", "000000",
                               rate_key="attacker|127.0.0.1", now=now)
        assert store.authenticate("root@example.com", "Long-Strong-Password-123!", code,
                                  rate_key="attacker|127.0.0.1", now=now) is None
    finally:
        store.close()


def test_super_admin_can_provision_and_disable_research_admin(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    try:
        root_id, _ = store.bootstrap("root@example.com", "Long-Strong-Password-123!")
        actor = {"admin_id": root_id, "role": "SUPER_ADMIN"}
        created, uri = store.create_admin(actor, "research@example.com", "RESEARCH_ADMIN")
        assert created["role"] == "RESEARCH_ADMIN"
        created_row = next(row for row in store.list_admins() if row["admin_id"] == created["admin_id"])
        assert created_row["must_change_password"] == 1
        assert "otpauth://totp/" in uri
        assert store.set_admin_status(actor, created["admin_id"], False)
        assert next(row for row in store.list_admins() if row["admin_id"] == created["admin_id"])["is_active"] == 0
        assert store.audit_events()
    finally:
        store.close()


def test_last_super_admin_cannot_be_deactivated(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    try:
        root_id, _ = store.bootstrap("root@example.com", "Long-Strong-Password-123!")
        actor = {"admin_id": root_id, "role": "SUPER_ADMIN"}
        with pytest.raises(ValueError, match="At least one active Super Admin"):
            store.set_admin_status(actor, root_id, False)
    finally:
        store.close()



def test_password_rotation_revokes_other_sessions(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    try:
        root_id, secret = store.bootstrap("root@example.com", "Long-Strong-Password-123!")
        now = 1_800_000_000
        login = store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                   _totp(secret, now), rate_key="root|local", now=now)
        assert login
        other = store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                   _totp(secret, now + 30), rate_key="root|local", now=now + 30)
        assert other
        store.change_password(login, "Long-Strong-Password-123!", "New-Strong-Password-456!")
        assert store.session(login["session_id"])["must_change_password"] == 0
        assert store.session(other["session_id"]) is None
        assert store.authenticate("root@example.com", "New-Strong-Password-456!",
                                  _totp(secret, now + 60), rate_key="root|local", now=now + 60)
    finally:
        store.close()

def test_bootstrap_is_one_time_and_creates_super_admin(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    try:
        admin_id, secret = store.bootstrap("owner@example.com", "Long-Strong-Password-123!")
        assert admin_id and secret
        rows = store.list_admins()
        assert len(rows) == 1
        assert rows[0]["role"] == "SUPER_ADMIN"
        assert rows[0]["must_change_password"] == 0
        with pytest.raises(ValueError, match="bootstrap is already complete"):
            store.bootstrap("second@example.com", "Another-Strong-Password-456!")
    finally:
        store.close()


def test_admin_role_change_revokes_existing_sessions(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    try:
        root_id, _ = store.bootstrap("root@example.com", "Long-Strong-Password-123!")
        actor = {"admin_id": root_id, "role": "SUPER_ADMIN"}
        created, _ = store.create_admin(actor, "analyst@example.com", "RESEARCH_ADMIN")
        sid = "test-session"
        with store.db:
            store.db.execute("INSERT INTO air_admin_sessions(session_id,admin_id) VALUES(?,?)",
                             (sid, created["admin_id"]))
        assert store.set_admin_role(actor, created["admin_id"], "ADMIN")
        assert store.session(sid) is None
    finally:
        store.close()


def test_mfa_rotation_requires_password_and_revokes_existing_sessions(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    try:
        admin_id, old_secret = store.bootstrap("root@example.com", "Long-Strong-Password-123!")
        now = 1_800_000_000
        login = store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                   _totp(old_secret, now), rate_key="root|local", now=now)
        assert login
        new_secret = base64.b32encode(b"0123456789abcdef0123").decode().rstrip("=")
        with pytest.raises(PermissionError):
            store.rotate_mfa_secret("root@example.com", "incorrect-password", new_secret)
        store.rotate_mfa_secret("root@example.com", "Long-Strong-Password-123!", new_secret)
        assert store.session(login["session_id"]) is None
        assert store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                  _totp(old_secret, now + 30), rate_key="root|new", now=now + 30) is None
        new_login = store.authenticate("root@example.com", "Long-Strong-Password-123!",
                                       _totp(new_secret, now + 30), rate_key="root|new", now=now + 30)
        assert new_login and new_login["admin_id"] == admin_id
    finally:
        store.close()
