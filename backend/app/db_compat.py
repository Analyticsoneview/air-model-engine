"""DB-API bridge for SQLite-compatible repositories migrated to PostgreSQL."""
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
    """psycopg 3 adapter preserving qmark parameters and sqlite row access patterns."""
    def __init__(self, url: str) -> None:
        import psycopg
        from psycopg.rows import dict_row
        driver_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._connection = psycopg.connect(driver_url, row_factory=dict_row, autocommit=True)
        self._transaction = None
    def execute(self, statement: str, parameters: Any = ()):
        return self._connection.execute(statement.replace("?", "%s"), parameters)
    def executemany(self, statement: str, parameter_rows):
        cursor = self._connection.cursor()
        cursor.executemany(statement.replace("?", "%s"), parameter_rows)
        return cursor
    def commit(self) -> None:
        return None
    def __enter__(self):
        self._transaction = self._connection.transaction()
        self._transaction.__enter__()
        return self
    def __exit__(self, exc_type, exc_value, traceback):
        transaction, self._transaction = self._transaction, None
        return transaction.__exit__(exc_type, exc_value, traceback)
    def close(self) -> None:
        self._connection.close()
