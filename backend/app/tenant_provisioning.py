"""Tenant registry and provisioning operations for AIR shared-schema SaaS."""
from __future__ import annotations

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
                row = conn.execute(text("""SELECT m.tenant_id
                    FROM air_tenant_members m JOIN air_tenants t ON t.tenant_id=m.tenant_id
                    WHERE m.customer_id=:customer AND m.status='ACTIVE' AND t.status='ACTIVE'"""),
                    {"customer": customer}).first()
        return row[0] if row else None

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
        with tenant_scope(is_admin=True):
            with self.engine.begin() as conn:
                member = conn.execute(text("""SELECT tenant_id,status FROM air_tenant_members
                    WHERE customer_id=:customer"""), {"customer": owner}).mappings().first()
                if member:
                    tenant_id = member["tenant_id"]
                    conn.execute(text("""UPDATE air_tenants SET name=:name,plan_code=:plan,
                        status=:status,updated_at=CURRENT_TIMESTAMP WHERE tenant_id=:tenant"""),
                        {"name": name, "plan": plan, "status": state, "tenant": tenant_id})
                else:
                    tenant_id = str(uuid4())
                    conn.execute(text("""INSERT INTO air_tenants
                        (tenant_id,name,owner_customer_id,plan_code,status)
                        VALUES(:tenant,:name,:owner,:plan,:status)"""),
                        {"tenant": tenant_id, "name": name, "owner": owner, "plan": plan, "status": state})
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
                state = conn.execute(text("SELECT status FROM air_tenants WHERE tenant_id=:tenant"),
                                     {"tenant": tenant}).scalar_one_or_none()
                if state != "ACTIVE":
                    raise ValueError("Tenant must be ACTIVE before members can be added")
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
                    t.status,t.created_at,t.updated_at,COUNT(m.customer_id) AS member_count
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
                    t.plan_code,t.status,t.created_at,t.updated_at,
                    COUNT(m.customer_id) FILTER (WHERE m.status='ACTIVE') AS member_count
                    FROM air_tenants t LEFT JOIN air_tenant_members m ON m.tenant_id=t.tenant_id
                    {where} GROUP BY t.tenant_id ORDER BY t.created_at DESC LIMIT :limit"""),
                    params).mappings().all()
        return [dict(row) for row in rows]

    def get_customer_context(self, customer_id: str) -> dict:
        customer = self._validate_customer(customer_id)
        with tenant_scope(customer_id=customer):
            with self.engine.connect() as conn:
                row = conn.execute(text("""SELECT m.tenant_id,m.role,m.status AS membership_status,
                    t.name,t.plan_code,t.status AS tenant_status
                    FROM air_tenant_members m JOIN air_tenants t ON t.tenant_id=m.tenant_id
                    WHERE m.customer_id=:customer AND m.status='ACTIVE'"""),
                    {"customer": customer}).mappings().first()
        if not row or row["tenant_status"] != "ACTIVE":
            raise KeyError("Customer has no active tenant")
        return dict(row)

    def close(self) -> None:
        self.engine.dispose()
