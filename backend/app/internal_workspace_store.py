"""Persistent owner-scoped private watchlists and research notes."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4


class InternalWorkspaceStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv(
            "AIR_INTERNAL_WORKSPACE_DB_PATH", "data/internal_workspace.sqlite3"
        )
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=15000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS internal_workspace_items (
            item_id TEXT PRIMARY KEY,
            owner_admin_id TEXT NOT NULL,
            item_type TEXT NOT NULL CHECK(item_type IN ('WATCHLIST','RESEARCH_NOTE')),
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        self.db.execute("""CREATE INDEX IF NOT EXISTS idx_internal_items_owner_type
            ON internal_workspace_items(owner_admin_id,item_type,updated_at)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS internal_workspace_audit (
            event_id TEXT PRIMARY KEY,
            owner_admin_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            item_type TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('CREATE','UPDATE','DELETE')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        self.db.commit()

    def _record(self, owner: str, item_id: str, kind: str, action: str) -> None:
        self.db.execute(
            "INSERT INTO internal_workspace_audit(event_id,owner_admin_id,item_id,item_type,action) VALUES(?,?,?,?,?)",
            (str(uuid4()), owner, item_id, kind, action),
        )

    @staticmethod
    def _serialize(row: sqlite3.Row) -> dict:
        return {
            "item_id": row["item_id"],
            "type": row["item_type"],
            "title": row["title"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "classification": "INTERNAL — NOT FOR DISTRIBUTION",
        }

    def list_items(self, owner: str, kind: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM internal_workspace_items
               WHERE owner_admin_id=? AND item_type=? ORDER BY updated_at DESC,item_id""",
            (owner, kind),
        ).fetchall()
        return [self._serialize(row) for row in rows]

    def get_item(self, owner: str, item_id: str, kind: str) -> dict | None:
        row = self.db.execute(
            """SELECT * FROM internal_workspace_items
               WHERE owner_admin_id=? AND item_id=? AND item_type=?""",
            (owner, item_id, kind),
        ).fetchone()
        return self._serialize(row) if row else None

    def create_item(self, owner: str, kind: str, title: str, payload: dict) -> dict:
        item_id = str(uuid4())
        with self.db:
            self.db.execute(
                """INSERT INTO internal_workspace_items
                   (item_id,owner_admin_id,item_type,title,payload_json)
                   VALUES(?,?,?,?,?)""",
                (item_id, owner, kind, title.strip(), json.dumps(payload, separators=(",", ":"), ensure_ascii=False)),
            )
            self._record(owner, item_id, kind, "CREATE")
        result = self.get_item(owner, item_id, kind)
        assert result is not None
        return result

    def update_item(self, owner: str, item_id: str, kind: str, title: str, payload: dict) -> dict | None:
        with self.db:
            cursor = self.db.execute(
                """UPDATE internal_workspace_items SET title=?,payload_json=?,updated_at=CURRENT_TIMESTAMP
                   WHERE owner_admin_id=? AND item_id=? AND item_type=?""",
                (title.strip(), json.dumps(payload, separators=(",", ":"), ensure_ascii=False), owner, item_id, kind),
            )
            if cursor.rowcount != 1:
                return None
            self._record(owner, item_id, kind, "UPDATE")
        return self.get_item(owner, item_id, kind)

    def delete_item(self, owner: str, item_id: str, kind: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                """DELETE FROM internal_workspace_items
                   WHERE owner_admin_id=? AND item_id=? AND item_type=?""",
                (owner, item_id, kind),
            )
            if cursor.rowcount != 1:
                return False
            self._record(owner, item_id, kind, "DELETE")
        return True

    def audit(self, owner: str, limit: int = 100) -> list[dict]:
        rows = self.db.execute(
            """SELECT item_id,item_type,action,created_at FROM internal_workspace_audit
               WHERE owner_admin_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?""",
            (owner, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.db.close()
