import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from app.tenant_context import tenant_scope

_password_hash = PasswordHash.recommended()

_tenant_quota_registry = None
_tenant_api_quota_enforcer = None


def _consume_tenant_api_quota(tenant_id: str) -> None:
    global _tenant_quota_registry, _tenant_api_quota_enforcer
    if os.getenv("AIR_DEPLOYMENT_PROFILE", "onprem-single") != "aws-saas-multi":
        return
    try:
        from app.tenant_quotas import TenantApiQuotaEnforcer, TenantApiQuotaExceeded
        if _tenant_quota_registry is None:
            from app.tenant_provisioning import TenantRegistry
            _tenant_quota_registry = TenantRegistry()
        tenant = _tenant_quota_registry.get_tenant(tenant_id)
        if tenant.get("status") != "ACTIVE":
            raise HTTPException(status_code=403, detail="AIR tenant is not active")
        if _tenant_api_quota_enforcer is None:
            _tenant_api_quota_enforcer = TenantApiQuotaEnforcer.from_environment()
        _tenant_api_quota_enforcer.consume(tenant_id, tenant["max_api_calls_per_day"])
    except HTTPException:
        raise
    except TenantApiQuotaExceeded as exc:
        raise HTTPException(status_code=429, detail="AIR tenant daily API quota has been exceeded") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="AIR tenant quota service is unavailable") from exc
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


def hash_pin(pin: str) -> str:
    if not isinstance(pin, str) or not pin.isdigit() or len(pin) != 6:
        raise ValueError("AIR PIN must be exactly six digits")
    return _password_hash.hash(pin)


def verify_pin(pin: str, encoded: str) -> bool:
    if not isinstance(pin, str) or not pin.isdigit() or len(pin) != 6:
        return False
    try:
        return _password_hash.verify(pin, encoded)
    except Exception:
        return False


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


async def require_customer(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
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
        from app.access_control import access_store
        owner_customer_id = customer_id
        if not customer_id.startswith("+"):
            # Compatibility for signed beta tokens whose subject was a request UUID.
            with tenant_scope(is_admin=True):
                owner_customer_id = access_store.mobile_for_request_id(customer_id) or ""
        if not owner_customer_id:
            raise ValueError("Customer identity could not be resolved")
        tenant_id = (
            access_store.tenant_for_customer(owner_customer_id)
            if hasattr(access_store, "tenant_for_customer") else owner_customer_id
        )
        if not tenant_id:
            raise ValueError("Customer does not have an active tenant")
        session_id = payload.get("jti")
        with tenant_scope(tenant_id=tenant_id, customer_id=owner_customer_id):
            if session_id and not access_store.is_session_active(session_id):
                raise ValueError("Access has been revoked or is not approved")
            _consume_tenant_api_quota(tenant_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked customer session") from exc

    # Keep the tenant context alive for the complete request, including thread-pool work.
    with tenant_scope(tenant_id=tenant_id, customer_id=owner_customer_id):
        yield customer_id


def create_admin_access_token(admin_id: str, role: str, session_id: str, expires_minutes: int = 20) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": admin_id, "role": role, "iat": now,
               "exp": now + timedelta(minutes=expires_minutes),
               "iss": "air-model-engine", "aud": "air-admin-api", "jti": session_id}
    return jwt.encode(payload, _secret("AIR_JWT_SECRET"), algorithm="HS256")


async def require_admin(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Administrator bearer token required")
    try:
        payload = jwt.decode(
            credentials.credentials, _secret("AIR_JWT_SECRET"),
            algorithms=["HS256"], issuer="air-model-engine", audience="air-admin-api",
            options={"require": ["sub", "role", "exp", "iat", "iss", "aud", "jti"]},
        )
        from app.admin_auth import get_admin_auth_store
        session = get_admin_auth_store().session(payload["jti"])
        if not session or session["admin_id"] != payload["sub"] or session["role"] != payload["role"]:
            raise ValueError("Administrator session revoked")
        must_change = bool(session["must_change_password"])
        if must_change and request.url.path not in {"/api/v1/admin/auth/password", "/api/v1/admin/auth/me"}:
            raise HTTPException(status_code=403, detail="Password rotation is required before using the administrator console")
        admin = {
            "admin_id": session["admin_id"], "email": session["email"],
            "role": session["role"], "session_id": payload["jti"],
            "must_change_password": must_change,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked administrator session") from exc

    with tenant_scope(is_admin=True):
        yield admin
