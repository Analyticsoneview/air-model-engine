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
            if cursor.rowcount:
                if status != "APPROVED":
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

    @staticmethod
    def _subscription_datetime(value: str):
        from datetime import datetime, timezone
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Subscription timestamps must be non-empty ISO-8601 strings")
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def assign_subscription(self, customer_id: str, plan_code: str, starts_at: str, expires_at: str):
        plan = plan_code.upper()
        if plan not in {"DAILY", "MONTHLY", "SIX_MONTHS", "YEARLY"}:
            raise ValueError("Unsupported AIR subscription plan")
        starts = self._subscription_datetime(starts_at)
        expires = self._subscription_datetime(expires_at)
        if expires <= starts:
            raise ValueError("Subscription expiry must be later than its start date")
        with self.db:
            self.db.execute(
                """INSERT INTO air_customer_subscriptions
                   (customer_id,plan_code,starts_at,expires_at,status,updated_at)
                   VALUES(?,?,?,?, 'ACTIVE', CURRENT_TIMESTAMP)
                   ON CONFLICT(customer_id) DO UPDATE SET
                   plan_code=excluded.plan_code, starts_at=excluded.starts_at,
                   expires_at=excluded.expires_at, status='ACTIVE', updated_at=CURRENT_TIMESTAMP""",
                (customer_id, plan, starts.isoformat(), expires.isoformat()),
            )

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
        allowed = {"ALL", "NEVER_SUBSCRIBED", "EXPIRED", "ACTIVE", "PENDING_ACCESS", "OPTED_OUT"}
        if segment not in allowed:
            raise ValueError("Unsupported customer segment")
        limit = max(1, min(int(limit), 500))
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
                   END AS access_status
              FROM air_access_requests r
             GROUP BY r.mobile_e164
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
            if segment == "PENDING_ACCESS" and item["access_status"] != "PENDING":
                continue
            if segment == "OPTED_OUT" and item["marketing_status"] != "OPTED_OUT":
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
            "PENDING_ACCESS": 0,
            "OPTED_OUT": 0,
            "NOT_GRANTED": 0,
            "ELIGIBLE_FOR_PROMOTIONS": 0,
        }
        for customer in customers:
            status = customer["subscription_status"]
            if status in counts:
                counts[status] += 1
            if customer["access_status"] == "APPROVED" and status != "ACTIVE" and customer["promotional_consent"]:
                counts["ELIGIBLE_FOR_PROMOTIONS"] += 1
            if customer["marketing_status"] == "OPTED_OUT":
                counts["OPTED_OUT"] += 1
            elif customer["marketing_status"] == "NOT_GRANTED":
                counts["NOT_GRANTED"] += 1
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
