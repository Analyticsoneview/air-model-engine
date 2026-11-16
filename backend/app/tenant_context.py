"""Request-scoped PostgreSQL tenant context for shared-schema SaaS isolation.

The context is propagated through contextvars, including asyncio.to_thread calls.
Database adapters install a pre-statement hook so pooled connections are reset to
the current request's tenant/admin context before every SQL statement.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from sqlalchemy import text

_tenant_id: ContextVar[str | None] = ContextVar("air_tenant_id", default=None)
_customer_id: ContextVar[str | None] = ContextVar("air_customer_id", default=None)
_is_admin: ContextVar[bool] = ContextVar("air_is_admin", default=False)


def current_tenant_id() -> str | None:
    return _tenant_id.get()


def current_customer_id() -> str | None:
    return _customer_id.get()


def current_is_admin() -> bool:
    return _is_admin.get()


@contextmanager
def tenant_scope(
    *, tenant_id: str | None = None, customer_id: str | None = None, is_admin: bool = False,
) -> Iterator[None]:
    tenant_token = _tenant_id.set(str(tenant_id).strip() if tenant_id else None)
    customer_token = _customer_id.set(str(customer_id).strip() if customer_id else None)
    admin_token = _is_admin.set(bool(is_admin))
    try:
        yield
    finally:
        _is_admin.reset(admin_token)
        _customer_id.reset(customer_token)
        _tenant_id.reset(tenant_token)


@contextmanager
def customer_tenant_scope(engine, customer_id: str) -> Iterator[str]:
    """Resolve a member to its active tenant and bind that scope for store operations."""
    customer = str(customer_id or "").strip()
    if not customer:
        raise ValueError("customer_id is required for tenant-scoped access")
    if getattr(getattr(engine, "dialect", None), "name", None) != "postgresql":
        with tenant_scope(tenant_id=customer, customer_id=customer):
            yield customer
        return
    with tenant_scope(customer_id=customer):
        with engine.connect() as conn:
            row = conn.execute(text("""SELECT m.tenant_id
                FROM air_tenant_members m JOIN air_tenants t ON t.tenant_id=m.tenant_id
                WHERE m.customer_id=:customer AND m.status='ACTIVE' AND t.status='ACTIVE'"""),
                {"customer": customer}).first()
    if not row:
        raise PermissionError("Customer does not have an active tenant membership")
    with tenant_scope(tenant_id=row[0], customer_id=customer):
        yield row[0]


@contextmanager
def connection_customer_scope(db, customer_id: str) -> Iterator[str]:
    """Resolve a customer membership through a PostgresConnection wrapper."""
    customer = str(customer_id or "").strip()
    if not customer:
        raise ValueError("customer_id is required for tenant-scoped access")
    if not getattr(db, "is_postgres", False):
        with tenant_scope(tenant_id=customer, customer_id=customer):
            yield customer
        return
    with tenant_scope(customer_id=customer):
        row = db.execute(
            "SELECT tenant_id FROM air_tenant_members WHERE customer_id=? AND status='ACTIVE'",
            (customer,),
        ).fetchone()
    if not row:
        raise PermissionError("Customer does not have an active tenant membership")
    tenant_id = row["tenant_id"] if hasattr(row, "keys") else row[0]
    with tenant_scope(tenant_id=tenant_id, customer_id=customer):
        yield tenant_id


def install_tenant_context(engine) -> None:
    """Set PostgreSQL session GUCs before each statement on a SQLAlchemy engine."""
    from sqlalchemy import event

    if getattr(getattr(engine, "dialect", None), "name", None) != "postgresql":
        return
    if getattr(engine, "_air_tenant_context_installed", False):
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _set_air_context(connection, cursor, statement, parameters, context, executemany):
        cursor.execute(
            "SELECT set_config('air.tenant_id', %s, false), "
            "set_config('air.customer_id', %s, false), "
            "set_config('air.is_admin', %s, false)",
            (
                current_tenant_id() or "",
                current_customer_id() or "",
                "true" if current_is_admin() else "false",
            ),
        )

    engine._air_tenant_context_installed = True
