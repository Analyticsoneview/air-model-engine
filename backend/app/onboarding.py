"""Tenant-scoped customer onboarding, consent and trial workflow.

Consent records and lifecycle events are append-only. Trial activation never
collects money; paid activation and renewal require an explicit admin action.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text


REQUIRED_CONSENTS = frozenset({"TERMS", "PRIVACY", "DATA_PROCESSING"})
ALLOWED_CONSENTS = REQUIRED_CONSENTS | {"MARKETING"}
STATUSES = frozenset({"PENDING", "TRIAL", "ACTIVE", "CANCELLED", "EXPIRED", "REJECTED"})


class OnboardingConflict(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


class OnboardingStore:
    def __init__(self, database_url=None, sqlite_path=None):
        url = database_url if database_url is not None else os.getenv("AIR_CUSTOMER_DATABASE_URL", "").strip()
        self.sqlite_path = sqlite_path or os.getenv("AIR_ONBOARDING_DB_PATH", "data/customer_onboarding.sqlite3")
        if url.startswith(("postgresql://", "postgresql+psycopg://")):
            self.engine = create_engine(url, pool_pre_ping=True, future=True)
            from app.tenant_context import install_tenant_context
            install_tenant_context(self.engine)
            with self.engine.connect() as conn:
                if not conn.execute(text("SELECT to_regclass('public.air_customer_onboarding')")).scalar():
                    raise RuntimeError("Customer onboarding migration 0026 must be applied before use")
        elif url:
            raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must use PostgreSQL")
        else:
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine("sqlite:///" + str(Path(self.sqlite_path).resolve()), future=True,
                                        connect_args={"timeout": 30})
            self._sqlite_schema()

    def _sqlite_schema(self):
        with self.engine.begin() as c:
            c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_customer_onboarding(
                onboarding_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,customer_id TEXT NOT NULL,
                product_code TEXT NOT NULL,plan_code TEXT NOT NULL,status TEXT NOT NULL,
                trial_started_at TEXT,trial_ends_at TEXT,contract_id TEXT,cancel_reason TEXT,
                idempotency_key TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                UNIQUE(tenant_id,customer_id,product_code),UNIQUE(tenant_id,idempotency_key))""")
            c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_customer_consents(
                consent_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,customer_id TEXT NOT NULL,
                consent_type TEXT NOT NULL,document_version TEXT NOT NULL,accepted INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL,accepted_at TEXT NOT NULL,UNIQUE(tenant_id,idempotency_key))""")
            c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_customer_onboarding_events(
                event_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,onboarding_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,event_type TEXT NOT NULL,from_status TEXT,to_status TEXT,
                idempotency_key TEXT NOT NULL,details TEXT NOT NULL,occurred_at TEXT NOT NULL,
                UNIQUE(tenant_id,idempotency_key))""")

    def _scope(self, tenant_id, customer_id=None, admin=False):
        from contextlib import nullcontext
        if self.engine.dialect.name == "postgresql":
            from app.tenant_context import tenant_scope
            return tenant_scope(tenant_id=tenant_id, customer_id=customer_id, is_admin=admin)
        return nullcontext()

    def record_consents(self, tenant_id, customer_id, consents, idempotency_prefix):
        if not tenant_id or not customer_id or not isinstance(consents, list) or not consents or len(consents) > 4:
            raise ValueError("Tenant, customer and 1-4 explicit consent records are required")
        seen = set()
        normalized = []
        for item in consents:
            if not isinstance(item, dict):
                raise ValueError("Each consent must be an object")
            kind = str(item.get("consent_type", "")).strip().upper()
            version = str(item.get("document_version", "")).strip()
            accepted = item.get("accepted")
            if kind not in ALLOWED_CONSENTS or kind in seen or not version or len(version) > 64 or not isinstance(accepted, bool):
                raise ValueError("Consent type, unique version and boolean decision are required")
            if kind in REQUIRED_CONSENTS and not accepted:
                raise ValueError(f"{kind} consent is required to continue")
            seen.add(kind)
            normalized.append((kind, version, accepted))
        if not REQUIRED_CONSENTS.issubset(seen):
            raise ValueError("TERMS, PRIVACY and DATA_PROCESSING consent decisions are required")
        with self._scope(tenant_id, customer_id), self.engine.begin() as conn:
            result = []
            for kind, version, accepted in normalized:
                key = f"{idempotency_prefix}:{kind}"
                old = conn.execute(text("SELECT consent_id,document_version,accepted FROM air_customer_consents WHERE tenant_id=:t AND idempotency_key=:k"),
                                   {"t": tenant_id, "k": key}).first()
                if old:
                    if old[1] != version or bool(old[2]) != accepted:
                        raise OnboardingConflict("Consent idempotency key was reused with different content")
                    result.append({"consent_id": old[0], "consent_type": kind, "document_version": version, "accepted": accepted})
                    continue
                consent_id = str(uuid4())
                conn.execute(text("""INSERT INTO air_customer_consents
                    (consent_id,tenant_id,customer_id,consent_type,document_version,accepted,idempotency_key,accepted_at)
                    VALUES(:id,:t,:c,:kind,:version,:accepted,:key,:now)"""),
                    {"id": consent_id, "t": tenant_id, "c": customer_id, "kind": kind, "version": version,
                     "accepted": accepted, "key": key, "now": _now()})
                result.append({"consent_id": consent_id, "consent_type": kind, "document_version": version, "accepted": accepted})
            return result

    def consents(self, tenant_id, customer_id):
        with self._scope(tenant_id, customer_id), self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT consent_id,consent_type,document_version,accepted,accepted_at
                FROM air_customer_consents WHERE tenant_id=:t AND customer_id=:c ORDER BY accepted_at,consent_id"""),
                {"t": tenant_id, "c": customer_id}).mappings().all()
            return [dict(r) for r in rows]

    def get(self, tenant_id, customer_id):
        with self._scope(tenant_id, customer_id), self.engine.connect() as conn:
            row = conn.execute(text("""SELECT * FROM air_customer_onboarding
                WHERE tenant_id=:t AND customer_id=:c ORDER BY created_at DESC LIMIT 1"""),
                {"t": tenant_id, "c": customer_id}).mappings().first()
            return dict(row) if row else None

    def _event(self, conn, tenant, onboarding_id, actor, kind, old, new, key, details):
        conn.execute(text("""INSERT INTO air_customer_onboarding_events
            (event_id,tenant_id,onboarding_id,actor_id,event_type,from_status,to_status,idempotency_key,details,occurred_at)
            VALUES(:id,:t,:o,:actor,:kind,:old,:new,:key,:details,:now)"""),
            {"id": str(uuid4()), "t": tenant, "o": onboarding_id, "actor": actor, "kind": kind,
             "old": old, "new": new, "key": key, "details": json.dumps(details, sort_keys=True), "now": _now()})

    def create(self, tenant_id, customer_id, product_code, plan_code, idempotency_key, actor_id):
        if not all(str(x or "").strip() for x in (tenant_id, customer_id, product_code, plan_code, idempotency_key)):
            raise ValueError("Tenant, customer, product, plan and idempotency key are required")
        if len(idempotency_key) > 200:
            raise ValueError("Idempotency key is too long")
        with self._scope(tenant_id, customer_id), self.engine.begin() as conn:
            prior = conn.execute(text("SELECT onboarding_id,product_code,plan_code FROM air_customer_onboarding WHERE tenant_id=:t AND idempotency_key=:k"),
                                 {"t": tenant_id, "k": idempotency_key}).first()
            if prior:
                if prior[1] != product_code or prior[2] != plan_code:
                    raise OnboardingConflict("Onboarding idempotency key was reused with different content")
                return dict(conn.execute(text("SELECT * FROM air_customer_onboarding WHERE onboarding_id=:id"),
                                         {"id": prior[0]}).mappings().one())
            existing = conn.execute(text("""SELECT * FROM air_customer_onboarding
                WHERE tenant_id=:t AND customer_id=:c AND product_code=:p"""),
                {"t": tenant_id, "c": customer_id, "p": product_code}).mappings().first()
            if existing and existing["status"] not in ("CANCELLED", "EXPIRED", "REJECTED"):
                raise OnboardingConflict("An active onboarding record already exists")
            now = _now()
            item_id = str(uuid4())
            conn.execute(text("""INSERT INTO air_customer_onboarding
                (onboarding_id,tenant_id,customer_id,product_code,plan_code,status,idempotency_key,created_at,updated_at)
                VALUES(:id,:t,:c,:p,:plan,'PENDING',:key,:now,:now)"""),
                {"id": item_id, "t": tenant_id, "c": customer_id, "p": product_code, "plan": plan_code,
                 "key": idempotency_key, "now": now})
            self._event(conn, tenant_id, item_id, actor_id, "ONBOARDING_CREATED", None, "PENDING", idempotency_key, {})
            return dict(conn.execute(text("SELECT * FROM air_customer_onboarding WHERE onboarding_id=:id"),
                                     {"id": item_id}).mappings().one())

    def transition(self, tenant_id, customer_id, onboarding_id, target, actor_id, idempotency_key,
                   details=None, trial_days=None):
        target = str(target).upper()
        allowed = {"PENDING": {"TRIAL", "CANCELLED", "REJECTED"},
                   "TRIAL": {"ACTIVE", "CANCELLED", "EXPIRED"},
                   "ACTIVE": {"CANCELLED", "EXPIRED"},
                   "CANCELLED": set(), "EXPIRED": set(), "REJECTED": set()}
        if target not in STATUSES or not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("Valid target state and idempotency key are required")
        with self._scope(tenant_id, customer_id), self.engine.begin() as conn:
            suffix = " FOR UPDATE" if self.engine.dialect.name == "postgresql" else ""
            row = conn.execute(text("SELECT * FROM air_customer_onboarding WHERE tenant_id=:t AND customer_id=:c AND onboarding_id=:id" + suffix),
                               {"t": tenant_id, "c": customer_id, "id": onboarding_id}).mappings().first()
            if not row:
                raise KeyError("Onboarding record not found")
            prior = conn.execute(text("SELECT 1 FROM air_customer_onboarding_events WHERE tenant_id=:t AND idempotency_key=:k"),
                                 {"t": tenant_id, "k": idempotency_key}).first()
            if prior:
                return dict(row)
            if target not in allowed[row["status"]]:
                raise OnboardingConflict(f"Illegal onboarding transition {row['status']} -> {target}")
            now = _now()
            started = row["trial_started_at"]
            ends = row["trial_ends_at"]
            if target == "TRIAL":
                days = int(trial_days or 14)
                if days < 1 or days > 30:
                    raise ValueError("Trial duration must be between 1 and 30 days")
                started, ends = now, now + timedelta(days=days)
            conn.execute(text("""UPDATE air_customer_onboarding SET status=:status,trial_started_at=:started,
                trial_ends_at=:ends,cancel_reason=:reason,updated_at=:now,version=version+1
                WHERE tenant_id=:t AND customer_id=:c AND onboarding_id=:id"""),
                {"status": target, "started": started, "ends": ends,
                 "reason": (details or {}).get("reason") if target == "CANCELLED" else row["cancel_reason"],
                 "now": now, "t": tenant_id, "c": customer_id, "id": onboarding_id})
            self._event(conn, tenant_id, onboarding_id, actor_id, target, row["status"], target,
                        idempotency_key, details or {})
            return dict(conn.execute(text("SELECT * FROM air_customer_onboarding WHERE onboarding_id=:id"),
                                     {"id": onboarding_id}).mappings().one())

    def events(self, tenant_id, customer_id, onboarding_id):
        with self._scope(tenant_id, customer_id), self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT event_id,actor_id,event_type,from_status,to_status,details,occurred_at
                FROM air_customer_onboarding_events WHERE tenant_id=:t AND onboarding_id=:id
                ORDER BY occurred_at,event_id"""), {"t": tenant_id, "id": onboarding_id}).mappings().all()
            return [dict(r) for r in rows]
