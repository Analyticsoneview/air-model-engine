import json
import os
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class CredentialVault:
    """Encrypt broker credential payloads at rest; never return plaintext in list APIs."""

    def __init__(self, db_path: str = "data/air_credentials.sqlite3"):
        key_file = os.getenv("AIR_CREDENTIAL_KEY_FILE")
        key = Path(key_file).read_bytes().strip() if key_file else os.getenv("AIR_CREDENTIAL_KEY", "").encode()
        if not key:
            raise RuntimeError("AIR_CREDENTIAL_KEY or AIR_CREDENTIAL_KEY_FILE must be configured")
        try:
            self._cipher = Fernet(key)
        except Exception as exc:
            raise RuntimeError("AIR credential encryption key must be a valid Fernet key") from exc
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS broker_credentials (
                customer_id TEXT NOT NULL,
                broker TEXT NOT NULL,
                account_id TEXT NOT NULL,
                encrypted_payload BLOB NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(customer_id, broker, account_id)
            )
        """)
        self._db.commit()

    def put(self, customer_id: str, broker: str, account_id: str, credentials: dict) -> None:
        if not credentials or any(not isinstance(k, str) or not isinstance(v, str) or not v for k,v in credentials.items()):
            raise ValueError("Credentials must be a non-empty map of string keys and values")
        encrypted = self._cipher.encrypt(json.dumps(credentials).encode())
        with self._db:
            self._db.execute("""
                INSERT INTO broker_credentials(customer_id,broker,account_id,encrypted_payload)
                VALUES(?,?,?,?)
                ON CONFLICT(customer_id,broker,account_id) DO UPDATE SET
                encrypted_payload=excluded.encrypted_payload, updated_at=CURRENT_TIMESTAMP
            """, (customer_id, broker.lower(), account_id, encrypted))

    def get(self, customer_id: str, broker: str, account_id: str) -> dict:
        row = self._db.execute("""
            SELECT encrypted_payload FROM broker_credentials
            WHERE customer_id=? AND broker=? AND account_id=?
        """, (customer_id, broker.lower(), account_id)).fetchone()
        if row is None:
            raise KeyError("Broker credentials not found")
        try:
            return json.loads(self._cipher.decrypt(row["encrypted_payload"]).decode())
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError("Stored broker credentials cannot be decrypted") from exc

    def delete(self, customer_id: str, broker: str, account_id: str) -> None:
        with self._db:
            self._db.execute("""
                DELETE FROM broker_credentials WHERE customer_id=? AND broker=? AND account_id=?
            """, (customer_id, broker.lower(), account_id))

    def list_for_all_customers(self) -> list[dict]:
        rows = self._db.execute("""
            SELECT customer_id,broker,account_id,updated_at FROM broker_credentials
            ORDER BY customer_id,broker,account_id
        """).fetchall()
        return [dict(row) for row in rows]

    def list_for_customer(self, customer_id: str) -> list[dict]:
        rows = self._db.execute("""
            SELECT broker,account_id,updated_at FROM broker_credentials
            WHERE customer_id=? ORDER BY broker,account_id
        """, (customer_id,)).fetchall()
        return [dict(row) for row in rows]

    def close(self):
        self._db.close()
