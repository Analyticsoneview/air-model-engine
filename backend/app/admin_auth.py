"""Role-based AIR administrator authentication with TOTP MFA, lockouts and audit trail."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import struct
import time
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from cryptography.fernet import Fernet
from app.security import hash_password, verify_password

ROLES = {"SUPER_ADMIN", "ADMIN", "RESEARCH_ADMIN"}


class AdminAuthStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3")
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_admin_users(
            admin_id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,mfa_secret BLOB NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('SUPER_ADMIN','ADMIN','RESEARCH_ADMIN')),
            is_active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_totp_counter INTEGER NOT NULL DEFAULT -1, must_change_password INTEGER NOT NULL DEFAULT 0, failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0)""")
        self._ensure_column("air_admin_users", "last_totp_counter", "INTEGER NOT NULL DEFAULT -1")
        self._ensure_column("air_admin_users", "must_change_password", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("air_admin_users", "failed_attempts", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("air_admin_users", "locked_until", "INTEGER NOT NULL DEFAULT 0")
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_admin_sessions(
            session_id TEXT PRIMARY KEY,admin_id TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_admin_login_limits(
            rate_key TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
            window_started INTEGER NOT NULL, locked_until INTEGER NOT NULL DEFAULT 0)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_admin_audit(
            event_id TEXT PRIMARY KEY,actor_admin_id TEXT,action TEXT NOT NULL,
            target_admin_id TEXT,details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.db.commit()
        key_file = os.getenv("AIR_ADMIN_MFA_KEY_FILE")
        key = Path(key_file).read_bytes().strip() if key_file else os.getenv("AIR_ADMIN_MFA_KEY", "").encode()
        if not key:
            raise RuntimeError("AIR_ADMIN_MFA_KEY_FILE must contain a Fernet key")
        self.cipher = Fernet(key)

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        cols = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _audit(self, actor: str | None, action: str, target: str | None, details: str = "") -> None:
        self.db.execute("INSERT INTO air_admin_audit(event_id,actor_admin_id,action,target_admin_id,details) VALUES(?,?,?,?,?)",
                        (str(uuid4()), actor, action, target, details[:500]))

    def bootstrap(self, email: str, password: str, secret: str | None = None) -> tuple[str, str]:
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("A valid administrator email is required")
        if self.db.execute("SELECT 1 FROM air_admin_users LIMIT 1").fetchone():
            raise ValueError("Administrator bootstrap is already complete")
        secret = secret or base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        admin_id = str(uuid4())
        with self.db:
            self.db.execute("INSERT INTO air_admin_users(admin_id,email,password_hash,mfa_secret,role) VALUES(?,?,?,?,?)",
                            (admin_id, email, hash_password(password), self.cipher.encrypt(secret.encode()), "SUPER_ADMIN"))
            self._audit(admin_id, "BOOTSTRAP_SUPER_ADMIN", admin_id, email)
        return admin_id, secret

    def _login_limit(self, rate_key: str, now: int) -> bool:
        row = self.db.execute("SELECT * FROM air_admin_login_limits WHERE rate_key=?", (rate_key,)).fetchone()
        return bool(row and row["locked_until"] > now)

    def _record_login_failure(self, rate_key: str, now: int) -> None:
        with self.db:
            row = self.db.execute("SELECT * FROM air_admin_login_limits WHERE rate_key=?", (rate_key,)).fetchone()
            if not row or now - row["window_started"] >= 900:
                self.db.execute("INSERT OR REPLACE INTO air_admin_login_limits(rate_key,failures,window_started,locked_until) VALUES(?,?,?,0)",
                                (rate_key, 1, now))
            else:
                failures = row["failures"] + 1
                locked = now + 900 if failures >= 5 else 0
                self.db.execute("UPDATE air_admin_login_limits SET failures=?,locked_until=? WHERE rate_key=?",
                                (failures, locked, rate_key))

    def authenticate(self, email: str, password: str, code: str, rate_key: str = "unknown",
                     now: int | None = None) -> dict | None:
        current = int(time.time() if now is None else now)
        key = hashlib.sha256(rate_key.encode("utf-8")).hexdigest()
        if self._login_limit(key, current):
            return None
        row = self.db.execute("SELECT * FROM air_admin_users WHERE email=? AND is_active=1",
                              (email.strip().lower(),)).fetchone()
        valid_password = bool(row and verify_password(password, row["password_hash"]))
        matched_counter = None
        if valid_password:
            secret = self.cipher.decrypt(row["mfa_secret"]).decode()
            matched_counter = matching_totp_counter(secret, code, current)
        if not row or not valid_password or matched_counter is None or matched_counter <= row["last_totp_counter"] or row["locked_until"] > current:
            self._record_login_failure(key, current)
            return None
        sid = str(uuid4())
        with self.db:
            self.db.execute("UPDATE air_admin_users SET last_totp_counter=?,failed_attempts=0,locked_until=0 WHERE admin_id=?",
                            (matched_counter, row["admin_id"]))
            self.db.execute("DELETE FROM air_admin_login_limits WHERE rate_key=?", (key,))
            self.db.execute("INSERT INTO air_admin_sessions(session_id,admin_id) VALUES(?,?)", (sid, row["admin_id"]))
            self._audit(row["admin_id"], "LOGIN_SUCCESS", row["admin_id"], "")
        return {"admin_id": row["admin_id"], "email": row["email"], "role": row["role"], "session_id": sid, "must_change_password": bool(row["must_change_password"])}

    def create_admin(self, actor: dict, email: str, role: str) -> tuple[dict, str]:
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("A valid administrator email is required")
        if role not in {"ADMIN", "RESEARCH_ADMIN"}:
            raise ValueError("Only ADMIN or RESEARCH_ADMIN can be provisioned")
        if actor["role"] != "SUPER_ADMIN":
            raise PermissionError("Only SUPER_ADMIN can create administrator accounts")
        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        admin_id = str(uuid4())
        temporary_password = secrets.token_urlsafe(24)
        with self.db:
            self.db.execute("INSERT INTO air_admin_users(admin_id,email,password_hash,mfa_secret,role,must_change_password) VALUES(?,?,?,?,?,1)",
                            (admin_id, email, hash_password(temporary_password), self.cipher.encrypt(secret.encode()), role))
            self._audit(actor["admin_id"], "ADMIN_CREATED", admin_id, f"{email};{role}")
        uri = f"otpauth://totp/{quote('AIR')}:{quote(email)}?secret={secret}&issuer=AIR&algorithm=SHA1&digits=6&period=30"
        return {"admin_id": admin_id, "email": email, "role": role, "active": True,
                "temporary_password": temporary_password}, uri

    def change_password(self, admin: dict, current_password: str, new_password: str) -> None:
        row = self.db.execute("SELECT password_hash FROM air_admin_users WHERE admin_id=? AND is_active=1",
                              (admin["admin_id"],)).fetchone()
        if not row or not verify_password(current_password, row["password_hash"]):
            raise PermissionError("Current administrator password is incorrect")
        encoded = hash_password(new_password)
        with self.db:
            self.db.execute("UPDATE air_admin_users SET password_hash=?,must_change_password=0 WHERE admin_id=?",
                            (encoded, admin["admin_id"]))
            self.db.execute("UPDATE air_admin_sessions SET active=0 WHERE admin_id=? AND session_id<>?",
                            (admin["admin_id"], admin["session_id"]))
            self._audit(admin["admin_id"], "PASSWORD_CHANGED", admin["admin_id"], "")

    def list_admins(self) -> list[dict]:
        rows = self.db.execute("SELECT admin_id,email,role,is_active,must_change_password,created_at FROM air_admin_users ORDER BY created_at,email").fetchall()
        return [dict(r) for r in rows]

    def set_admin_status(self, actor: dict, target_id: str, active: bool) -> bool:
        if actor["role"] != "SUPER_ADMIN":
            raise PermissionError("Only SUPER_ADMIN can change administrator status")
        row = self.db.execute("SELECT role FROM air_admin_users WHERE admin_id=?", (target_id,)).fetchone()
        if not row:
            return False
        if target_id == actor["admin_id"] and not active:
            raise ValueError("You cannot deactivate your own active Super Admin account")
        if row["role"] == "SUPER_ADMIN" and active is False:
            count = self.db.execute("SELECT COUNT(*) FROM air_admin_users WHERE role='SUPER_ADMIN' AND is_active=1").fetchone()[0]
            if count <= 1:
                raise ValueError("At least one active Super Admin must remain")
        with self.db:
            self.db.execute("UPDATE air_admin_users SET is_active=? WHERE admin_id=?", (int(active), target_id))
            if not active:
                self.db.execute("UPDATE air_admin_sessions SET active=0 WHERE admin_id=?", (target_id,))
            self._audit(actor["admin_id"], "ADMIN_ACTIVATED" if active else "ADMIN_DEACTIVATED", target_id)
        return True

    def set_admin_role(self, actor: dict, target_id: str, role: str) -> bool:
        if actor["role"] != "SUPER_ADMIN":
            raise PermissionError("Only SUPER_ADMIN can change administrator roles")
        if role not in ROLES:
            raise ValueError("Unsupported administrator role")
        row = self.db.execute("SELECT role FROM air_admin_users WHERE admin_id=?", (target_id,)).fetchone()
        if not row:
            return False
        if row["role"] == "SUPER_ADMIN" and role != "SUPER_ADMIN":
            count = self.db.execute("SELECT COUNT(*) FROM air_admin_users WHERE role='SUPER_ADMIN' AND is_active=1").fetchone()[0]
            active = self.db.execute("SELECT is_active FROM air_admin_users WHERE admin_id=?", (target_id,)).fetchone()[0]
            if active and count <= 1:
                raise ValueError("At least one active Super Admin must remain")
        with self.db:
            self.db.execute("UPDATE air_admin_users SET role=? WHERE admin_id=?", (role, target_id))
            self.db.execute("UPDATE air_admin_sessions SET active=0 WHERE admin_id=?", (target_id,))
            self._audit(actor["admin_id"], "ADMIN_ROLE_CHANGED", target_id, role)
        return True

    def audit_events(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute("""SELECT event_id,actor_admin_id,action,target_admin_id,details,created_at
            FROM air_admin_audit ORDER BY created_at DESC,rowid DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def session(self, session_id: str):
        return self.db.execute("""SELECT u.admin_id,u.email,u.role,u.must_change_password FROM air_admin_sessions s
            JOIN air_admin_users u ON u.admin_id=s.admin_id
            WHERE s.session_id=? AND s.active=1 AND u.is_active=1""", (session_id,)).fetchone()

    def revoke(self, session_id: str) -> None:
        with self.db:
            self.db.execute("UPDATE air_admin_sessions SET active=0 WHERE session_id=?", (session_id,))

    def close(self):
        self.db.close()


def matching_totp_counter(secret: str, code: str, now: int | None = None) -> int | None:
    if len(code) != 6 or not code.isdigit():
        return None
    try:
        key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8), casefold=True)
    except Exception:
        return None
    counter = int((now if now is not None else time.time()) // 30)
    for step in (0, -1, 1):
        candidate = counter + step
        if candidate < 0:
            continue
        digest = hmac.new(key, struct.pack(">Q", candidate), hashlib.sha1).digest()
        offset = digest[-1] & 15
        value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000
        if hmac.compare_digest(f"{value:06d}", code):
            return candidate
    return None


def verify_totp(secret: str, code: str, now: int | None = None) -> bool:
    return matching_totp_counter(secret, code, now) is not None


_admin_store = None

def get_admin_auth_store() -> AdminAuthStore:
    global _admin_store
    if _admin_store is None:
        _admin_store = AdminAuthStore()
    return _admin_store
