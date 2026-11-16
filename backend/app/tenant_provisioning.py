"""Tenant registry and provisioning operations for AIR shared-schema SaaS."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.tenant_context import install_tenant_context, tenant_scope


class TenantRegistry:
    """Admin provisioning and customer-scoped tenant lookup."""

    def __init__(self, database_url: str | None = None, engine: Engine | None = None):
        if engine is None:
            url = database_url or self._database_url()
            if not url or not url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise RuntimeError("AIR_CUSTOMER_DATABASE_URL or AIR_DATABASE_URL must point to PostgreSQL")
            engine = create_engine(url, pool_pre_ping=True, future=True)
        install_tenant_context(engine)
        self.engine = engine

    @staticmethod
    def _database_url() -> str:
        for name in ("AIR_CUSTOMER_DATABASE_URL", "AIR_DATABASE_URL"):
            secret_file = os.getenv(name + "_FILE")
            value = Path(secret_file).read_text(encoding="utf-8").strip() if secret_file else os.getenv(name, "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _validate_customer(customer_id: str) -> str:
        value = str(customer_id or "").strip()
        if not value or len(value) > 128:
            raise ValueError("A valid customer identity is required")
        return value

    def tenant_for_customer(self, customer_id: str) -> str | None:
        customer = self._validate_customer(customer_id)
        with tenant_scope(customer_id=customer):
            with self.engine.connect() as conn:
                member = conn.execute(text("""SELECT tenant_id FROM air_tenant_members
                    WHERE customer_id=:customer AND status='ACTIVE'"""),
                    {"customer": customer}).first()
        if not member:
            return None
        tenant_id = member[0]
        with tenant_scope(tenant_id=tenant_id, customer_id=customer):
            with self.engine.connect() as conn:
                active = conn.execute(text("""SELECT 1 FROM air_tenants
                    WHERE tenant_id=:tenant AND status='ACTIVE'"""),
                    {"tenant": tenant_id}).first()
        return tenant_id if active else None

    def create_or_update_tenant(
        self, *, owner_customer_id: str, name: str,
        plan_code: str = "STANDARD", status: str = "ACTIVE",
    ) -> dict:
        owner = self._validate_customer(owner_customer_id)
        name = str(name or "").strip()
        plan = str(plan_code).upper()
        state = str(status).upper()
        if not name or len(name) > 160:
            raise ValueError("Tenant name must contain 1-160 characters")
        if plan not in {"STANDARD", "PAID", "ENTERPRISE"}:
            raise ValueError("Unsupported tenant plan")
        if state not in {"PROVISIONING", "ACTIVE", "SUSPENDED"}:
            raise ValueError("Unsupported tenant status")
        quotas = {
            "STANDARD": (1, 10000, 1073741824),
            "PAID": (5, 100000, 10737418240),
            "ENTERPRISE": (50, 1000000, 107374182400),
        }
        max_members, max_calls, max_storage = quotas[plan]
        with tenant_scope(is_admin=True):
            with self.engine.begin() as conn:
                member = conn.execute(text("""SELECT tenant_id FROM air_tenants
                    WHERE owner_customer_id=:customer"""), {"customer": owner}).first()
                if member:
                    tenant_id = member[0]
                    conn.execute(text("""UPDATE air_tenants SET name=:name,plan_code=:plan,
                        status=:status,max_members=:members,max_api_calls_per_day=:calls,
                        max_storage_bytes=:storage,updated_at=CURRENT_TIMESTAMP WHERE tenant_id=:tenant"""),
                        {"name": name, "plan": plan, "status": state, "members": max_members,
                         "calls": max_calls, "storage": max_storage, "tenant": tenant_id})
                else:
                    tenant_id = str(uuid4())
                    conn.execute(text("""INSERT INTO air_tenants
                        (tenant_id,name,owner_customer_id,plan_code,status,storage_prefix,rabbitmq_vhost,
                         max_members,max_api_calls_per_day,max_storage_bytes)
                        VALUES(:tenant,:name,:owner,:plan,:status,:prefix,:vhost,:members,:calls,:storage)"""),
                        {"tenant": tenant_id, "name": name, "owner": owner, "plan": plan, "status": state,
                         "prefix": f"tenants/{tenant_id}/", "vhost": "air-" + tenant_id.replace("-", ""),
                         "members": max_members, "calls": max_calls, "storage": max_storage})
                    conn.execute(text("""INSERT INTO air_tenant_members
                        (tenant_id,customer_id,role,status)
                        VALUES(:tenant,:customer,'OWNER','ACTIVE')"""),
                        {"tenant": tenant_id, "customer": owner})
        return self.get_tenant(tenant_id)

    def add_member(self, tenant_id: str, customer_id: str, role: str = "MEMBER") -> dict:
        tenant = str(tenant_id).strip()
        customer = self._validate_customer(customer_id)
        role = str(role).upper()
        if role not in {"ADMIN", "MEMBER", "READ_ONLY"}:
            raise ValueError("Member role must be ADMIN, MEMBER or READ_ONLY")
        with tenant_scope(is_admin=True):
            with self.engine.begin() as conn:
                state = conn.execute(text("SELECT status,max_members FROM air_tenants WHERE tenant_id=:tenant FOR UPDATE"),
                                     {"tenant": tenant}).first()
                if not state or state[0] != "ACTIVE":
                    raise ValueError("Tenant must be ACTIVE before members can be added")
                active_members = conn.execute(text("""SELECT COUNT(*) FROM air_tenant_members
                    WHERE tenant_id=:tenant AND status='ACTIVE'"""), {"tenant": tenant}).scalar_one()
                pending_invitations = conn.execute(text("""SELECT COUNT(*) FROM air_tenant_invitations
                    WHERE tenant_id=:tenant AND status='PENDING' AND expires_at>CURRENT_TIMESTAMP"""),
                    {"tenant": tenant}).scalar_one()
                effective_limit = int(state[1])
                licensed_limit = conn.execute(text("""SELECT MAX(l.max_seats)
                    FROM air_license_bindings b
                    JOIN air_enterprise_licenses l ON l.license_id=b.license_id
                    WHERE b.tenant_id=:tenant AND b.status='ACTIVE'
                      AND l.status IN ('ACTIVE','GRACE')
                      AND l.valid_from<=CURRENT_DATE
                      AND (l.valid_until>CURRENT_DATE OR l.grace_until>=CURRENT_DATE)"""),
                    {"tenant": tenant}).scalar_one_or_none()
                if licensed_limit is not None:
                    effective_limit = min(effective_limit, int(licensed_limit))
                if int(active_members) + int(pending_invitations) >= effective_limit:
                    raise ValueError("Organisation or enterprise licence seat limit has been reached or seats are reserved by invitations")
                existing = conn.execute(text("""SELECT status FROM air_tenant_members
                    WHERE tenant_id=:tenant AND customer_id=:customer"""),
                    {"tenant": tenant, "customer": customer}).scalar_one_or_none()
                if existing and existing != "REMOVED":
                    raise ValueError("Customer is already a member of this tenant")
                if existing == "REMOVED":
                    conn.execute(text("""DELETE FROM air_tenant_members
                        WHERE tenant_id=:tenant AND customer_id=:customer"""),
                        {"tenant": tenant, "customer": customer})
                conn.execute(text("""INSERT INTO air_tenant_members
                    (tenant_id,customer_id,role,status)
                    VALUES(:tenant,:customer,:role,'ACTIVE')"""),
                    {"tenant": tenant, "customer": customer, "role": role})
                conn.execute(text("""INSERT INTO air_tenant_membership_events
                    (event_id,tenant_id,customer_id,actor_id,event_type,from_role,to_role,
                     idempotency_key,details,occurred_at)
                    VALUES(:id,:tenant,:customer,'AIR_SYSTEM_ADMIN','ADMIN_MEMBER_ADDED',
                           NULL,:role,:key,CAST(:details AS json),CURRENT_TIMESTAMP)"""),
                    {"id": str(uuid4()), "tenant": tenant, "customer": customer, "role": role,
                     "key": "admin-add:" + str(uuid4()), "details": json.dumps({"source": "tenant_registry"})})
        return {"tenant_id": tenant, "customer_id": customer, "role": role, "status": "ACTIVE"}

    def set_tenant_status(self, tenant_id: str, status: str) -> dict:
        tenant, state = str(tenant_id).strip(), str(status).upper()
        if state not in {"ACTIVE", "SUSPENDED", "CLOSED"}:
            raise ValueError("Tenant status must be ACTIVE, SUSPENDED or CLOSED")
        with tenant_scope(is_admin=True):
            with self.engine.begin() as conn:
                result = conn.execute(text("""UPDATE air_tenants SET status=:status,
                    updated_at=CURRENT_TIMESTAMP WHERE tenant_id=:tenant"""),
                    {"status": state, "tenant": tenant})
                if result.rowcount != 1:
                    raise KeyError("Tenant does not exist")
        return self.get_tenant(tenant)

    def get_tenant(self, tenant_id: str) -> dict:
        tenant = str(tenant_id).strip()
        with tenant_scope(is_admin=True):
            with self.engine.connect() as conn:
                row = conn.execute(text("""SELECT t.tenant_id,t.name,t.owner_customer_id,t.plan_code,
                    t.status,t.storage_prefix,t.rabbitmq_vhost,t.max_members,
                    t.max_api_calls_per_day,t.max_storage_bytes,t.feature_flags_json,
                    t.metadata_json,t.provisioned_at,t.created_at,t.updated_at,
                    COUNT(m.customer_id) AS member_count
                    FROM air_tenants t LEFT JOIN air_tenant_members m ON m.tenant_id=t.tenant_id
                    AND m.status='ACTIVE' WHERE t.tenant_id=:tenant
                    GROUP BY t.tenant_id"""), {"tenant": tenant}).mappings().first()
        if not row:
            raise KeyError("Tenant does not exist")
        return dict(row)

    def list_tenants(self, status: str | None = None, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        params = {"limit": limit}
        where = ""
        if status:
            state = str(status).upper()
            if state not in {"PROVISIONING", "ACTIVE", "SUSPENDED", "CLOSED"}:
                raise ValueError("Unsupported tenant status filter")
            where = "WHERE t.status=:status"
            params["status"] = state
        with tenant_scope(is_admin=True):
            with self.engine.connect() as conn:
                rows = conn.execute(text(f"""SELECT t.tenant_id,t.name,t.owner_customer_id,
                    t.plan_code,t.status,t.storage_prefix,t.rabbitmq_vhost,t.max_members,
                    t.max_api_calls_per_day,t.max_storage_bytes,t.feature_flags_json,
                    t.metadata_json,t.provisioned_at,t.created_at,t.updated_at,
                    COUNT(m.customer_id) FILTER (WHERE m.status='ACTIVE') AS member_count
                    FROM air_tenants t LEFT JOIN air_tenant_members m ON m.tenant_id=t.tenant_id
                    {where} GROUP BY t.tenant_id ORDER BY t.created_at DESC LIMIT :limit"""),
                    params).mappings().all()
        return [dict(row) for row in rows]

    def get_customer_context(self, customer_id: str) -> dict:
        customer = self._validate_customer(customer_id)
        with tenant_scope(customer_id=customer):
            with self.engine.connect() as conn:
                member = conn.execute(text("""SELECT tenant_id,role,status
                    FROM air_tenant_members WHERE customer_id=:customer"""),
                    {"customer": customer}).mappings().first()
        if not member or member["status"] != "ACTIVE":
            raise KeyError("Customer has no active tenant")
        tenant_id = member["tenant_id"]
        with tenant_scope(tenant_id=tenant_id, customer_id=customer):
            with self.engine.connect() as conn:
                tenant = conn.execute(text("""SELECT name,plan_code,status,storage_prefix,
                    rabbitmq_vhost,max_members,max_api_calls_per_day,max_storage_bytes,
                    storage_used_bytes,feature_flags_json FROM air_tenants WHERE tenant_id=:tenant"""),
                    {"tenant": tenant_id}).mappings().first()
        if not tenant or tenant["status"] != "ACTIVE":
            raise KeyError("Customer has no active tenant")
        return {
            "tenant_id": tenant_id, "role": member["role"],
            "membership_status": member["status"], **dict(tenant),
            "tenant_status": tenant["status"],
        }

    @staticmethod
    def _require_active_storage_member(conn, tenant_id: str, customer_id: str, *, write: bool = False) -> dict:
        member = conn.execute(text("""
            SELECT m.role,m.status,t.status AS tenant_status
            FROM air_tenant_members m
            JOIN air_tenants t ON t.tenant_id=m.tenant_id
            WHERE m.tenant_id=:tenant AND m.customer_id=:customer
        """), {"tenant": tenant_id, "customer": customer_id}).mappings().first()
        if not member or member["status"] != "ACTIVE" or member["tenant_status"] != "ACTIVE":
            raise PermissionError("Customer is not an active member of this tenant")
        if write and member["role"] not in {"OWNER", "ADMIN", "MEMBER"}:
            raise PermissionError("Tenant membership is read-only")
        return dict(member)

    @staticmethod
    def _validate_object_key(object_key: str) -> str:
        key = str(object_key or "")
        if (
            not key or len(key) > 512 or len(key.encode("utf-8")) > 1024 or key.startswith("/")
            or "\\" in key or "\x00" in key
            or any(ord(char) < 32 or ord(char) == 127 for char in key)
        ):
            raise ValueError("A safe tenant object key of 1-512 characters is required")
        if any(not part or part in {".", ".."} for part in key.split("/")):
            raise ValueError("Tenant object key contains an unsafe path segment")
        return key

    def reserve_object_upload(
        self, tenant_id: str, customer_id: str, object_key: str, *,
        size_bytes: int, sha256: str, content_type: str,
    ) -> dict:
        tenant = str(tenant_id).strip()
        customer = self._validate_customer(customer_id)
        key = self._validate_object_key(object_key)
        size = int(size_bytes)
        digest = str(sha256 or "").lower()
        media_type = str(content_type or "application/octet-stream").strip().lower()
        if size < 1 or size > 25 * 1024 * 1024:
            raise ValueError("Tenant object size must be between 1 byte and 25 MiB")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("A valid SHA-256 digest is required")
        if not media_type or len(media_type) > 255 or any(ord(ch) < 32 for ch in media_type):
            raise ValueError("A valid content type is required")

        with tenant_scope(tenant_id=tenant, customer_id=customer):
            with self.engine.begin() as conn:
                self._require_active_storage_member(conn, tenant, customer, write=True)
                row = conn.execute(text("""
                    SELECT status,max_storage_bytes,storage_used_bytes
                    FROM air_tenants WHERE tenant_id=:tenant FOR UPDATE
                """), {"tenant": tenant}).mappings().first()
                if not row or row["status"] != "ACTIVE":
                    raise PermissionError("Customer tenant is not active")
                existing = conn.execute(text("""
                    SELECT size_bytes,sha256,content_type,etag,status
                    FROM air_tenant_objects
                    WHERE tenant_id=:tenant AND object_key=:key
                """), {"tenant": tenant, "key": key}).mappings().first()
                if existing:
                    if (
                        int(existing["size_bytes"]) != size
                        or existing["sha256"] != digest
                        or existing["content_type"] != media_type
                    ):
                        raise FileExistsError("Tenant object keys are immutable; choose a new key")
                    if existing["status"] == "STORED":
                        return {
                            "already_stored": True, "tenant_id": tenant, "object_key": key,
                            "size_bytes": size, "sha256": digest,
                            "content_type": existing["content_type"], "etag": existing["etag"],
                            "storage_used_bytes": int(row["storage_used_bytes"]),
                            "max_storage_bytes": int(row["max_storage_bytes"]),
                        }
                    return {
                        "already_stored": False, "resume_pending": True,
                        "tenant_id": tenant, "object_key": key, "size_bytes": size,
                        "sha256": digest, "content_type": media_type,
                        "storage_used_bytes": int(row["storage_used_bytes"]),
                        "max_storage_bytes": int(row["max_storage_bytes"]),
                    }
                used, limit = int(row["storage_used_bytes"]), int(row["max_storage_bytes"])
                if used + size > limit:
                    raise OverflowError("Tenant storage quota would be exceeded")
                conn.execute(text("""
                    UPDATE air_tenants SET storage_used_bytes=storage_used_bytes+:size,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE tenant_id=:tenant AND status='ACTIVE'
                """), {"size": size, "tenant": tenant})
                conn.execute(text("""
                    INSERT INTO air_tenant_objects
                        (tenant_id,object_key,size_bytes,sha256,content_type,status)
                    VALUES(:tenant,:key,:size,:sha256,:content_type,'PENDING')
                """), {"tenant": tenant, "key": key, "size": size, "sha256": digest,
                       "content_type": media_type})
                return {
                    "already_stored": False, "resume_pending": False,
                    "tenant_id": tenant, "object_key": key, "size_bytes": size,
                    "sha256": digest, "content_type": media_type,
                    "storage_used_bytes": used + size, "max_storage_bytes": limit,
                }

    def complete_object_upload(self, tenant_id: str, customer_id: str, object_key: str, etag: str) -> dict:
        tenant = str(tenant_id).strip()
        customer = self._validate_customer(customer_id)
        key = self._validate_object_key(object_key)
        with tenant_scope(tenant_id=tenant, customer_id=customer):
            with self.engine.begin() as conn:
                self._require_active_storage_member(conn, tenant, customer, write=True)
                row = conn.execute(text("""
                    UPDATE air_tenant_objects SET status='STORED',etag=:etag,updated_at=CURRENT_TIMESTAMP
                    WHERE tenant_id=:tenant AND object_key=:key AND status='PENDING'
                    RETURNING tenant_id,object_key,size_bytes,sha256,content_type,etag,status,created_at
                """), {"etag": str(etag or "")[:128], "tenant": tenant, "key": key}).mappings().first()
                if row:
                    return dict(row)
                existing = conn.execute(text("""
                    SELECT tenant_id,object_key,size_bytes,sha256,content_type,etag,status,created_at
                    FROM air_tenant_objects WHERE tenant_id=:tenant AND object_key=:key
                """), {"tenant": tenant, "key": key}).mappings().first()
                if existing and existing["status"] == "STORED":
                    return dict(existing)
                raise KeyError("Pending tenant object reservation was not found")

    def list_tenant_objects(
        self, tenant_id: str, customer_id: str, *, limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        tenant = str(tenant_id).strip()
        customer = self._validate_customer(customer_id)
        page_size, page_offset = max(1, min(int(limit), 500)), max(0, int(offset))
        with tenant_scope(tenant_id=tenant, customer_id=customer):
            with self.engine.connect() as conn:
                self._require_active_storage_member(conn, tenant, customer)
                rows = conn.execute(text("""
                    SELECT object_key,size_bytes,sha256,content_type,etag,status,created_at
                    FROM air_tenant_objects WHERE tenant_id=:tenant AND status='STORED'
                    ORDER BY created_at DESC,object_key LIMIT :limit OFFSET :offset
                """), {"tenant": tenant, "limit": page_size, "offset": page_offset}).mappings().all()
        return [dict(row) for row in rows]

    def get_tenant_object(self, tenant_id: str, customer_id: str, object_key: str) -> dict:
        tenant = str(tenant_id).strip()
        customer = self._validate_customer(customer_id)
        key = self._validate_object_key(object_key)
        with tenant_scope(tenant_id=tenant, customer_id=customer):
            with self.engine.connect() as conn:
                self._require_active_storage_member(conn, tenant, customer)
                row = conn.execute(text("""
                    SELECT object_key,size_bytes,sha256,content_type,etag,status,created_at
                    FROM air_tenant_objects
                    WHERE tenant_id=:tenant AND object_key=:key AND status='STORED'
                """), {"tenant": tenant, "key": key}).mappings().first()
        if not row:
            raise KeyError("Tenant object does not exist")
        return dict(row)

    def record_aws_provisioning(
        self, tenant_id: str, infrastructure: dict, *, status: str = "ACTIVE",
    ) -> dict:
        tenant = str(tenant_id).strip()
        state = str(status).upper()
        if state not in {"PROVISIONING", "ACTIVE", "SUSPENDED", "CLOSED"}:
            raise ValueError("Unsupported tenant lifecycle status")
        with tenant_scope(is_admin=True):
            with self.engine.begin() as conn:
                row = conn.execute(text(
                    "SELECT metadata_json FROM air_tenants WHERE tenant_id=:tenant FOR UPDATE"
                ), {"tenant": tenant}).first()
                if not row:
                    raise KeyError("Tenant does not exist")
                metadata = row[0] or {}
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata["aws_provisioning"] = dict(infrastructure)
                conn.execute(text("""
                    UPDATE air_tenants
                    SET metadata_json=CAST(:metadata AS json),
                        status=:status,
                        provisioned_at=CASE WHEN :provisioned THEN CURRENT_TIMESTAMP ELSE provisioned_at END,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE tenant_id=:tenant
                """), {
                    "metadata": json.dumps(metadata, sort_keys=True),
                    "status": state,
                    "provisioned": infrastructure.get("status") == "PROVISIONED",
                    "tenant": tenant,
                })
        return self.get_tenant(tenant)

    def record_aws_provisioning_failure(self, tenant_id: str, error_code: str) -> dict:
        return self.record_aws_provisioning(
            tenant_id,
            {"status": "FAILED", "error_code": str(error_code)[:80]},
            status="PROVISIONING",
        )

    def close(self) -> None:
        self.engine.dispose()
