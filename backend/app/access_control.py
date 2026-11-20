import os
import re
import sqlite3
from pathlib import Path
from uuid import uuid4


_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


class AccessStore:
    """Phone-number onboarding, revocable device sessions and subscription entitlements."""

    def __new__(cls, db_path: str | None = None):
        if db_path is None and (os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE")):
            from app.customer_auth_postgres import PostgresAccessStore
            return PostgresAccessStore()
        return super().__new__(cls)

    def __init__(self, db_path: str | None = None):
        db_path = db_path or os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3")
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=30000')
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
            CREATE TABLE IF NOT EXISTS air_access_decision_history (
                decision_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, mobile_e164 TEXT NOT NULL,
                previous_status TEXT NOT NULL, new_status TEXT NOT NULL, reviewer_admin_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', totp_counter INTEGER NOT NULL,
                decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_air_access_decisions_request ON air_access_decision_history(request_id, decided_at)")
        decision_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(air_access_decision_history)")}
        for name, declaration in {
            "totp_verified_at": "TEXT", "verification_reference": "TEXT",
            "device_id": "TEXT", "request_context": "TEXT NOT NULL DEFAULT '{}'",
        }.items():
            if name not in decision_columns:
                self.db.execute(f"ALTER TABLE air_access_decision_history ADD COLUMN {name} {declaration}")
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_customer_lifecycle(
            customer_id TEXT PRIMARY KEY, first_registered_at TEXT NOT NULL,
            first_approved_at TEXT, first_rejected_at TEXT, first_plan_availed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_customer_subscription_history(
            assignment_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, plan_code TEXT NOT NULL,
            starts_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL,
            assigned_by_admin_id TEXT, assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        lifecycle_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(air_customer_lifecycle)")}
        if "first_rejected_at" not in lifecycle_columns:
            self.db.execute("ALTER TABLE air_customer_lifecycle ADD COLUMN first_rejected_at TEXT")
        self.db.executescript("""
            CREATE TRIGGER IF NOT EXISTS trg_air_access_decision_no_update
            BEFORE UPDATE ON air_access_decision_history BEGIN
                SELECT RAISE(ABORT, 'air_access_decision_history is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_air_access_decision_no_delete
            BEFORE DELETE ON air_access_decision_history BEGIN
                SELECT RAISE(ABORT, 'air_access_decision_history is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_air_subscription_history_no_update
            BEFORE UPDATE ON air_customer_subscription_history BEGIN
                SELECT RAISE(ABORT, 'air_customer_subscription_history is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_air_subscription_history_no_delete
            BEFORE DELETE ON air_customer_subscription_history BEGIN
                SELECT RAISE(ABORT, 'air_customer_subscription_history is append-only');
            END;
        """)
        self.db.commit()
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS air_device_sessions (
                session_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES air_access_requests(request_id),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS air_customer_subscriptions (
                customer_id TEXT PRIMARY KEY,
                plan_code TEXT NOT NULL CHECK(plan_code IN ('DAILY','MONTHLY','SIX_MONTHS','YEARLY')),
                starts_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','CANCELLED','EXPIRED')),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS air_customer_marketing_preferences (
                customer_id TEXT PRIMARY KEY,
                promotional_consent INTEGER NOT NULL DEFAULT 0 CHECK(promotional_consent IN (0,1)),
                consent_updated_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS air_marketing_offers (
                offer_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                offer_code TEXT NOT NULL UNIQUE,
                plan_code TEXT NOT NULL CHECK(plan_code IN ('DAILY','MONTHLY','SIX_MONTHS','YEARLY')),
                discount_percent REAL NOT NULL CHECK(discount_percent > 0 AND discount_percent <= 90),
                starts_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                terms TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','APPROVED','REVOKED')),
                created_by TEXT NOT NULL,
                approved_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                approved_at TEXT
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS air_marketing_audit (
                event_id TEXT PRIMARY KEY,
                actor_customer_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_id TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.commit()
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_auth_schema_migrations(
            version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        # Serialize the one-time legacy backfill and re-check its marker inside the write lock.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            migrated = self.db.execute(
                "SELECT 1 FROM air_auth_schema_migrations WHERE version='customer_lifecycle_v1'"
            ).fetchone()
            if not migrated:
                self.db.execute("""INSERT OR IGNORE INTO air_customer_lifecycle(customer_id,first_registered_at)
                    SELECT mobile_e164,MIN(created_at) FROM air_access_requests GROUP BY mobile_e164""")
                self.db.execute("""UPDATE air_customer_lifecycle SET first_approved_at=(
                    SELECT MIN(decided_at) FROM air_access_decision_history
                    WHERE mobile_e164=air_customer_lifecycle.customer_id AND new_status='APPROVED')
                    WHERE first_approved_at IS NULL AND EXISTS(
                    SELECT 1 FROM air_access_decision_history WHERE mobile_e164=air_customer_lifecycle.customer_id
                    AND new_status='APPROVED')""")
                self.db.execute("""UPDATE air_customer_lifecycle SET first_rejected_at=(
                    SELECT MIN(decided_at) FROM air_access_decision_history
                    WHERE mobile_e164=air_customer_lifecycle.customer_id AND new_status='REJECTED')
                    WHERE first_rejected_at IS NULL AND EXISTS(
                    SELECT 1 FROM air_access_decision_history WHERE mobile_e164=air_customer_lifecycle.customer_id
                    AND new_status='REJECTED')""")
                self.db.execute("""UPDATE air_customer_lifecycle SET first_approved_at=(
                    SELECT MIN(reviewed_at) FROM air_access_requests
                    WHERE mobile_e164=air_customer_lifecycle.customer_id
                      AND status='APPROVED' AND reviewed_at IS NOT NULL)
                    WHERE first_approved_at IS NULL AND EXISTS(
                    SELECT 1 FROM air_access_requests WHERE mobile_e164=air_customer_lifecycle.customer_id
                      AND status='APPROVED' AND reviewed_at IS NOT NULL)""")
                self.db.execute("""UPDATE air_customer_lifecycle SET first_rejected_at=(
                    SELECT MIN(reviewed_at) FROM air_access_requests
                    WHERE mobile_e164=air_customer_lifecycle.customer_id
                      AND status='REJECTED' AND reviewed_at IS NOT NULL)
                    WHERE first_rejected_at IS NULL AND EXISTS(
                    SELECT 1 FROM air_access_requests WHERE mobile_e164=air_customer_lifecycle.customer_id
                      AND status='REJECTED' AND reviewed_at IS NOT NULL)""")
                self.db.execute("""INSERT OR IGNORE INTO air_customer_subscription_history
                    (assignment_id,customer_id,plan_code,starts_at,expires_at,status,assigned_at)
                    SELECT lower(hex(randomblob(16))),customer_id,plan_code,starts_at,expires_at,status,updated_at
                    FROM air_customer_subscriptions""")
                self.db.execute("""UPDATE air_customer_lifecycle SET first_plan_availed_at=(
                    SELECT MIN(assigned_at) FROM air_customer_subscription_history
                    WHERE customer_id=air_customer_lifecycle.customer_id)
                    WHERE first_plan_availed_at IS NULL AND EXISTS(
                    SELECT 1 FROM air_customer_subscription_history WHERE customer_id=air_customer_lifecycle.customer_id)""")
                self.db.execute("INSERT INTO air_auth_schema_migrations(version) VALUES('customer_lifecycle_v1')")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        self.db.execute("""CREATE TABLE IF NOT EXISTS air_customer_pin_credentials(
            customer_id TEXT PRIMARY KEY, pin_hash TEXT, failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0, must_reset INTEGER NOT NULL DEFAULT 0,
            suspended INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reset_by_admin_id TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_customer_pin_audit(
            event_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, action TEXT NOT NULL,
            actor_admin_id TEXT, details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
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
                   (request_id,mobile_e164,device_id,status) VALUES(?,?,?,'PENDING')""",
                (str(uuid4()), mobile, device),
            )
        row = self.get_request(mobile, device)
        with self.db:
            self.db.execute("""INSERT INTO air_customer_lifecycle(customer_id,first_registered_at)
                VALUES(?,?) ON CONFLICT(customer_id) DO UPDATE SET
                first_registered_at=MIN(air_customer_lifecycle.first_registered_at,excluded.first_registered_at),
                updated_at=CURRENT_TIMESTAMP""", (mobile, row["created_at"]))
        return row

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
        where, params = (" WHERE r.status=?", (status.upper(),)) if status else ("", ())
        return self.db.execute("""SELECT r.request_id,r.mobile_e164,r.device_id,r.status,r.created_at,
            r.reviewed_at,r.reviewer_note,
            CASE WHEN r.request_id=(SELECT r2.request_id FROM air_access_requests r2
                WHERE r2.mobile_e164=r.mobile_e164 ORDER BY r2.created_at,r2.request_id LIMIT 1)
                THEN 'NEW' ELSE 'EXISTING' END AS customer_type,
            (SELECT MIN(r3.created_at) FROM air_access_requests r3 WHERE r3.mobile_e164=r.mobile_e164)
                AS first_registered_at
            FROM air_access_requests r""" + where + " ORDER BY r.created_at DESC,r.request_id", params).fetchall()

    def get_request_by_id(self, request_id: str):
        return self.db.execute("SELECT * FROM air_access_requests WHERE request_id=?", (request_id,)).fetchone()

    def decision_history(self, request_id: str):
        rows = self.db.execute("""SELECT decision_id,request_id,mobile_e164,previous_status,new_status,
            reviewer_admin_id,reviewer_role,note,totp_counter,totp_verified_at,verification_reference,
            device_id,request_context,decided_at
            FROM air_access_decision_history WHERE request_id=? ORDER BY decided_at,decision_id""",
            (request_id,)).fetchall()
        import json
        return [{**dict(row), "request_context": json.loads(row["request_context"] or "{}")} for row in rows]

    def list_decisions(self, start_date: str | None = None, end_date: str | None = None):
        clauses, params = [], []
        if start_date: clauses.append("date(decided_at)>=date(?)"); params.append(start_date)
        if end_date: clauses.append("date(decided_at)<=date(?)"); params.append(end_date)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.execute("""SELECT decision_id,request_id,mobile_e164,previous_status,new_status,
            reviewer_admin_id,reviewer_role,note,totp_counter,totp_verified_at,verification_reference,device_id,request_context,decided_at FROM air_access_decision_history""" +
            where + " ORDER BY decided_at DESC,decision_id DESC", params).fetchall()
        import json
        return [{**dict(row), "request_context": json.loads(row["request_context"] or "{}")} for row in rows]

    def review(self, request_id: str, status: str, note: str = "", reviewer_admin_id: str = "",
               reviewer_role: str = "", totp_counter: int = -1, verification_reference: str | None = None,
               totp_verified_at=None, request_context: dict | None = None) -> bool:
        import json
        from datetime import datetime, timezone
        status = status.upper()
        if status not in {"APPROVED", "REJECTED", "BLOCKED"}:
            raise ValueError("Status must be APPROVED, REJECTED or BLOCKED")
        verified_at = totp_verified_at or datetime.now(timezone.utc)
        verification_reference = verification_reference or str(uuid4())
        with self.db:
            current = self.db.execute("SELECT mobile_e164,device_id,status,created_at FROM air_access_requests WHERE request_id=?",
                                       (request_id,)).fetchone()
            if not current: return False
            cursor = self.db.execute("""UPDATE air_access_requests SET status=?,reviewed_at=CURRENT_TIMESTAMP,
                reviewer_note=? WHERE request_id=?""", (status, note[:500], request_id))
            if cursor.rowcount:
                self.db.execute("""INSERT INTO air_access_decision_history
                    (decision_id,request_id,mobile_e164,previous_status,new_status,reviewer_admin_id,
                     reviewer_role,note,totp_counter,totp_verified_at,verification_reference,device_id,request_context)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid4()), request_id, current["mobile_e164"], current["status"], status,
                     reviewer_admin_id, reviewer_role, note[:500], int(totp_counter),
                     verified_at.isoformat(), verification_reference, current["device_id"],
                     json.dumps(request_context or {})))
                if status in {"APPROVED", "REJECTED"}:
                    lifecycle_column = "first_approved_at" if status == "APPROVED" else "first_rejected_at"
                    decision_at = self.db.execute(
                        "SELECT reviewed_at FROM air_access_requests WHERE request_id=?", (request_id,)
                    ).fetchone()[0] or verified_at.isoformat()
                    self.db.execute(f"""INSERT INTO air_customer_lifecycle
                        (customer_id,first_registered_at,{lifecycle_column}) VALUES(?,?,?)
                        ON CONFLICT(customer_id) DO UPDATE SET
                        {lifecycle_column}=COALESCE(air_customer_lifecycle.{lifecycle_column},excluded.{lifecycle_column}),
                        updated_at=CURRENT_TIMESTAMP""",
                        (current["mobile_e164"], current["created_at"], decision_at))
                else:
                    self.db.execute("UPDATE air_device_sessions SET active=0 WHERE request_id=?", (request_id,))
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

    def customer_has_approved_access(self, mobile_e164: str) -> bool:
        mobile = self.validate_mobile(mobile_e164)
        row = self.db.execute("SELECT 1 FROM air_access_requests WHERE mobile_e164=? AND status='APPROVED' LIMIT 1",
                              (mobile,)).fetchone()
        return bool(row)

    def customer_pin_state(self, mobile_e164: str) -> dict:
        mobile = self.validate_mobile(mobile_e164)
        row = self.db.execute("SELECT pin_hash,must_reset,suspended,locked_until FROM air_customer_pin_credentials WHERE customer_id=?",
                              (mobile,)).fetchone()
        if not row:
            return {"pin_set": False, "must_reset": False, "suspended": False, "locked_until": 0}
        return {"pin_set": bool(row["pin_hash"]), "must_reset": bool(row["must_reset"]),
                "suspended": bool(row["suspended"]), "locked_until": int(row["locked_until"] or 0)}

    def set_customer_pin(self, mobile_e164: str, device_id: str, pin_hash: str) -> None:
        mobile = self.validate_mobile(mobile_e164)
        request = self.get_request(mobile, device_id)
        if not request or request["status"] != "APPROVED":
            raise PermissionError("The initially approved device is required to set the first AIR PIN")
        existing = self.db.execute("SELECT pin_hash,must_reset,suspended FROM air_customer_pin_credentials WHERE customer_id=?",
                                   (mobile,)).fetchone()
        if existing and existing["suspended"]:
            raise PermissionError("AIR customer account is suspended")
        if existing and existing["pin_hash"] and not existing["must_reset"]:
            raise PermissionError("An AIR PIN is already configured; use administrator reset if it is forgotten")
        with self.db:
            self.db.execute("""INSERT INTO air_customer_pin_credentials(customer_id,pin_hash,failed_attempts,locked_until,must_reset)
                VALUES(?,?,0,0,0) ON CONFLICT(customer_id) DO UPDATE SET pin_hash=excluded.pin_hash,
                failed_attempts=0,locked_until=0,must_reset=0,updated_at=CURRENT_TIMESTAMP""", (mobile,pin_hash))
            self.db.execute("INSERT INTO air_customer_pin_audit(event_id,customer_id,action,details) VALUES(?,?,?,?)",
                            (str(uuid4()),mobile,"PIN_SET","Customer completed initial PIN setup"))

    def verify_customer_pin(self, mobile_e164: str, pin: str) -> bool:
        import time
        from app.security import verify_pin
        mobile = self.validate_mobile(mobile_e164)
        row = self.db.execute("SELECT pin_hash,failed_attempts,locked_until,must_reset,suspended FROM air_customer_pin_credentials WHERE customer_id=?",
                              (mobile,)).fetchone()
        if not row or not row["pin_hash"] or row["must_reset"]:
            raise LookupError("PIN_SETUP_REQUIRED")
        now = int(time.time())
        if row["suspended"]:
            raise PermissionError("AIR customer account is suspended")
        if int(row["locked_until"] or 0) > now:
            raise PermissionError("Too many incorrect PIN attempts. Try again later.")
        if not verify_pin(pin, row["pin_hash"]):
            attempts = int(row["failed_attempts"] or 0) + 1
            locked_until = now + 900 if attempts >= 5 else 0
            with self.db:
                self.db.execute("UPDATE air_customer_pin_credentials SET failed_attempts=?,locked_until=?,updated_at=CURRENT_TIMESTAMP WHERE customer_id=?",
                                (attempts,locked_until,mobile))
            return False
        with self.db:
            self.db.execute("UPDATE air_customer_pin_credentials SET failed_attempts=0,locked_until=0,updated_at=CURRENT_TIMESTAMP WHERE customer_id=?",
                            (mobile,))
        return True

    def register_approved_device(self, mobile_e164: str, device_id: str):
        mobile = self.validate_mobile(mobile_e164)
        device = device_id.strip()
        if not device or len(device) > 128:
            raise ValueError("A valid device identifier is required")
        pin_state = self.customer_pin_state(mobile)
        if pin_state["suspended"]:
            raise PermissionError("AIR customer account is suspended")
        if not self.customer_has_approved_access(mobile):
            raise PermissionError("Initial AIR administrator approval is required")
        existing = self.get_request(mobile, device)
        if existing:
            if existing["status"] != "APPROVED":
                raise PermissionError("This device is blocked or was rejected; contact AIR support")
            return existing
        with self.db:
            self.db.execute("""INSERT INTO air_access_requests(request_id,mobile_e164,device_id,status,reviewer_note)
                VALUES(?,?,?,'APPROVED','Automatically registered to an existing approved AIR customer')""",
                (str(uuid4()),mobile,device))
            row = self.get_request(mobile,device)
            self.db.execute("""INSERT INTO air_customer_lifecycle(customer_id,first_registered_at)
                VALUES(?,?) ON CONFLICT(customer_id) DO NOTHING""",(mobile,row["created_at"]))
        return row

    def reset_customer_pin(self, mobile_e164: str, admin_id: str) -> None:
        mobile = self.validate_mobile(mobile_e164)
        if not self.customer_has_approved_access(mobile):
            raise LookupError("AIR customer was not found or has never been approved")
        with self.db:
            self.db.execute("""INSERT INTO air_customer_pin_credentials(customer_id,pin_hash,must_reset,failed_attempts,locked_until,reset_by_admin_id)
                VALUES(?,NULL,1,0,0,?) ON CONFLICT(customer_id) DO UPDATE SET pin_hash=NULL,must_reset=1,
                failed_attempts=0,locked_until=0,reset_by_admin_id=excluded.reset_by_admin_id,updated_at=CURRENT_TIMESTAMP""",
                (mobile,admin_id))
            self.db.execute("""UPDATE air_device_sessions SET active=0 WHERE request_id IN
                (SELECT request_id FROM air_access_requests WHERE mobile_e164=?)""",(mobile,))
            self.db.execute("INSERT INTO air_customer_pin_audit(event_id,customer_id,action,actor_admin_id,details) VALUES(?,?,?,?,?)",
                            (str(uuid4()),mobile,"ADMIN_PIN_RESET",admin_id,"PIN reset; all customer sessions revoked"))

    def suspend_customer(self, mobile_e164: str, admin_id: str, suspended: bool = True) -> None:
        mobile = self.validate_mobile(mobile_e164)
        with self.db:
            self.db.execute("""INSERT INTO air_customer_pin_credentials(customer_id,suspended)
                VALUES(?,?) ON CONFLICT(customer_id) DO UPDATE SET suspended=excluded.suspended,updated_at=CURRENT_TIMESTAMP""",
                (mobile,int(suspended)))
            if suspended:
                self.db.execute("""UPDATE air_device_sessions SET active=0 WHERE request_id IN
                    (SELECT request_id FROM air_access_requests WHERE mobile_e164=?)""",(mobile,))
            self.db.execute("INSERT INTO air_customer_pin_audit(event_id,customer_id,action,actor_admin_id,details) VALUES(?,?,?,?,?)",
                            (str(uuid4()),mobile,"CUSTOMER_SUSPENDED" if suspended else "CUSTOMER_REACTIVATED",admin_id,"Admin account status change"))

    @staticmethod
    def _subscription_datetime(value: str):
        from datetime import datetime, timezone
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Subscription timestamps must be non-empty ISO-8601 strings")
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def assign_subscription(self, customer_id: str, plan_code: str, starts_at: str, expires_at: str, assigned_by_admin_id: str | None = None):
        plan = plan_code.upper()
        if plan not in {"DAILY", "MONTHLY", "SIX_MONTHS", "YEARLY"}:
            raise ValueError("Unsupported AIR subscription plan")
        starts = self._subscription_datetime(starts_at)
        expires = self._subscription_datetime(expires_at)
        if expires <= starts:
            raise ValueError("Subscription expiry must be later than its start date")
        from datetime import datetime, timezone
        with self.db:
            assigned_at = datetime.now(timezone.utc).isoformat()
            self.db.execute(
                """INSERT INTO air_customer_subscriptions
                   (customer_id,plan_code,starts_at,expires_at,status,updated_at)
                   VALUES(?,?,?,?, 'ACTIVE', CURRENT_TIMESTAMP)
                   ON CONFLICT(customer_id) DO UPDATE SET
                   plan_code=excluded.plan_code, starts_at=excluded.starts_at,
                   expires_at=excluded.expires_at, status='ACTIVE', updated_at=CURRENT_TIMESTAMP""",
                (customer_id, plan, starts.isoformat(), expires.isoformat()),
            )
            self.db.execute("""INSERT INTO air_customer_subscription_history
                (assignment_id,customer_id,plan_code,starts_at,expires_at,status,assigned_by_admin_id,assigned_at)
                VALUES(?,?,?,?,?,'ACTIVE',?,?)""",
                (str(uuid4()), customer_id, plan, starts.isoformat(), expires.isoformat(), assigned_by_admin_id, assigned_at))
            registered = self.db.execute("SELECT MIN(created_at) FROM air_access_requests WHERE mobile_e164=?",
                                         (customer_id,)).fetchone()[0]
            if registered:
                self.db.execute("""INSERT INTO air_customer_lifecycle
                    (customer_id,first_registered_at,first_plan_availed_at) VALUES(?,?,?)
                    ON CONFLICT(customer_id) DO UPDATE SET
                    first_plan_availed_at=COALESCE(air_customer_lifecycle.first_plan_availed_at,excluded.first_plan_availed_at),
                    updated_at=CURRENT_TIMESTAMP""", (customer_id, registered, assigned_at))

    def get_subscription(self, customer_id: str):
        row = self.db.execute(
            """SELECT customer_id,plan_code,starts_at,expires_at,status
               FROM air_customer_subscriptions WHERE customer_id=?""",
            (customer_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result["status"] == "ACTIVE":
            from datetime import datetime, timezone
            try:
                starts = self._subscription_datetime(result["starts_at"])
                expires = self._subscription_datetime(result["expires_at"])
                now = datetime.now(timezone.utc)
                if starts > now:
                    result["status"] = "PENDING"
                elif expires <= now:
                    result["status"] = "EXPIRED"
            except (TypeError, ValueError):
                result["status"] = "EXPIRED"
        return result


    def list_marketing_customers(self, segment: str = "ALL", search: str = "", limit: int = 200):
        """Return one row per mobile identity, never one row per device."""
        segment = segment.upper()
        allowed = {"ALL", "NEVER_SUBSCRIBED", "EXPIRED", "ACTIVE", "CANCELLED", "INACTIVE", "PENDING_ACCESS", "OPTED_OUT", "NOT_GRANTED"}
        if segment not in allowed:
            raise ValueError("Unsupported customer segment")
        limit = max(1, min(int(limit), 10000))
        rows = self.db.execute("""
            SELECT r.mobile_e164 AS customer_id,
                   MIN(r.created_at) AS registered_at,
                   MAX(r.created_at) AS last_device_request_at,
                   COUNT(DISTINCT r.device_id) AS device_count,
                   CASE
                     WHEN SUM(CASE WHEN r.status='APPROVED' THEN 1 ELSE 0 END)>0 THEN 'APPROVED'
                     WHEN SUM(CASE WHEN r.status='PENDING' THEN 1 ELSE 0 END)>0 THEN 'PENDING'
                     WHEN SUM(CASE WHEN r.status='BLOCKED' THEN 1 ELSE 0 END)>0 THEN 'BLOCKED'
                     ELSE 'REJECTED'
                   END AS access_status,
                   l.first_approved_at,l.first_rejected_at,l.first_plan_availed_at
              FROM air_access_requests r LEFT JOIN air_customer_lifecycle l ON l.customer_id=r.mobile_e164
             GROUP BY r.mobile_e164,l.first_approved_at,l.first_rejected_at,l.first_plan_availed_at
             ORDER BY MAX(r.created_at) DESC
        """).fetchall()
        result = []
        needle = search.strip().lower()
        for row in rows:
            customer_id = row["customer_id"]
            subscription = self.get_subscription(customer_id)
            subscription_status = subscription["status"] if subscription else "NEVER_SUBSCRIBED"
            pref = self.db.execute(
                "SELECT promotional_consent,consent_updated_at FROM air_customer_marketing_preferences WHERE customer_id=?",
                (customer_id,),
            ).fetchone()
            consent = bool(pref and pref["promotional_consent"])
            item = {
                "customer_id": customer_id,
                "registered_at": row["registered_at"],
                "last_device_request_at": row["last_device_request_at"],
                "device_count": row["device_count"],
                "access_status": row["access_status"],
                "subscription_status": subscription_status,
                "plan_code": subscription["plan_code"] if subscription else None,
                "subscription_expires_at": subscription["expires_at"] if subscription else None,
                "first_registered_at": row["registered_at"],
                "first_approved_at": row["first_approved_at"],
                "first_rejected_at": row["first_rejected_at"],
                "first_plan_availed_at": row["first_plan_availed_at"],
                "subscription_starts_at": subscription["starts_at"] if subscription else None,
                "promotional_consent": consent,
                "marketing_status": "OPTED_IN" if consent else ("OPTED_OUT" if pref else "NOT_GRANTED"),
                "consent_updated_at": pref["consent_updated_at"] if pref else None,
            }
            if needle and needle not in customer_id.lower():
                continue
            if segment == "NEVER_SUBSCRIBED" and subscription_status != "NEVER_SUBSCRIBED":
                continue
            if segment == "EXPIRED" and subscription_status != "EXPIRED":
                continue
            if segment == "ACTIVE" and subscription_status != "ACTIVE":
                continue
            if segment == "CANCELLED" and subscription_status != "CANCELLED":
                continue
            if segment == "INACTIVE" and subscription_status not in {"EXPIRED", "CANCELLED"}:
                continue
            if segment == "PENDING_ACCESS" and item["access_status"] != "PENDING":
                continue
            if segment == "OPTED_OUT" and item["marketing_status"] != "OPTED_OUT":
                continue
            if segment == "NOT_GRANTED" and item["marketing_status"] != "NOT_GRANTED":
                continue
            result.append(item)
            if len(result) >= limit:
                break
        return result

    def get_marketing_consent(self, customer_id: str):
        row = self.db.execute(
            "SELECT promotional_consent,consent_updated_at FROM air_customer_marketing_preferences WHERE customer_id=?",
            (customer_id,),
        ).fetchone()
        return {
            "customer_id": customer_id,
            "promotional_consent": bool(row and row["promotional_consent"]),
            "marketing_status": "OPTED_IN" if row and row["promotional_consent"] else ("OPTED_OUT" if row else "NOT_GRANTED"),
            "consent_updated_at": row["consent_updated_at"] if row else None,
        }

    def set_marketing_consent(self, customer_id: str, enabled: bool):
        """Customer-controlled opt-in/out. Admin UI cannot grant consent on a customer's behalf."""
        if not customer_id:
            raise ValueError("Customer identity is required")
        with self.db:
            self.db.execute("""
                INSERT INTO air_customer_marketing_preferences
                    (customer_id,promotional_consent,consent_updated_at,updated_at)
                VALUES(?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT(customer_id) DO UPDATE SET
                    promotional_consent=excluded.promotional_consent,
                    consent_updated_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
            """, (customer_id, 1 if enabled else 0))
            self.db.execute("""
                INSERT INTO air_marketing_audit(event_id,actor_customer_id,action,target_id,details)
                VALUES(?,?,?,?,?)
            """, (str(uuid4()), customer_id, "CUSTOMER_MARKETING_CONSENT",
                  customer_id, "OPTED_IN" if enabled else "OPTED_OUT"))
        return {"customer_id": customer_id, "promotional_consent": bool(enabled)}

    def marketing_segment_counts(self):
        customers = self.list_marketing_customers("ALL", limit=500)
        counts = {
            "ALL": len(customers),
            "NEVER_SUBSCRIBED": 0,
            "EXPIRED": 0,
            "ACTIVE": 0,
            "CANCELLED": 0,
            "INACTIVE": 0,
            "PENDING": 0,
            "PENDING_ACCESS": 0,
            "OPTED_OUT": 0,
            "NOT_GRANTED": 0,
            "ELIGIBLE_FOR_PROMOTIONS": 0,
        }
        for customer in customers:
            status = customer["subscription_status"]
            if status in {"NEVER_SUBSCRIBED", "EXPIRED", "ACTIVE", "CANCELLED", "PENDING"}:
                counts[status] += 1
            if status in {"EXPIRED", "CANCELLED"}:
                counts["INACTIVE"] += 1
            if customer["access_status"] == "PENDING":
                counts["PENDING_ACCESS"] += 1
            if customer["marketing_status"] == "OPTED_OUT":
                counts["OPTED_OUT"] += 1
            elif customer["marketing_status"] == "NOT_GRANTED":
                counts["NOT_GRANTED"] += 1
            if customer["access_status"] == "APPROVED" and status in {"NEVER_SUBSCRIBED", "EXPIRED", "CANCELLED"} and customer["promotional_consent"]:
                counts["ELIGIBLE_FOR_PROMOTIONS"] += 1
        return counts

    def create_marketing_offer(self, name: str, offer_code: str, plan_code: str,
                               discount_percent: float, starts_at: str, expires_at: str,
                               terms: str, created_by: str):
        plan = plan_code.upper()
        if plan not in {"DAILY", "MONTHLY", "SIX_MONTHS", "YEARLY"}:
            raise ValueError("Unsupported AIR subscription plan")
        discount = float(discount_percent)
        if not 0 < discount <= 90:
            raise ValueError("Discount must be greater than 0 and no more than 90 percent")
        starts = self._subscription_datetime(starts_at)
        expires = self._subscription_datetime(expires_at)
        if expires <= starts:
            raise ValueError("Offer expiry must be later than its start date")
        normalized_code = re.sub(r"[^A-Z0-9_-]", "", offer_code.strip().upper())
        if len(normalized_code) < 4 or len(normalized_code) > 32:
            raise ValueError("Offer code must contain 4 to 32 letters, numbers, hyphens or underscores")
        if not name.strip() or len(name.strip()) > 100:
            raise ValueError("Offer name must contain 1 to 100 characters")
        offer_id = str(uuid4())
        with self.db:
            self.db.execute("""
                INSERT INTO air_marketing_offers
                    (offer_id,name,offer_code,plan_code,discount_percent,starts_at,expires_at,terms,created_by)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (offer_id, name.strip(), normalized_code, plan, discount,
                  starts.isoformat(), expires.isoformat(), terms.strip()[:1000], created_by))
            self.db.execute("""
                INSERT INTO air_marketing_audit(event_id,actor_customer_id,action,target_id,details)
                VALUES(?,?,?,?,?)
            """, (str(uuid4()), created_by, "MARKETING_OFFER_CREATED", offer_id, normalized_code))
        return self.get_marketing_offer(offer_id)

    def get_marketing_offer(self, offer_id: str):
        row = self.db.execute("SELECT * FROM air_marketing_offers WHERE offer_id=?", (offer_id,)).fetchone()
        return dict(row) if row else None

    def list_marketing_offers(self, status: str | None = None):
        if status and status.upper() not in {"DRAFT", "APPROVED", "REVOKED"}:
            raise ValueError("Unsupported offer status")
        if status:
            rows = self.db.execute(
                "SELECT * FROM air_marketing_offers WHERE status=? ORDER BY created_at DESC",
                (status.upper(),),
            ).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM air_marketing_offers ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def approve_marketing_offer(self, offer_id: str, approved_by: str):
        from datetime import datetime, timezone
        offer = self.get_marketing_offer(offer_id)
        if not offer or offer["status"] != "DRAFT":
            raise ValueError("Draft offer not found or already reviewed")
        if self._subscription_datetime(offer["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("Expired offers cannot be approved")
        with self.db:
            cursor = self.db.execute("""
                UPDATE air_marketing_offers SET status='APPROVED',approved_by=?,
                    approved_at=CURRENT_TIMESTAMP
                WHERE offer_id=? AND status='DRAFT'
            """, (approved_by, offer_id))
            if cursor.rowcount:
                self.db.execute("""
                    INSERT INTO air_marketing_audit(event_id,actor_customer_id,action,target_id,details)
                    VALUES(?,?,?,?,?)
                """, (str(uuid4()), approved_by, "MARKETING_OFFER_APPROVED", offer_id, "Super Admin approval"))
        if not cursor.rowcount:
            raise ValueError("Draft offer not found or already reviewed")
        return self.get_marketing_offer(offer_id)

    def revoke_marketing_offer(self, offer_id: str, actor: str):
        with self.db:
            cursor = self.db.execute(
                "UPDATE air_marketing_offers SET status='REVOKED' WHERE offer_id=? AND status='APPROVED'",
                (offer_id,),
            )
            if cursor.rowcount:
                self.db.execute("""
                    INSERT INTO air_marketing_audit(event_id,actor_customer_id,action,target_id,details)
                    VALUES(?,?,?,?,?)
                """, (str(uuid4()), actor, "MARKETING_OFFER_REVOKED", offer_id, "Offer revoked"))
        return bool(cursor.rowcount)

    def close(self):
        self.db.close()


access_store = AccessStore()
