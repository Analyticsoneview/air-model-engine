"""Small DB-API bridge for repositories being migrated from SQLite to PostgreSQL.

The wrapper preserves the repository method surface (qmark parameters, dict-like rows,
transaction context managers) while using psycopg 3 for PostgreSQL.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


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
        self._connection = psycopg.connect(driver_url, row_factory=dict_row)

    def execute(self, statement: str, parameters: Any = ()):
        # These repositories use SQLite's qmark placeholders. Their SQL statements
        # are otherwise PostgreSQL-compatible after the migration-specific branches.
        return self._connection.execute(statement.replace("?", "%s"), parameters)

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._connection.__exit__(exc_type, exc_value, traceback)

    def close(self) -> None:
        self._connection.close()
