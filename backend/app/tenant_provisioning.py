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
                member = conn.execute(text("""SELECT tenant_id,status FROM air_tenant_members
                    WHERE customer_id=:customer"""), {"customer": owner}).mappings().first()
                if member:
                    tenant_id = member["tenant_id"]
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
                if active_members >= state[1]:
                    raise ValueError("Tenant member quota has been reached")
                existing = conn.execute(text("SELECT tenant_id FROM air_tenant_members WHERE customer_id=:customer"),
                                        {"customer": customer}).scalar_one_or_none()
                if existing:
                    if existing != tenant:
                        raise ValueError("Customer already belongs to another tenant")
                    raise ValueError("Customer is already a member of this tenant")
                conn.execute(text("""INSERT INTO air_tenant_members
                    (tenant_id,customer_id,role,status)
                    VALUES(:tenant,:customer,:role,'ACTIVE')"""),
                    {"tenant": tenant, "customer": customer, "role": role})
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
                    feature_flags_json FROM air_tenants WHERE tenant_id=:tenant"""),
                    {"tenant": tenant_id}).mappings().first()
        if not tenant or tenant["status"] != "ACTIVE":
            raise KeyError("Customer has no active tenant")
        return {
            "tenant_id": tenant_id, "role": member["role"],
            "membership_status": member["status"], **dict(tenant),
            "tenant_status": tenant["status"],
        }

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
