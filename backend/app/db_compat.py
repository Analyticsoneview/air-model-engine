"""Small DB-API bridge for repositories being migrated from SQLite to PostgreSQL.

The wrapper preserves the repository method surface (qmark parameters, dict-like rows,
transaction context managers) while using psycopg 3 for PostgreSQL.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.tenant_context import current_customer_id, current_is_admin, current_tenant_id


def read_database_url(name: str) -> str | None:
    secret_file = os.getenv(f"{name}_FILE")
    value = Path(secret_file).read_text(encoding="utf-8").strip() if secret_file else os.getenv(name, "").strip()
    if not value:
        return None
    if not value.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError(f"{name} must use PostgreSQL")
    return value


class PostgresConnection:
    def __init__(self, url: str) -> None:
        import psycopg
        from psycopg.rows import dict_row

        driver_url = url.replace('postgresql+psycopg://', 'postgresql://', 1)
        self._connection = psycopg.connect(driver_url, row_factory=dict_row, autocommit=True)
        self._transaction = None
        self.is_postgres = True

    def _apply_tenant_context(self) -> None:
        self._connection.execute(
            "SELECT set_config('air.tenant_id', %s, false), "
            "set_config('air.customer_id', %s, false), "
            "set_config('air.is_admin', %s, false)",
            (
                current_tenant_id() or "",
                current_customer_id() or "",
                "true" if current_is_admin() else "false",
            ),
        )

    def execute(self, statement: str, parameters: Any = ()):
        # These repositories use SQLite's qmark placeholders. Their SQL statements
        # are otherwise PostgreSQL-compatible after the migration-specific branches.
        self._apply_tenant_context()
        return self._connection.execute(statement.replace("?", "%s"), parameters)

    def executemany(self, statement: str, parameter_rows):
        self._apply_tenant_context()
        cursor = self._connection.cursor()
        cursor.executemany(statement.replace("?", "%s"), parameter_rows)
        return cursor

    def commit(self) -> None:
        # Connections run in autocommit mode; explicit with-blocks provide transactions.
        return None

    def __enter__(self):
        self._transaction = self._connection.transaction()
        self._transaction.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        transaction = self._transaction
        self._transaction = None
        return transaction.__exit__(exc_type, exc_value, traceback)

    def close(self) -> None:
        self._connection.close()
