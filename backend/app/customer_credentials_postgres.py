"""PostgreSQL-backed customer credential store.

Credentials are selected only when AIR_CUSTOMER_DATABASE_URL (or its secret-file
variant) is explicitly configured. SQLite remains the local compatibility default.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _database_url() -> str:
    secret_file = os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE")
    value = Path(secret_file).read_text(encoding="utf-8").strip() if secret_file else os.getenv("AIR_CUSTOMER_DATABASE_URL", "").strip()
    if not value or not value.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("AIR_CUSTOMER_DATABASE_URL or AIR_CUSTOMER_DATABASE_URL_FILE must point to PostgreSQL")
    return value


class PostgresAuthStore:
    """Implements the AuthStore contract using the shared PostgreSQL customer database."""

    def __init__(self, database_url: str | None = None, engine: Engine | None = None):
        self.engine = engine or create_engine(database_url or _database_url(), pool_pre_ping=True, future=True)

    def create_customer(self, customer_id: str, email: str, password_hash: str) -> None:
        if not customer_id or len(customer_id) > 128:
            raise ValueError("Customer ID must contain 1 to 128 characters")
        normalized_email = email.strip().lower()
        if not normalized_email or len(normalized_email) > 254:
            raise ValueError("A valid customer email is required")
        if not password_hash:
            raise ValueError("Customer password hash is required")
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO customers(customer_id,email,password_hash)
                VALUES(:customer_id,:email,:password_hash)
            """), {"customer_id": customer_id, "email": normalized_email, "password_hash": password_hash})

    def get_by_email(self, email: str):
        normalized_email = email.strip().lower()
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT customer_id,email,password_hash,is_active
                FROM customers WHERE lower(email)=:email
            """), {"email": normalized_email}).mappings().first()
        return row

    def is_active(self, customer_id: str) -> bool:
        with self.engine.connect() as conn:
            active = conn.execute(text("""
                SELECT is_active FROM customers WHERE customer_id=:customer_id
            """), {"customer_id": customer_id}).scalar_one_or_none()
        return bool(active)

    def close(self) -> None:
        self.engine.dispose()
