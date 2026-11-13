"""PostgreSQL implementation of the AIR customer access and marketing store.

The schema is managed by Alembic revision 0002_customer_access_schema.
SQLite remains the default compatibility store until AIR_CUSTOMER_DATABASE_URL
(or AIR_CUSTOMER_DATABASE_URL_FILE) is explicitly configured.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
_PLANS = {"DAILY", "MONTHLY", "SIX_MONTHS", "YEARLY"}
_SEGMENTS = {"ALL", "NEVER_SUBSCRIBED", "EXPIRED", "ACTIVE", "CANCELLED",
             "INACTIVE", "PENDING_ACCESS", "OPTED_OUT", "NOT_GRANTED"}
_OFFER_STATUSES = {"DRAFT", "APPROVED", "REVOKED"}


class PostgresAccessStore:
    """SQLAlchemy-backed implementation matching the SQLite AccessStore API."""

    def __init__(self, database_url: str | None = None, engine: Engine | None = None):
        database_url = database_url or self._secret_setting("AIR_CUSTOMER_DATABASE_URL")
        if engine is None:
            if not database_url or not database_url.startswith(
                ("postgresql://", "postgresql+psycopg://")
            ):
                raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must be configured with PostgreSQL")
            engine = create_engine(database_url, pool_pre_ping=True, future=True)
        self.engine = engine

    @staticmethod
    def _secret_setting(name: str) -> str:
        file_name = os.getenv(name + "_FILE")
        return Path(file_name).read_text(encoding="utf-8").strip() if file_name else os.getenv(name, "").strip()

    @staticmethod
    def validate_mobile(mobile_e164: str) -> str:
        value = mobile_e164.strip()
        if not _E164.fullmatch(value):
            raise ValueError("Enter a valid international number in E.164 format, for example +14155550123")
        return value

    @staticmethod
    def _subscription_datetime(value: str):
        from datetime import datetime, timezone
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Subscription timestamps must be non-empty ISO-8601 strings")
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _dict(row):
        return dict(row) if row is not None else None

    def request_access(self, mobile_e164: str, device_id: str):
        mobile = self.validate_mobile(mobile_e164)
        device = device_id.strip()
        if not device or len(device) > 128:
            raise ValueError("A valid device identifier is required")
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO air_access_requests
                (request_id,mobile_e164,device_id,status)
                VALUES(:id,:mobile,:device,'PENDING')
                ON CONFLICT(mobile_e164,device_id) DO NOTHING"""),
                {"id": str(uuid4()), "mobile": mobile, "device": device})
            row = conn.execute(text("""SELECT request_id,mobile_e164,device_id,status,
                created_at,reviewed_at,reviewer_note FROM air_access_requests
                WHERE mobile_e164=:mobile AND device_id=:device"""),
                {"mobile": mobile, "device": device}).mappings().one()
        return dict(row)

    def get_request(self, mobile_e164: str, device_id: str):
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT request_id,mobile_e164,device_id,status,
                created_at,reviewed_at,reviewer_note FROM air_access_requests
                WHERE mobile_e164=:mobile AND device_id=:device"""),
                {"mobile": mobile_e164.strip(), "device": device_id.strip()}).mappings().first()
        return self._dict(row)

    def mobile_for_request_id(self, request_id: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT mobile_e164 FROM air_access_requests WHERE request_id=:id"),
                                {"id": request_id}).scalar_one_or_none()

    def list_requests(self, status: str | None = None):
        statement = """SELECT request_id,mobile_e164,device_id,status,created_at,reviewed_at,reviewer_note
            FROM air_access_requests"""
        params = {}
        if status:
            statement += " WHERE status=:status"
            params["status"] = status.upper()
        statement += " ORDER BY created_at DESC,request_id"
        with self.engine.connect() as conn:
            rows = conn.execute(text(statement), params).mappings().all()
        return [dict(row) for row in rows]

    def review(self, request_id: str, status: str, note: str = "") -> bool:
        status = status.upper()
        if status not in {"APPROVED", "REJECTED", "BLOCKED"}:
            raise ValueError("Status must be APPROVED, REJECTED or BLOCKED")
        with self.engine.begin() as conn:
            result = conn.execute(text("""UPDATE air_access_requests
                SET status=:status,reviewed_at=CURRENT_TIMESTAMP,reviewer_note=:note
                WHERE request_id=:id"""),
                {"status": status, "note": note[:500], "id": request_id})
            if result.rowcount and status != "APPROVED":
                conn.execute(text("UPDATE air_device_sessions SET active=false WHERE request_id=:id"),
                             {"id": request_id})
        return result.rowcount > 0

    def create_session(self, request_id: str) -> str:
        session_id = str(uuid4())
        with self.engine.begin() as conn:
            row = conn.execute(text("""SELECT status FROM air_access_requests
                WHERE request_id=:id FOR SHARE"""), {"id": request_id}).first()
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

    def assign_subscription(self, customer_id: str, plan_code: str, starts_at: str, expires_at: str):
        plan = plan_code.upper()
        if plan not in _PLANS:
            raise ValueError("Unsupported AIR subscription plan")
        starts = self._subscription_datetime(starts_at)
        expires = self._subscription_datetime(expires_at)
        if expires <= starts:
            raise ValueError("Subscription expiry must be later than its start date")
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO air_customer_subscriptions
                (customer_id,plan_code,starts_at,expires_at,status,updated_at)
                VALUES(:customer,:plan,:starts,:expires,'ACTIVE',CURRENT_TIMESTAMP)
                ON CONFLICT(customer_id) DO UPDATE SET plan_code=EXCLUDED.plan_code,
                starts_at=EXCLUDED.starts_at,expires_at=EXCLUDED.expires_at,
                status='ACTIVE',updated_at=CURRENT_TIMESTAMP"""),
                {"customer": customer_id, "plan": plan, "starts": starts.isoformat(),
                 "expires": expires.isoformat()})

    def get_subscription(self, customer_id: str):
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT customer_id,plan_code,starts_at,expires_at,status
                FROM air_customer_subscriptions WHERE customer_id=:customer"""),
                {"customer": customer_id}).mappings().first()
        result = self._dict(row)
        if result and result["status"] == "ACTIVE":
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

    def _subscription_and_preference(self, conn, customer_id: str):
        sub = conn.execute(text("""SELECT customer_id,plan_code,starts_at,expires_at,status
            FROM air_customer_subscriptions WHERE customer_id=:customer"""),
            {"customer": customer_id}).mappings().first()
        pref = conn.execute(text("""SELECT promotional_consent,consent_updated_at
            FROM air_customer_marketing_preferences WHERE customer_id=:customer"""),
            {"customer": customer_id}).mappings().first()
        subscription = dict(sub) if sub else None
        if subscription and subscription["status"] == "ACTIVE":
            from datetime import datetime, timezone
            try:
                now = datetime.now(timezone.utc)
                if self._subscription_datetime(subscription["starts_at"]) > now:
                    subscription["status"] = "PENDING"
                elif self._subscription_datetime(subscription["expires_at"]) <= now:
                    subscription["status"] = "EXPIRED"
            except (TypeError, ValueError):
                subscription["status"] = "EXPIRED"
        return subscription, dict(pref) if pref else None

    def list_marketing_customers(self, segment: str = "ALL", search: str = "", limit: int = 200):
        segment = segment.upper()
        if segment not in _SEGMENTS:
            raise ValueError("Unsupported customer segment")
        limit = max(1, min(int(limit), 500))
        with self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT r.mobile_e164 AS customer_id,
                MIN(r.created_at) AS registered_at,MAX(r.created_at) AS last_device_request_at,
                COUNT(DISTINCT r.device_id) AS device_count,
                CASE WHEN BOOL_OR(r.status='APPROVED') THEN 'APPROVED'
                     WHEN BOOL_OR(r.status='PENDING') THEN 'PENDING'
                     WHEN BOOL_OR(r.status='BLOCKED') THEN 'BLOCKED' ELSE 'REJECTED' END AS access_status
                FROM air_access_requests r GROUP BY r.mobile_e164
                ORDER BY MAX(r.created_at) DESC""")).mappings().all()
            result = []
            needle = search.strip().lower()
            for row in rows:
                customer_id = row["customer_id"]
                if needle and needle not in customer_id.lower():
                    continue
                subscription, pref = self._subscription_and_preference(conn, customer_id)
                sub_status = subscription["status"] if subscription else "NEVER_SUBSCRIBED"
                consent = bool(pref and pref["promotional_consent"])
                marketing_status = "OPTED_IN" if consent else ("OPTED_OUT" if pref else "NOT_GRANTED")
                item = {
                    "customer_id": customer_id, "registered_at": row["registered_at"],
                    "last_device_request_at": row["last_device_request_at"],
                    "device_count": row["device_count"], "access_status": row["access_status"],
                    "subscription_status": sub_status,
                    "plan_code": subscription["plan_code"] if subscription else None,
                    "subscription_expires_at": subscription["expires_at"] if subscription else None,
                    "promotional_consent": consent, "marketing_status": marketing_status,
                    "consent_updated_at": pref["consent_updated_at"] if pref else None,
                }
                if segment == "NEVER_SUBSCRIBED" and sub_status != "NEVER_SUBSCRIBED": continue
                if segment == "EXPIRED" and sub_status != "EXPIRED": continue
                if segment == "ACTIVE" and sub_status != "ACTIVE": continue
                if segment == "CANCELLED" and sub_status != "CANCELLED": continue
                if segment == "INACTIVE" and sub_status not in {"EXPIRED", "CANCELLED"}: continue
                if segment == "PENDING_ACCESS" and item["access_status"] != "PENDING": continue
                if segment == "OPTED_OUT" and marketing_status != "OPTED_OUT": continue
                if segment == "NOT_GRANTED" and marketing_status != "NOT_GRANTED": continue
                result.append(item)
                if len(result) >= limit: break
        return result

    def get_marketing_consent(self, customer_id: str):
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT promotional_consent,consent_updated_at
                FROM air_customer_marketing_preferences WHERE customer_id=:customer"""),
                {"customer": customer_id}).mappings().first()
        consent = bool(row and row["promotional_consent"])
        return {"customer_id": customer_id, "promotional_consent": consent,
                "marketing_status": "OPTED_IN" if consent else ("OPTED_OUT" if row else "NOT_GRANTED"),
                "consent_updated_at": row["consent_updated_at"] if row else None}

    def set_marketing_consent(self, customer_id: str, enabled: bool):
        if not customer_id:
            raise ValueError("Customer identity is required")
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO air_customer_marketing_preferences
                (customer_id,promotional_consent,consent_updated_at,updated_at)
                VALUES(:customer,:enabled,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT(customer_id) DO UPDATE SET promotional_consent=EXCLUDED.promotional_consent,
                consent_updated_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP"""),
                {"customer": customer_id, "enabled": bool(enabled)})
            conn.execute(text("""INSERT INTO air_marketing_audit
                (event_id,actor_customer_id,action,target_id,details)
                VALUES(:event,:actor,'CUSTOMER_MARKETING_CONSENT',:target,:details)"""),
                {"event": str(uuid4()), "actor": customer_id, "target": customer_id,
                 "details": "OPTED_IN" if enabled else "OPTED_OUT"})
        return {"customer_id": customer_id, "promotional_consent": bool(enabled)}

    def marketing_segment_counts(self):
        customers = self.list_marketing_customers("ALL", limit=500)
        counts = {"ALL": len(customers), "NEVER_SUBSCRIBED": 0, "EXPIRED": 0,
                  "ACTIVE": 0, "CANCELLED": 0, "INACTIVE": 0, "PENDING": 0,
                  "PENDING_ACCESS": 0, "OPTED_OUT": 0, "NOT_GRANTED": 0,
                  "ELIGIBLE_FOR_PROMOTIONS": 0}
        for customer in customers:
            status = customer["subscription_status"]
            if status in {"NEVER_SUBSCRIBED", "EXPIRED", "ACTIVE", "CANCELLED", "PENDING"}:
                counts[status] += 1
            if status in {"EXPIRED", "CANCELLED"}: counts["INACTIVE"] += 1
            if customer["access_status"] == "PENDING": counts["PENDING_ACCESS"] += 1
            if customer["marketing_status"] == "OPTED_OUT": counts["OPTED_OUT"] += 1
            elif customer["marketing_status"] == "NOT_GRANTED": counts["NOT_GRANTED"] += 1
            if (customer["access_status"] == "APPROVED"
                    and status in {"NEVER_SUBSCRIBED", "EXPIRED", "CANCELLED"}
                    and customer["promotional_consent"]):
                counts["ELIGIBLE_FOR_PROMOTIONS"] += 1
        return counts

    def create_marketing_offer(self, name: str, offer_code: str, plan_code: str,
                               discount_percent: float, starts_at: str, expires_at: str,
                               terms: str, created_by: str):
        plan = plan_code.upper()
        if plan not in _PLANS: raise ValueError("Unsupported AIR subscription plan")
        discount = float(discount_percent)
        if not 0 < discount <= 90:
            raise ValueError("Discount must be greater than 0 and no more than 90 percent")
        starts = self._subscription_datetime(starts_at)
        expires = self._subscription_datetime(expires_at)
        if expires <= starts: raise ValueError("Offer expiry must be later than its start date")
        code = re.sub(r"[^A-Z0-9_-]", "", offer_code.strip().upper())
        if len(code) < 4 or len(code) > 32:
            raise ValueError("Offer code must contain 4 to 32 letters, numbers, hyphens or underscores")
        if not name.strip() or len(name.strip()) > 100:
            raise ValueError("Offer name must contain 1 to 100 characters")
        offer_id = str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO air_marketing_offers
                (offer_id,name,offer_code,plan_code,discount_percent,starts_at,expires_at,terms,created_by)
                VALUES(:id,:name,:code,:plan,:discount,:starts,:expires,:terms,:actor)"""),
                {"id": offer_id, "name": name.strip(), "code": code, "plan": plan,
                 "discount": discount, "starts": starts.isoformat(), "expires": expires.isoformat(),
                 "terms": terms.strip()[:1000], "actor": created_by})
            self._audit(conn, created_by, "MARKETING_OFFER_CREATED", offer_id, code)
        return self.get_marketing_offer(offer_id)

    def get_marketing_offer(self, offer_id: str):
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM air_marketing_offers WHERE offer_id=:id"),
                               {"id": offer_id}).mappings().first()
        return self._dict(row)

    def list_marketing_offers(self, status: str | None = None):
        if status and status.upper() not in _OFFER_STATUSES:
            raise ValueError("Unsupported offer status")
        query = "SELECT * FROM air_marketing_offers"
        params = {}
        if status:
            query += " WHERE status=:status"
            params["status"] = status.upper()
        query += " ORDER BY created_at DESC,offer_id"
        with self.engine.connect() as conn:
            rows = conn.execute(text(query), params).mappings().all()
        return [dict(row) for row in rows]

    def approve_marketing_offer(self, offer_id: str, approved_by: str):
        from datetime import datetime, timezone
        with self.engine.begin() as conn:
            offer = conn.execute(text("""SELECT status,expires_at FROM air_marketing_offers
                WHERE offer_id=:id FOR UPDATE"""), {"id": offer_id}).first()
            if not offer or offer.status != "DRAFT":
                raise ValueError("Draft offer not found or already reviewed")
            if self._subscription_datetime(offer.expires_at) <= datetime.now(timezone.utc):
                raise ValueError("Expired offers cannot be approved")
            result = conn.execute(text("""UPDATE air_marketing_offers
                SET status='APPROVED',approved_by=:actor,approved_at=CURRENT_TIMESTAMP
                WHERE offer_id=:id AND status='DRAFT'"""),
                {"actor": approved_by, "id": offer_id})
            if not result.rowcount:
                raise ValueError("Draft offer not found or already reviewed")
            self._audit(conn, approved_by, "MARKETING_OFFER_APPROVED", offer_id, "Super Admin approval")
        return self.get_marketing_offer(offer_id)

    def revoke_marketing_offer(self, offer_id: str, actor: str):
        with self.engine.begin() as conn:
            result = conn.execute(text("""UPDATE air_marketing_offers SET status='REVOKED'
                WHERE offer_id=:id AND status='APPROVED'"""), {"id": offer_id})
            if result.rowcount:
                self._audit(conn, actor, "MARKETING_OFFER_REVOKED", offer_id, "Offer revoked")
        return bool(result.rowcount)

    @staticmethod
    def _audit(conn, actor: str, action: str, target: str, details: str = ""):
        conn.execute(text("""INSERT INTO air_marketing_audit
            (event_id,actor_customer_id,action,target_id,details)
            VALUES(:event,:actor,:action,:target,:details)"""),
            {"event": str(uuid4()), "actor": actor, "action": action,
             "target": target, "details": details[:1000]})

    def close(self):
        self.engine.dispose()
