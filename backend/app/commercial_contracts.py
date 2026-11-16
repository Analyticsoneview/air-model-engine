"""Durable annual commercial contract ledger (Gate 17F-2).

PostgreSQL is the production store; SQLite is the self-hosted/local fallback.
Lifecycle events are append-only and idempotent. This module does not charge
customers or activate payment collection.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

STATES = frozenset({"DRAFT", "TRIAL", "ACTIVE", "GRACE", "PAST_DUE", "CANCELLED", "EXPIRED", "SUSPENDED"})
TRANSITIONS = {
    "DRAFT": {"TRIAL", "ACTIVE", "CANCELLED"},
    "TRIAL": {"ACTIVE", "CANCELLED", "EXPIRED", "SUSPENDED"},
    "ACTIVE": {"GRACE", "PAST_DUE", "CANCELLED", "EXPIRED", "SUSPENDED"},
    "GRACE": {"ACTIVE", "PAST_DUE", "CANCELLED", "EXPIRED", "SUSPENDED"},
    "PAST_DUE": {"ACTIVE", "GRACE", "CANCELLED", "EXPIRED", "SUSPENDED"},
    "SUSPENDED": {"ACTIVE", "CANCELLED", "EXPIRED"},
    "CANCELLED": set(), "EXPIRED": set(),
}

def annual_period(start: date) -> date:
    """Return the exclusive end date one calendar year later (leap-safe)."""
    try:
        return start.replace(year=start.year + 1)
    except ValueError:
        return start.replace(year=start.year + 1, month=2, day=28)

class ContractConflict(ValueError):
    pass

class CommercialContractStore:
    def __init__(self, database_url: str | None = None, sqlite_path: str | None = None):
        self.database_url = database_url or os.getenv("AIR_CUSTOMER_DATABASE_URL", "")
        self.sqlite_path = sqlite_path or os.getenv("AIR_COMMERCIAL_DB_PATH", "data/commercial_contracts.sqlite3")
        self.engine = None
        if self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            self.engine = create_engine(self.database_url, pool_pre_ping=True, future=True)
            self._postgres_schema()
        elif self.database_url:
            raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must use PostgreSQL")
        else:
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_schema()

    def _sqlite(self):
        db = sqlite3.connect(self.sqlite_path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _sqlite_schema(self):
        with self._sqlite() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS air_commercial_contracts(
              contract_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL,
              product_code TEXT NOT NULL, plan_code TEXT NOT NULL, billing_period TEXT NOT NULL CHECK(billing_period='ANNUAL'),
              currency TEXT, amount_minor INTEGER CHECK(amount_minor IS NULL OR amount_minor>=0),
              start_date TEXT NOT NULL, end_date TEXT NOT NULL, grace_end_date TEXT,
              status TEXT NOT NULL CHECK(status IN ('DRAFT','TRIAL','ACTIVE','GRACE','PAST_DUE','CANCELLED','EXPIRED','SUSPENDED')),
              auto_renew INTEGER NOT NULL DEFAULT 0 CHECK(auto_renew IN (0,1)),
              provider TEXT, provider_customer_ref TEXT, provider_contract_ref TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS ix_air_contract_tenant_status ON air_commercial_contracts(tenant_id,status,end_date);
            CREATE TABLE IF NOT EXISTS air_commercial_contract_events(
              event_id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES air_commercial_contracts(contract_id),
              tenant_id TEXT NOT NULL, actor_id TEXT NOT NULL, event_type TEXT NOT NULL,
              from_status TEXT, to_status TEXT, idempotency_key TEXT NOT NULL, payload TEXT NOT NULL,
              occurred_at TEXT NOT NULL, UNIQUE(tenant_id,idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS ix_air_contract_events_history ON air_commercial_contract_events(tenant_id,contract_id,occurred_at);
            """)

    def _postgres_schema(self):
        # Alembic owns production schema. Fail early when the required migration is absent.
        with self.engine.connect() as conn:
            exists = conn.execute(text("SELECT to_regclass('public.air_commercial_contracts')")).scalar()
            if not exists:
                raise RuntimeError("Commercial contract migration 0022 must be applied before starting this store")

    def create_contract(self, *, tenant_id: str, customer_id: str, product_code: str, plan_code: str,
                        start_date: date, currency: str | None = None, amount_minor: int | None = None,
                        grace_days: int = 0, auto_renew: bool = False, actor_id: str | None = None,
                        idempotency_key: str):
        tenant, customer = str(tenant_id).strip(), str(customer_id).strip()
        if not tenant or not customer or not product_code or not plan_code:
            raise ValueError("tenant, customer, product and plan are required")
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("A bounded idempotency key is required")
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise ValueError("currency must be a three-letter ISO code")
        if amount_minor is not None and int(amount_minor) < 0:
            raise ValueError("amount_minor cannot be negative")
        if not 0 <= int(grace_days) <= 90:
            raise ValueError("grace_days must be between 0 and 90")
        end = annual_period(start_date)
        grace_end = date.fromordinal(end.toordinal() + int(grace_days)) if grace_days else None
        now = datetime.now(timezone.utc).isoformat()
        contract_id = str(uuid4())
        actor = actor_id or customer
        values = dict(contract_id=contract_id, tenant_id=tenant, customer_id=customer, product_code=product_code,
                      plan_code=plan_code, billing_period="ANNUAL", currency=currency.upper() if currency else None,
                      amount_minor=amount_minor, start_date=start_date.isoformat(), end_date=end.isoformat(),
                      grace_end_date=grace_end.isoformat() if grace_end else None, status="DRAFT",
                      auto_renew=bool(auto_renew), created_at=now, updated_at=now)
        if self.engine:
            with self.engine.begin() as conn:
                old = conn.execute(text("SELECT contract_id FROM air_commercial_contract_events WHERE tenant_id=:tenant AND idempotency_key=:key"),
                                   {"tenant": tenant, "key": idempotency_key}).scalar()
                if old: return self.get_contract(tenant, old)
                conn.execute(text("""INSERT INTO air_commercial_contracts
                  (contract_id,tenant_id,customer_id,product_code,plan_code,billing_period,currency,amount_minor,start_date,end_date,grace_end_date,status,auto_renew,created_at,updated_at)
                  VALUES (:contract_id,:tenant_id,:customer_id,:product_code,:plan_code,:billing_period,:currency,:amount_minor,:start_date,:end_date,:grace_end_date,:status,:auto_renew,:created_at,:updated_at)"""), values)
                self._event(conn, values, actor, "CONTRACT_CREATED", None, "DRAFT", idempotency_key, {})
            return self.get_contract(tenant, contract_id)
        with self._sqlite() as db:
            old = db.execute("SELECT contract_id FROM air_commercial_contract_events WHERE tenant_id=? AND idempotency_key=?",(tenant,idempotency_key)).fetchone()
            if old: return self.get_contract(tenant, old["contract_id"])
            db.execute("""INSERT INTO air_commercial_contracts
              (contract_id,tenant_id,customer_id,product_code,plan_code,billing_period,currency,amount_minor,start_date,end_date,grace_end_date,status,auto_renew,created_at,updated_at)
              VALUES (:contract_id,:tenant_id,:customer_id,:product_code,:plan_code,:billing_period,:currency,:amount_minor,:start_date,:end_date,:grace_end_date,:status,:auto_renew,:created_at,:updated_at)""", values)
            db.execute("""INSERT INTO air_commercial_contract_events
              (event_id,contract_id,tenant_id,actor_id,event_type,from_status,to_status,idempotency_key,payload,occurred_at)
              VALUES (?,?,?,?,?,?,?,?,?,?)""",(str(uuid4()),contract_id,tenant,actor,"CONTRACT_CREATED",None,"DRAFT",idempotency_key,"{}",now))
        return self.get_contract(tenant, contract_id)

    def _event(self, conn, values, actor, event_type, old, new, key, payload):
        conn.execute(text("""INSERT INTO air_commercial_contract_events
          (event_id,contract_id,tenant_id,actor_id,event_type,from_status,to_status,idempotency_key,payload,occurred_at)
          VALUES (:id,:contract,:tenant,:actor,:type,:old,:new,:key,CAST(:payload AS json),:now)"""),
          {"id":str(uuid4()),"contract":values["contract_id"],"tenant":values["tenant_id"],"actor":actor,
           "type":event_type,"old":old,"new":new,"key":key,"payload":json.dumps(payload,sort_keys=True),
           "now":datetime.now(timezone.utc)})

    def transition(self, tenant_id: str, contract_id: str, to_status: str, *, actor_id: str,
                   idempotency_key: str, payload: dict | None = None, grace_days: int | None = None):
        target = str(to_status).upper()
        if target not in STATES: raise ValueError("Unknown contract state")
        if not idempotency_key or len(idempotency_key)>200: raise ValueError("A bounded idempotency key is required")
        if self.engine:
            with self.engine.begin() as conn:
                row=conn.execute(text("SELECT * FROM air_commercial_contracts WHERE tenant_id=:t AND contract_id=:c FOR UPDATE"),
                                 {"t":tenant_id,"c":contract_id}).mappings().first()
                if not row: raise KeyError("Contract not found")
                prior=conn.execute(text("SELECT 1 FROM air_commercial_contract_events WHERE tenant_id=:t AND idempotency_key=:k"),
                                   {"t":tenant_id,"k":idempotency_key}).first()
                if prior: return dict(row)
                if target not in TRANSITIONS[row["status"]]: raise ContractConflict(f"Illegal transition {row['status']} -> {target}")
                conn.execute(text("UPDATE air_commercial_contracts SET status=:s,updated_at=:n,version=version+1 WHERE tenant_id=:t AND contract_id=:c"),
                             {"s":target,"n":datetime.now(timezone.utc),"t":tenant_id,"c":contract_id})
                self._event(conn,dict(row),actor_id,"STATUS_CHANGED",row["status"],target,idempotency_key,payload or {})
            return self.get_contract(tenant_id,contract_id)
        with self._sqlite() as db:
            row=db.execute("SELECT * FROM air_commercial_contracts WHERE tenant_id=? AND contract_id=?",(tenant_id,contract_id)).fetchone()
            if not row: raise KeyError("Contract not found")
            prior=db.execute("SELECT 1 FROM air_commercial_contract_events WHERE tenant_id=? AND idempotency_key=?",(tenant_id,idempotency_key)).fetchone()
            if prior: return dict(row)
            if target not in TRANSITIONS[row["status"]]: raise ContractConflict(f"Illegal transition {row['status']} -> {target}")
            now=datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE air_commercial_contracts SET status=?,updated_at=?,version=version+1 WHERE tenant_id=? AND contract_id=?",
                       (target,now,tenant_id,contract_id))
            db.execute("""INSERT INTO air_commercial_contract_events
              (event_id,contract_id,tenant_id,actor_id,event_type,from_status,to_status,idempotency_key,payload,occurred_at)
              VALUES (?,?,?,?,?,?,?,?,?,?)""",(str(uuid4()),contract_id,tenant_id,actor_id,"STATUS_CHANGED",row["status"],target,idempotency_key,json.dumps(payload or {},sort_keys=True),now))
        return self.get_contract(tenant_id,contract_id)

    def get_contract(self, tenant_id: str, contract_id: str):
        if self.engine:
            with self.engine.connect() as conn:
                row=conn.execute(text("SELECT * FROM air_commercial_contracts WHERE tenant_id=:t AND contract_id=:c"),{"t":tenant_id,"c":contract_id}).mappings().first()
                return dict(row) if row else None
        with self._sqlite() as db:
            row=db.execute("SELECT * FROM air_commercial_contracts WHERE tenant_id=? AND contract_id=?",(tenant_id,contract_id)).fetchone()
            return dict(row) if row else None

    def list_contracts(self, tenant_id: str):
        if self.engine:
            with self.engine.connect() as conn:
                return [dict(r) for r in conn.execute(text("SELECT * FROM air_commercial_contracts WHERE tenant_id=:t ORDER BY created_at DESC"),{"t":tenant_id}).mappings()]
        with self._sqlite() as db:
            return [dict(r) for r in db.execute("SELECT * FROM air_commercial_contracts WHERE tenant_id=? ORDER BY created_at DESC",(tenant_id,)).fetchall()]

    def events(self, tenant_id: str, contract_id: str):
        if self.engine:
            with self.engine.connect() as conn:
                return [dict(r) for r in conn.execute(text("SELECT * FROM air_commercial_contract_events WHERE tenant_id=:t AND contract_id=:c ORDER BY occurred_at,event_id"),{"t":tenant_id,"c":contract_id}).mappings()]
        with self._sqlite() as db:
            return [dict(r) for r in db.execute("SELECT * FROM air_commercial_contract_events WHERE tenant_id=? AND contract_id=? ORDER BY occurred_at,event_id",(tenant_id,contract_id)).fetchall()]
