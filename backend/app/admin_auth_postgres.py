"""PostgreSQL-backed AIR administrator store.

Selected only when AIR_ADMIN_DATABASE_URL is configured. Redis is used for
session state and login throttling when AIR_REDIS_URL is configured. The
SQLite implementation remains available for local compatibility/tests.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from redis import Redis

from app.admin_auth import ROLES, matching_totp_counter
from app.security import hash_password, verify_password


class PostgresAdminAuthStore:
    def __init__(self, database_url: str | None = None, redis_url: str | None = None):
        database_url = database_url or self._secret_setting("AIR_ADMIN_DATABASE_URL")
        if not database_url or not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise RuntimeError("AIR_ADMIN_DATABASE_URL must be configured with PostgreSQL")
        self.engine: Engine = create_engine(database_url, pool_pre_ping=True, future=True)
        redis_url = redis_url or self._secret_setting("AIR_REDIS_URL")
        self.redis = Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3,
                                    socket_timeout=3, health_check_interval=30) if redis_url else None
        key = self._secret_setting("AIR_ADMIN_MFA_KEY")
        if not key:
            raise RuntimeError("AIR_ADMIN_MFA_KEY_FILE or AIR_ADMIN_MFA_KEY is required")
        self.cipher = Fernet(key.encode())

    @staticmethod
    def _secret_setting(name: str) -> str:
        file_name = os.getenv(name + "_FILE")
        return Path(file_name).read_text(encoding="utf-8").strip() if file_name else os.getenv(name, "").strip()

    def _audit(self, conn, actor, action, target, details=""):
        conn.execute(text("""INSERT INTO air_admin_audit(event_id,actor_admin_id,action,target_admin_id,details)
                             VALUES(:event,:actor,:action,:target,:details)"""),
                     {"event": str(uuid4()), "actor": actor, "action": action, "target": target, "details": details[:500]})

    def bootstrap(self, email: str, password: str, secret: str | None = None):
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("A valid administrator email is required")
        secret = secret or base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        admin_id = str(uuid4())
        with self.engine.begin() as conn:
            # Serialize bootstrap and all Super Admin invariant changes.
            conn.execute(text("SELECT pg_advisory_xact_lock(741902611)"))
            if conn.execute(text("SELECT 1 FROM air_admin_users LIMIT 1")).first():
                raise ValueError("Administrator bootstrap is already complete")
            conn.execute(text("""INSERT INTO air_admin_users
                (admin_id,email,password_hash,mfa_secret,role) VALUES
                (:id,:email,:password,:secret,'SUPER_ADMIN')"""),
                {"id": admin_id, "email": email, "password": hash_password(password),
                 "secret": self.cipher.encrypt(secret.encode())})
            self._audit(conn, admin_id, "BOOTSTRAP_SUPER_ADMIN", admin_id, email)
        return admin_id, secret

    def _limit_key(self, rate_key: str) -> str:
        return hashlib.sha256(rate_key.encode()).hexdigest()

    def _login_limit(self, key: str, now: int) -> bool:
        if self.redis is not None:
            return bool(self.redis.get("air:admin:lock:" + key))
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT locked_until FROM air_admin_login_limits WHERE rate_key=:key"),
                               {"key": key}).first()
            return bool(row and row.locked_until > now)

    def _record_login_failure(self, key: str, now: int):
        if self.redis is not None:
            counter = self.redis.incr("air:admin:fail:" + key)
            if counter == 1:
                self.redis.expire("air:admin:fail:" + key, 900)
            if counter >= 5:
                self.redis.setex("air:admin:lock:" + key, 900, "1")
            return
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT failures,window_started FROM air_admin_login_limits WHERE rate_key=:key FOR UPDATE"),
                               {"key": key}).first()
            if not row or now - row.window_started >= 900:
                conn.execute(text("""INSERT INTO air_admin_login_limits(rate_key,failures,window_started,locked_until)
                    VALUES(:key,1,:now,0) ON CONFLICT(rate_key) DO UPDATE SET failures=1,window_started=:now,locked_until=0"""),
                    {"key": key, "now": now})
            else:
                failures = row.failures + 1
                conn.execute(text("UPDATE air_admin_login_limits SET failures=:n,locked_until=:lock WHERE rate_key=:key"),
                             {"n": failures, "lock": now + 900 if failures >= 5 else 0, "key": key})

    def _clear_login_limit(self, key: str) -> None:
        """Reset Redis throttling after a successful password + TOTP login."""
        if self.redis is not None:
            self.redis.delete("air:admin:fail:" + key, "air:admin:lock:" + key)

    def authenticate(self, email: str, password: str, code: str, rate_key: str = "unknown", now: int | None = None):
        current = int(time.time() if now is None else now)
        key = self._limit_key(rate_key)
        if self._login_limit(key, current):
            return None
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT * FROM air_admin_users
                WHERE lower(email)=:email AND is_active=true"""), {"email": email.strip().lower()}).mappings().first()
        valid_password = bool(row and verify_password(password, row["password_hash"]))
        counter = None
        if valid_password:
            counter = matching_totp_counter(self.cipher.decrypt(bytes(row["mfa_secret"])).decode(), code, current)
        if (not row or not valid_password or counter is None or counter <= row["last_totp_counter"]
                or row["locked_until"] > current):
            self._record_login_failure(key, current)
            return None
        sid = str(uuid4())
        with self.engine.begin() as conn:
            updated = conn.execute(text("""UPDATE air_admin_users SET last_totp_counter=:counter,
                failed_attempts=0,locked_until=0 WHERE admin_id=:id AND last_totp_counter<:counter"""),
                {"counter": counter, "id": row["admin_id"]})
            if updated.rowcount != 1:
                return None
            conn.execute(text("DELETE FROM air_admin_login_limits WHERE rate_key=:key"), {"key": key})
            conn.execute(text("INSERT INTO air_admin_sessions(session_id,admin_id) VALUES(:sid,:id)"),
                         {"sid": sid, "id": row["admin_id"]})
            self._audit(conn, row["admin_id"], "LOGIN_SUCCESS", row["admin_id"])
        self._clear_login_limit(key)
        if self.redis is not None:
            self.redis.setex("air:admin:session:" + sid, 1200, row["admin_id"])
            self.redis.sadd("air:admin:user-sessions:" + row["admin_id"], sid)
            self.redis.expire("air:admin:user-sessions:" + row["admin_id"], 1200)
        return {"admin_id": row["admin_id"], "email": row["email"], "role": row["role"],
                "session_id": sid, "must_change_password": bool(row["must_change_password"])}

    def create_admin(self, actor: dict, email: str, role: str):
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("A valid administrator email is required")
        if role not in {"ADMIN", "RESEARCH_ADMIN"}:
            raise ValueError("Only ADMIN or RESEARCH_ADMIN can be provisioned")
        if actor["role"] != "SUPER_ADMIN":
            raise PermissionError("Only SUPER_ADMIN can create administrator accounts")
        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        admin_id, temporary_password = str(uuid4()), secrets.token_urlsafe(24)
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO air_admin_users
                (admin_id,email,password_hash,mfa_secret,role,must_change_password)
                VALUES(:id,:email,:password,:secret,:role,true)"""),
                {"id": admin_id, "email": email, "password": hash_password(temporary_password),
                 "secret": self.cipher.encrypt(secret.encode()), "role": role})
            self._audit(conn, actor["admin_id"], "ADMIN_CREATED", admin_id, f"{email};{role}")
        uri = f"otpauth://totp/{quote('AIR')}:{quote(email)}?secret={secret}&issuer=AIR&algorithm=SHA1&digits=6&period=30"
        return {"admin_id": admin_id, "email": email, "role": role, "active": True,
                "temporary_password": temporary_password}, uri

    def change_password(self, admin: dict, current_password: str, new_password: str):
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT password_hash FROM air_admin_users WHERE admin_id=:id AND is_active=true FOR UPDATE"),
                               {"id": admin["admin_id"]}).first()
            if not row or not verify_password(current_password, row.password_hash):
                raise PermissionError("Current administrator password is incorrect")
            conn.execute(text("UPDATE air_admin_users SET password_hash=:hash,must_change_password=false WHERE admin_id=:id"),
                         {"hash": hash_password(new_password), "id": admin["admin_id"]})
            conn.execute(text("UPDATE air_admin_sessions SET active=false WHERE admin_id=:id AND session_id<>:sid"),
                         {"id": admin["admin_id"], "sid": admin["session_id"]})
            self._audit(conn, admin["admin_id"], "PASSWORD_CHANGED", admin["admin_id"])
        if self.redis is not None:
            for sid in self.redis.smembers("air:admin:user-sessions:" + admin["admin_id"]):
                if sid != admin["session_id"]:
                    self.redis.delete("air:admin:session:" + sid)
            self.redis.srem("air:admin:user-sessions:" + admin["admin_id"], *self.redis.smembers("air:admin:user-sessions:" + admin["admin_id"]))

    def list_admins(self):
        with self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT admin_id,email,role,is_active,must_change_password,created_at
                FROM air_admin_users ORDER BY created_at,email""")).mappings().all()
        return [dict(r) for r in rows]

    def set_admin_status(self, actor: dict, target_id: str, active: bool):
        if actor["role"] != "SUPER_ADMIN":
            raise PermissionError("Only SUPER_ADMIN can change administrator status")
        with self.engine.begin() as conn:
            # Prevent concurrent deactivation of the last active Super Admin.
            conn.execute(text("SELECT pg_advisory_xact_lock(741902611)"))
            row = conn.execute(text("SELECT role FROM air_admin_users WHERE admin_id=:id FOR UPDATE"),
                               {"id": target_id}).first()
            if not row:
                return False
            if target_id == actor["admin_id"] and not active:
                raise ValueError("You cannot deactivate your own active Super Admin account")
            if row.role == "SUPER_ADMIN" and not active:
                count = conn.execute(text("SELECT COUNT(*) FROM air_admin_users WHERE role='SUPER_ADMIN' AND is_active=true")).scalar_one()
                if count <= 1:
                    raise ValueError("At least one active Super Admin must remain")
            conn.execute(text("UPDATE air_admin_users SET is_active=:active WHERE admin_id=:id"),
                         {"active": active, "id": target_id})
            if not active:
                conn.execute(text("UPDATE air_admin_sessions SET active=false WHERE admin_id=:id"), {"id": target_id})
            self._audit(conn, actor["admin_id"], "ADMIN_ACTIVATED" if active else "ADMIN_DEACTIVATED", target_id)
        if not active and self.redis is not None:
            for sid in self.redis.smembers("air:admin:user-sessions:" + target_id):
                self.redis.delete("air:admin:session:" + sid)
        return True

    def set_admin_role(self, actor: dict, target_id: str, role: str):
        if actor["role"] != "SUPER_ADMIN":
            raise PermissionError("Only SUPER_ADMIN can change administrator roles")
        if role not in ROLES:
            raise ValueError("Unsupported administrator role")
        with self.engine.begin() as conn:
            # Use the same transaction lock as status changes and bootstrap.
            conn.execute(text("SELECT pg_advisory_xact_lock(741902611)"))
            row = conn.execute(text("SELECT role,is_active FROM air_admin_users WHERE admin_id=:id FOR UPDATE"),
                               {"id": target_id}).first()
            if not row:
                return False
            if row.role == "SUPER_ADMIN" and role != "SUPER_ADMIN" and row.is_active:
                count = conn.execute(text("SELECT COUNT(*) FROM air_admin_users WHERE role='SUPER_ADMIN' AND is_active=true")).scalar_one()
                if count <= 1:
                    raise ValueError("At least one active Super Admin must remain")
            conn.execute(text("UPDATE air_admin_users SET role=:role WHERE admin_id=:id"), {"role": role, "id": target_id})
            conn.execute(text("UPDATE air_admin_sessions SET active=false WHERE admin_id=:id"), {"id": target_id})
            self._audit(conn, actor["admin_id"], "ADMIN_ROLE_CHANGED", target_id, role)
        if self.redis is not None:
            for sid in self.redis.smembers("air:admin:user-sessions:" + target_id):
                self.redis.delete("air:admin:session:" + sid)
        return True

    def audit_events(self, limit: int = 100):
        with self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT event_id,actor_admin_id,action,target_admin_id,details,created_at
                FROM air_admin_audit ORDER BY created_at DESC LIMIT :limit"""), {"limit": limit}).mappings().all()
        return [dict(r) for r in rows]

    def session(self, session_id: str):
        if self.redis is not None:
            cached_admin_id = self.redis.get("air:admin:session:" + session_id)
            if not cached_admin_id:
                return None
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT u.admin_id,u.email,u.role,u.must_change_password
                FROM air_admin_sessions s JOIN air_admin_users u ON u.admin_id=s.admin_id
                WHERE s.session_id=:sid AND s.active=true AND u.is_active=true"""),
                {"sid": session_id}).mappings().first()
        return row

    def revoke(self, session_id: str):
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE air_admin_sessions SET active=false WHERE session_id=:sid"), {"sid": session_id})
        if self.redis is not None:
            self.redis.delete("air:admin:session:" + session_id)

    def close(self):
        if self.redis is not None:
            self.redis.close()
        self.engine.dispose()
