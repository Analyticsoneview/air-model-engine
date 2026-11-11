"""PostgreSQL stores for customer credentials and approved device sessions.

SQLite remains the default until AIR_CUSTOMER_DATABASE_URL is explicitly set.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_E164 = re.compile(r"^\\+[1-9][0-9]{7,14}$")


def customer_database_url() -> str:
    secret_file = os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE")
    value = Path(secret_file).read_text(encoding="utf-8").strip() if secret_file else os.getenv("AIR_CUSTOMER_DATABASE_URL", "").strip()
    if not value or not value.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("AIR_CUSTOMER_DATABASE_URL or AIR_CUSTOMER_DATABASE_URL_FILE must point to PostgreSQL")
    return value


class _PostgresStore:
    def __init__(self, database_url: str | None = None):
        self.engine: Engine = create_engine(database_url or customer_database_url(), pool_pre_ping=True, future=True)

    def close(self) -> None:
        self.engine.dispose()


class PostgresAuthStore(_PostgresStore):
    def create_customer(self, customer_id: str, email: str, password_hash: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO customers(customer_id,email,password_hash)
                VALUES(:id,:email,:password)"""),
                {"id": customer_id, "email": email.strip().lower(), "password": password_hash})

    def get_by_email(self, email: str):
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT customer_id,email,password_hash,is_active
                FROM customers WHERE lower(email)=:email"""),
                {"email": email.strip().lower()}).mappings().first()
        return row

    def is_active(self, customer_id: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT is_active FROM customers WHERE customer_id=:id"),
                               {"id": customer_id}).first()
        return bool(row and row.is_active)


class PostgresAccessStore(_PostgresStore):
    @staticmethod
    def validate_mobile(mobile_e164: str) -> str:
        value = mobile_e164.strip()
        if not _E164.fullmatch(value):
            raise ValueError("Enter a valid international number in E.164 format, for example +14155550123")
        return value

    def request_access(self, mobile_e164: str, device_id: str):
        mobile = self.validate_mobile(mobile_e164)
        device = device_id.strip()
        if not device or len(device) > 128:
            raise ValueError("A valid device identifier is required")
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO air_access_requests(request_id,mobile_e164,device_id)
                VALUES(:id,:mobile,:device) ON CONFLICT (mobile_e164,device_id) DO NOTHING"""),
                {"id": str(uuid4()), "mobile": mobile, "device": device})
            row = conn.execute(text("""SELECT request_id,mobile_e164,device_id,status,created_at,reviewed_at,reviewer_note
                FROM air_access_requests WHERE mobile_e164=:mobile AND device_id=:device"""),
                {"mobile": mobile, "device": device}).mappings().one()
        return row

    def get_request(self, mobile_e164: str, device_id: str):
        with self.engine.connect() as conn:
            return conn.execute(text("""SELECT request_id,mobile_e164,device_id,status,created_at,reviewed_at,reviewer_note
                FROM air_access_requests WHERE mobile_e164=:mobile AND device_id=:device"""),
                {"mobile": mobile_e164.strip(), "device": device_id.strip()}).mappings().first()

    def mobile_for_request_id(self, request_id: str) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT mobile_e164 FROM air_access_requests WHERE request_id=:id"),
                               {"id": request_id}).first()
        return row.mobile_e164 if row else None

    def list_requests(self, status: str | None = None):
        statement = """SELECT request_id,mobile_e164,device_id,status,created_at,reviewed_at,reviewer_note
            FROM air_access_requests"""
        params = {}
        if status:
            statement += " WHERE status=:status"
            params["status"] = status.upper()
        statement += " ORDER BY created_at DESC,request_id"
        with self.engine.connect() as conn:
            return conn.execute(text(statement), params).mappings().all()

    def review(self, request_id: str, status: str, note: str = "") -> bool:
        status = status.upper()
        if status not in {"APPROVED", "REJECTED", "BLOCKED"}:
            raise ValueError("Status must be APPROVED, REJECTED or BLOCKED")
        with self.engine.begin() as conn:
            updated = conn.execute(text("""UPDATE air_access_requests
                SET status=:status,reviewed_at=now(),reviewer_note=:note WHERE request_id=:id"""),
                {"status": status, "note": note[:500], "id": request_id})
            if updated.rowcount and status != "APPROVED":
                conn.execute(text("UPDATE air_device_sessions SET active=false WHERE request_id=:id"),
                             {"id": request_id})
        return updated.rowcount > 0

    def create_session(self, request_id: str) -> str:
        session_id = str(uuid4())
        with self.engine.begin() as conn:
            row = conn.execute(text("""SELECT status FROM air_access_requests
                WHERE request_id=:id FOR UPDATE"""), {"id": request_id}).first()
            if not row or row.status != "APPROVED":
                raise PermissionError("AIR administrator approval is required")
            conn.execute(text("INSERT INTO air_device_sessions(session_id,request_id) VALUES(:sid,:rid)"),
                         {"sid": session_id, "rid": request_id})
        return session_id

    def is_session_active(self, session_id: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT s.active,r.status FROM air_device_sessions s
                JOIN air_access_requests r ON r.request_id=s.request_id WHERE s.session_id=:sid"""),
                {"sid": session_id}).first()
        return bool(row and row.active and row.status == "APPROVED")
