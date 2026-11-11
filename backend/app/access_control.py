import os
import re
import sqlite3
from pathlib import Path
from uuid import uuid4


_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


class AccessStore:
    """Admin-approved mobile/device access requests and revocable sessions."""

    def __new__(cls, db_path: str | None = None):
        if db_path is None and (os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE")):
            from app.customer_auth_postgres import PostgresAccessStore
            return PostgresAccessStore()
        return super().__new__(cls)

    def __init__(self, db_path: str | None = None):
        db_path = db_path or os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3")
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS air_access_requests (
                request_id TEXT PRIMARY KEY,
                mobile_e164 TEXT NOT NULL,
                device_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING','APPROVED','REJECTED','BLOCKED')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                reviewer_note TEXT,
                UNIQUE(mobile_e164, device_id)
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS air_device_sessions (
                session_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES air_access_requests(request_id),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.commit()

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
        with self.db:
            self.db.execute(
                """INSERT OR IGNORE INTO air_access_requests
                   (request_id,mobile_e164,device_id) VALUES(?,?,?)""",
                (str(uuid4()), mobile, device),
            )
        return self.get_request(mobile, device)

    def get_request(self, mobile_e164: str, device_id: str):
        return self.db.execute(
            """SELECT request_id,mobile_e164,device_id,status,created_at,reviewed_at,reviewer_note
               FROM air_access_requests WHERE mobile_e164=? AND device_id=?""",
            (mobile_e164.strip(), device_id.strip()),
        ).fetchone()

    def mobile_for_request_id(self, request_id: str) -> str | None:
        row = self.db.execute(
            "SELECT mobile_e164 FROM air_access_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
        return row["mobile_e164"] if row else None

    def list_requests(self, status: str | None = None):
        if status:
            return self.db.execute(
                """SELECT request_id,mobile_e164,device_id,status,created_at,reviewed_at,reviewer_note
                   FROM air_access_requests WHERE status=? ORDER BY created_at DESC""",
                (status.upper(),),
            ).fetchall()
        return self.db.execute(
            """SELECT request_id,mobile_e164,device_id,status,created_at,reviewed_at,reviewer_note
               FROM air_access_requests ORDER BY created_at DESC"""
        ).fetchall()

    def review(self, request_id: str, status: str, note: str = "") -> bool:
        status = status.upper()
        if status not in {"APPROVED", "REJECTED", "BLOCKED"}:
            raise ValueError("Status must be APPROVED, REJECTED or BLOCKED")
        with self.db:
            cursor = self.db.execute(
                """UPDATE air_access_requests SET status=?, reviewed_at=CURRENT_TIMESTAMP,
                   reviewer_note=? WHERE request_id=?""",
                (status, note[:500], request_id),
            )
            if cursor.rowcount and status != "APPROVED":
                self.db.execute(
                    """UPDATE air_device_sessions SET active=0 WHERE request_id=?""",
                    (request_id,),
                )
        return cursor.rowcount > 0

    def create_session(self, request_id: str) -> str:
        row = self.db.execute(
            "SELECT status FROM air_access_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        if not row or row["status"] != "APPROVED":
            raise PermissionError("AIR administrator approval is required")
        session_id = str(uuid4())
        with self.db:
            self.db.execute(
                "INSERT INTO air_device_sessions(session_id,request_id) VALUES(?,?)",
                (session_id, request_id),
            )
        return session_id

    def is_session_active(self, session_id: str) -> bool:
        row = self.db.execute(
            """SELECT s.active,r.status FROM air_device_sessions s
               JOIN air_access_requests r ON r.request_id=s.request_id
               WHERE s.session_id=?""",
            (session_id,),
        ).fetchone()
        return bool(row and row["active"] and row["status"] == "APPROVED")

    def close(self):
        self.db.close()


access_store = AccessStore()
