import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()
_bearer = HTTPBearer(auto_error=False)


def _secret(name: str, min_length: int = 32) -> str:
    value = os.getenv(f"{name}_FILE")
    if value:
        value = Path(value).read_text(encoding="utf-8").strip()
    else:
        value = os.getenv(name, "")
    if len(value) < min_length:
        raise RuntimeError(f"{name} must be configured with at least {min_length} characters")
    return value


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    return _password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _password_hash.verify(password, encoded)
    except Exception:
        return False


def create_access_token(customer_id: str, expires_minutes: int = 30, session_id: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": customer_id,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "iss": "air-model-engine",
        "aud": "air-api",
    }
    if session_id:
        payload["jti"] = session_id
    return jwt.encode(payload, _secret("AIR_JWT_SECRET"), algorithm="HS256")


async def require_customer(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Bearer access token required")
    try:
        payload = jwt.decode(
            credentials.credentials,
            _secret("AIR_JWT_SECRET"),
            algorithms=["HS256"],
            issuer="air-model-engine",
            audience="air-api",
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
        customer_id = payload.get("sub")
        if not isinstance(customer_id, str) or not customer_id:
            raise ValueError("Invalid subject")
        session_id = payload.get("jti")
        if session_id:
            from app.access_control import access_store
            if not access_store.is_session_active(session_id):
                raise ValueError("Access has been revoked or is not approved")
        return customer_id
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from exc


def create_admin_access_token(admin_id: str, role: str, session_id: str, expires_minutes: int = 20) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": admin_id, "role": role, "iat": now,
               "exp": now + timedelta(minutes=expires_minutes),
               "iss": "air-model-engine", "aud": "air-admin-api", "jti": session_id}
    return jwt.encode(payload, _secret("AIR_JWT_SECRET"), algorithm="HS256")


async def require_admin(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Administrator bearer token required")
    try:
        payload = jwt.decode(credentials.credentials, _secret("AIR_JWT_SECRET"),
            algorithms=["HS256"], issuer="air-model-engine", audience="air-admin-api",
            options={"require": ["sub", "role", "exp", "iat", "iss", "aud", "jti"]})
        from app.admin_auth import get_admin_auth_store
        session = get_admin_auth_store().session(payload["jti"])
        if not session or session["admin_id"] != payload["sub"] or session["role"] != payload["role"]:
            raise ValueError("Administrator session revoked")
        must_change = bool(session["must_change_password"])
        if must_change and request.url.path != "/api/v1/admin/auth/password":
            raise HTTPException(status_code=403, detail="Password rotation is required before using the administrator console")
        return {"admin_id": session["admin_id"], "email": session["email"], "role": session["role"],
                "session_id": payload["jti"], "must_change_password": must_change}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked administrator session") from exc
