"""PostgreSQL-backed encrypted AIR broker credential vault."""
from __future__ import annotations
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from app.tenant_context import install_tenant_context, tenant_scope, customer_tenant_scope, current_tenant_id
from functools import wraps

def _customer_scoped(method):
    @wraps(method)
    def wrapped(self, customer_id, *args, **kwargs):
        with customer_tenant_scope(self.engine, customer_id):
            return method(self, customer_id, *args, **kwargs)
    return wrapped


def _admin_scoped(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with tenant_scope(is_admin=True):
            return method(self, *args, **kwargs)
    return wrapped


class PostgresCredentialVault:
    def __init__(self, database_url: str, engine: Engine | None = None):
        key_file = os.getenv("AIR_CREDENTIAL_KEY_FILE")
        key = Path(key_file).read_bytes().strip() if key_file else os.getenv("AIR_CREDENTIAL_KEY", "").encode()
        if not key:
            raise RuntimeError("AIR_CREDENTIAL_KEY or AIR_CREDENTIAL_KEY_FILE must be configured")
        try:
            self._cipher = Fernet(key)
        except Exception as exc:
            raise RuntimeError("AIR credential encryption key must be a valid Fernet key") from exc
        if engine is None:
            if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise RuntimeError("AIR_CREDENTIAL_DATABASE_URL must point to PostgreSQL")
            engine = create_engine(database_url, pool_pre_ping=True, future=True)
        install_tenant_context(engine)
        self.engine = engine
        self._tenant_ciphers: dict[str, Fernet] = {}

    def _cipher_for_current_tenant(self) -> Fernet:
        if os.getenv("AIR_DEPLOYMENT_PROFILE", "onprem-single") != "aws-saas-multi":
            return self._cipher
        tenant_id = current_tenant_id()
        if not tenant_id:
            raise RuntimeError("Tenant context is required for AWS SaaS credential encryption")
        cached = self._tenant_ciphers.get(tenant_id)
        if cached:
            return cached
        try:
            import boto3
            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
            client = boto3.client("secretsmanager", region_name=region)
            prefix = os.getenv("AIR_TENANT_SECRETS_PREFIX", "air/tenants").strip("/")
            secret = client.get_secret_value(SecretId=f"{prefix}/{tenant_id}/runtime")
            payload = json.loads(secret["SecretString"])
            cipher = Fernet(str(payload["credential_key"]).encode("ascii"))
        except Exception as exc:
            raise RuntimeError("Tenant credential encryption key is unavailable in AWS Secrets Manager") from exc
        self._tenant_ciphers[tenant_id] = cipher
        return cipher

    @_customer_scoped
    def put(self, customer_id: str, broker: str, account_id: str, credentials: dict) -> None:
        if not credentials or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in credentials.items()):
            raise ValueError("Credentials must be a non-empty map of string keys and values")
        encrypted = self._cipher_for_current_tenant().encrypt(json.dumps(credentials).encode())
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO broker_credentials
                (customer_id,broker,account_id,encrypted_payload,updated_at)
                VALUES(:customer,:broker,:account,:payload,CURRENT_TIMESTAMP)
                ON CONFLICT(customer_id,broker,account_id) DO UPDATE SET
                encrypted_payload=EXCLUDED.encrypted_payload,updated_at=CURRENT_TIMESTAMP"""),
                {"customer": customer_id.strip(), "broker": broker.strip().lower(), "account": account_id.strip(), "payload": encrypted})

    @_customer_scoped
    def get(self, customer_id: str, broker: str, account_id: str) -> dict:
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT encrypted_payload FROM broker_credentials
                WHERE customer_id=:customer AND broker=:broker AND account_id=:account"""),
                {"customer": customer_id.strip(), "broker": broker.strip().lower(), "account": account_id.strip()}).mappings().first()
        if row is None:
            raise KeyError("Broker credentials not found")
        encrypted = bytes(row["encrypted_payload"])
        tenant_cipher = self._cipher_for_current_tenant()
        try:
            return json.loads(tenant_cipher.decrypt(encrypted).decode())
        except (InvalidToken, ValueError, TypeError):
            # Existing tenants are migrated from the original shared key. On the
            # first successful read, re-encrypt the payload with the tenant key.
            try:
                payload = json.loads(self._cipher.decrypt(encrypted).decode())
            except (InvalidToken, ValueError, TypeError) as exc:
                raise RuntimeError("Stored broker credentials cannot be decrypted") from exc
            if tenant_cipher is not self._cipher:
                replacement = tenant_cipher.encrypt(json.dumps(payload).encode())
                with self.engine.begin() as conn:
                    conn.execute(text("""UPDATE broker_credentials
                        SET encrypted_payload=:payload,updated_at=CURRENT_TIMESTAMP
                        WHERE customer_id=:customer AND broker=:broker AND account_id=:account"""), {
                        "payload": replacement, "customer": customer_id.strip(),
                        "broker": broker.strip().lower(), "account": account_id.strip(),
                    })
            return payload

    @_customer_scoped
    def delete(self, customer_id: str, broker: str, account_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""DELETE FROM broker_credentials WHERE customer_id=:customer
                AND broker=:broker AND account_id=:account"""),
                {"customer": customer_id.strip(), "broker": broker.strip().lower(), "account": account_id.strip()})

    @_admin_scoped
    def list_for_all_customers(self) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT customer_id,broker,account_id,updated_at
                FROM broker_credentials ORDER BY customer_id,broker,account_id""")).mappings().all()
        return [dict(row) for row in rows]

    @_customer_scoped
    def list_for_customer(self, customer_id: str) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT broker,account_id,updated_at FROM broker_credentials
                WHERE customer_id=:customer ORDER BY broker,account_id"""), {"customer": customer_id.strip()}).mappings().all()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.engine.dispose()
