"""Request-scoped PostgreSQL tenant context for shared-schema SaaS isolation.

The context is propagated through contextvars, including asyncio.to_thread calls.
Database adapters install a pre-statement hook so pooled connections are reset to
the current request's tenant/admin context before every SQL statement.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

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
