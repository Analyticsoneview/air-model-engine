import os
import sqlite3
from pathlib import Path


class AuthStore:
    def __new__(cls, db_path: str | None = None):
        # PostgreSQL is opt-in; explicit SQLite paths keep unit tests and legacy
        # local deployments isolated from any configured production database.
        if db_path is None and (os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE")):
            from app.customer_auth_postgres import PostgresAuthStore
            return PostgresAuthStore()
        return super().__new__(cls)

    def __init__(self, db_path: str | None = None):
        db_path = db_path or os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3")
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.commit()

    def create_customer(self, customer_id: str, email: str, password_hash: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO customers(customer_id,email,password_hash) VALUES(?,?,?)",
                (customer_id, email.strip().lower(), password_hash),
            )

    def get_by_email(self, email: str):
        return self.db.execute(
            "SELECT customer_id,email,password_hash,is_active FROM customers WHERE email=?",
            (email.strip().lower(),),
        ).fetchone()

    def is_active(self, customer_id: str) -> bool:
        row = self.db.execute(
            "SELECT is_active FROM customers WHERE customer_id=?", (customer_id,)
        ).fetchone()
        return bool(row and row["is_active"])

    def close(self):
        self.db.close()
