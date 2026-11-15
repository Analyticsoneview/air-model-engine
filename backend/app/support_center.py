"""Customer-isolated support tickets with an append-only activity history."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.db_compat import PostgresConnection, read_database_url

_STATUSES = {"OPEN", "IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED", "CLOSED"}
_PRIORITIES = {"LOW", "NORMAL", "HIGH", "URGENT"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupportStore:
    def __init__(self, db_path: str | None = None):
        url = None if db_path is not None else (
            read_database_url("AIR_CUSTOMER_DATABASE_URL") or read_database_url("AIR_DATABASE_URL")
        )
        self.is_postgres = bool(url)
        if url:
            self.db = PostgresConnection(url)
            try:
                self.db.execute("SELECT 1 FROM air_support_tickets LIMIT 0")
                self.db.execute("SELECT 1 FROM air_support_ticket_events LIMIT 0")
            except Exception as exc:
                self.db.close()
                raise RuntimeError("Support PostgreSQL schema is missing; apply Alembic migrations first") from exc
        else:
            path = db_path or os.getenv("AIR_SUPPORT_DB_PATH", "data/air_support.sqlite3")
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=30000")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS air_support_tickets(
                    ticket_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
                    subject TEXT NOT NULL, category TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN', priority TEXT NOT NULL DEFAULT 'NORMAL',
                    assigned_admin_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_air_support_customer_updated
                    ON air_support_tickets(customer_id,updated_at);
                CREATE INDEX IF NOT EXISTS ix_air_support_status_updated
                    ON air_support_tickets(status,updated_at);
                CREATE TABLE IF NOT EXISTS air_support_ticket_events(
                    event_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL, actor_id TEXT NOT NULL,
                    event_type TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_air_support_events_ticket
                    ON air_support_ticket_events(ticket_id,created_at);
                CREATE TRIGGER IF NOT EXISTS trg_air_support_events_no_update
                BEFORE UPDATE ON air_support_ticket_events BEGIN
                    SELECT RAISE(ABORT,'air_support_ticket_events is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_air_support_events_no_delete
                BEFORE DELETE ON air_support_ticket_events BEGIN
                    SELECT RAISE(ABORT,'air_support_ticket_events is append-only');
                END;
            """)
            self.db.commit()

    def _event(self, ticket_id: str, actor_type: str, actor_id: str,
               event_type: str, message: str = "", metadata: dict | None = None) -> None:
        self.db.execute("""INSERT INTO air_support_ticket_events
            (event_id,ticket_id,actor_type,actor_id,event_type,message,metadata_json,created_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (str(uuid4()), ticket_id, actor_type, actor_id, event_type,
             message, json.dumps(metadata or {}, separators=(",", ":")), _now()))

    def create(self, customer_id: str, subject: str, category: str, message: str) -> dict:
        subject, category, message = subject.strip(), category.strip().upper(), message.strip()
        if not customer_id or len(customer_id) > 16:
            raise ValueError("A valid customer identity is required")
        if not 5 <= len(subject) <= 120:
            raise ValueError("Subject must contain 5 to 120 characters")
        if category not in {"ACCOUNT", "BILLING", "BROKER", "TECHNICAL", "GENERAL"}:
            raise ValueError("Unsupported support category")
        if not 10 <= len(message) <= 5000:
            raise ValueError("Message must contain 10 to 5000 characters")
        ticket_id, now = str(uuid4()), _now()
        with self.db:
            self.db.execute("""INSERT INTO air_support_tickets
                (ticket_id,customer_id,subject,category,status,priority,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (ticket_id, customer_id, subject, category, "OPEN", "NORMAL", now, now))
            self._event(ticket_id, "CUSTOMER", customer_id, "TICKET_CREATED", message)
        return self.get_customer_ticket(customer_id, ticket_id)

    def _ticket(self, row) -> dict:
        result = dict(row)
        result["events"] = [dict(e) | {"metadata": json.loads(e["metadata_json"])}
            for e in self.db.execute("""SELECT event_id,actor_type,actor_id,event_type,message,
                metadata_json,created_at FROM air_support_ticket_events
                WHERE ticket_id=? ORDER BY created_at,event_id""", (result["ticket_id"],)).fetchall()]
        for event in result["events"]:
            event.pop("metadata_json", None)
        return result

    def get_customer_ticket(self, customer_id: str, ticket_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM air_support_tickets WHERE ticket_id=? AND customer_id=?",
                              (ticket_id, customer_id)).fetchone()
        return self._ticket(row) if row else None

    def list_customer(self, customer_id: str, limit: int = 100) -> list[dict]:
        rows = self.db.execute("""SELECT * FROM air_support_tickets WHERE customer_id=?
            ORDER BY updated_at DESC,ticket_id LIMIT ?""", (customer_id, max(1,min(limit,200)))).fetchall()
        return [self._ticket(row) for row in rows]

    def list_admin(self, status: str | None = None, limit: int = 200) -> list[dict]:
        if status and status not in _STATUSES:
            raise ValueError("Unsupported ticket status")
        sql = "SELECT * FROM air_support_tickets"
        params: tuple = ()
        if status:
            sql += " WHERE status=?"
            params = (status,)
        sql += " ORDER BY CASE priority WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'NORMAL' THEN 2 ELSE 3 END, updated_at DESC LIMIT ?"
        rows = self.db.execute(sql, (*params, max(1,min(limit,500)))).fetchall()
        return [self._ticket(row) for row in rows]

    def customer_reply(self, customer_id: str, ticket_id: str, message: str) -> dict:
        message = message.strip()
        if not 10 <= len(message) <= 5000:
            raise ValueError("Reply must contain 10 to 5000 characters")
        with self.db:
            row = self.db.execute("SELECT status FROM air_support_tickets WHERE ticket_id=? AND customer_id=?",
                                  (ticket_id, customer_id)).fetchone()
            if not row:
                return None
            if row["status"] == "CLOSED":
                raise ValueError("Closed tickets cannot receive replies")
            now = _now()
            self.db.execute("UPDATE air_support_tickets SET status='OPEN',updated_at=? WHERE ticket_id=?",
                            (now,ticket_id))
            self._event(ticket_id,"CUSTOMER",customer_id,"CUSTOMER_REPLY",message)
        return self.get_customer_ticket(customer_id,ticket_id)

    def admin_update(self, ticket_id: str, admin_id: str, message: str = "",
                     status: str | None = None, priority: str | None = None,
                     assigned_admin_id: str | None = None) -> dict | None:
        message = message.strip()
        if len(message) > 5000:
            raise ValueError("Reply must not exceed 5000 characters")
        if status is not None and status not in _STATUSES:
            raise ValueError("Unsupported ticket status")
        if priority is not None and priority not in _PRIORITIES:
            raise ValueError("Unsupported ticket priority")
        with self.db:
            row = self.db.execute("SELECT * FROM air_support_tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            if not row:
                return None
            if row["status"] == "CLOSED" and (message or status not in (None, "CLOSED")):
                raise ValueError("Closed tickets cannot be modified")
            now = _now()
            new_status = status or row["status"]
            new_priority = priority or row["priority"]
            new_assignee = assigned_admin_id if assigned_admin_id is not None else row["assigned_admin_id"]
            self.db.execute("""UPDATE air_support_tickets SET status=?,priority=?,assigned_admin_id=?,updated_at=?
                WHERE ticket_id=?""", (new_status,new_priority,new_assignee,now,ticket_id))
            if status and status != row["status"]:
                self._event(ticket_id,"ADMIN",admin_id,"STATUS_CHANGED","",{"from":row["status"],"to":status})
            if priority and priority != row["priority"]:
                self._event(ticket_id,"ADMIN",admin_id,"PRIORITY_CHANGED","",{"from":row["priority"],"to":priority})
            if assigned_admin_id is not None and assigned_admin_id != row["assigned_admin_id"]:
                self._event(ticket_id,"ADMIN",admin_id,"ASSIGNED","",{"assigned_admin_id":assigned_admin_id})
            if message:
                self._event(ticket_id,"ADMIN",admin_id,"ADMIN_REPLY",message)
        return self._ticket(self.db.execute("SELECT * FROM air_support_tickets WHERE ticket_id=?",(ticket_id,)).fetchone())

    def close(self) -> None:
        self.db.close()
