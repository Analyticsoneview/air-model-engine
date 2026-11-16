"""Tenant-scoped invoice, tax, credit-note, settlement and reconciliation ledger.

All monetary values are integer minor units. Tax components are explicit amounts;
the service never assumes a jurisdiction or tax rate. No payment collection occurs.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


class BillingConflict(ValueError):
    pass


def _tenant_scoped(method):
    @wraps(method)
    def wrapped(self, tenant_id, *args, **kwargs):
        if self.engine.dialect.name == "postgresql":
            from app.tenant_context import tenant_scope
            with tenant_scope(tenant_id=tenant_id):
                return method(self, tenant_id, *args, **kwargs)
        return method(self, tenant_id, *args, **kwargs)
    return wrapped


def _now():
    return datetime.now(timezone.utc)


def _currency(value):
    code = str(value or "").strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("currency must be a three-letter ISO code")
    return code


def _taxes(value):
    if not isinstance(value, list) or len(value) > 12:
        raise ValueError("tax_breakdown must be a list with at most 12 components")
    result, total = [], 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each tax component must be an object")
        name = str(item.get("name") or "").strip()
        code = str(item.get("code") or "").strip().upper()
        amount = item.get("amount_minor")
        if not name or len(name) > 80 or not code or len(code) > 24:
            raise ValueError("Tax component name and code are required and bounded")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError("Tax component amount_minor must be a non-negative integer")
        result.append({"name": name, "code": code, "amount_minor": amount})
        total += amount
    return result, total


class BillingStore:
    def __init__(self, database_url=None, sqlite_path=None):
        url = database_url if database_url is not None else os.getenv("AIR_CUSTOMER_DATABASE_URL", "").strip()
        self.sqlite_path = sqlite_path or os.getenv("AIR_BILLING_DB_PATH", "data/billing.sqlite3")
        if url.startswith(("postgresql://", "postgresql+psycopg://")):
            self.engine = create_engine(url, pool_pre_ping=True, future=True)
            from app.tenant_context import install_tenant_context
            install_tenant_context(self.engine)
            with self.engine.connect() as conn:
                if not conn.execute(text("SELECT to_regclass('public.air_billing_invoices')")).scalar():
                    raise RuntimeError("Billing migration 0025 must be applied before use")
        elif url:
            raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must use PostgreSQL")
        else:
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine("sqlite:///" + str(Path(self.sqlite_path).resolve()),
                                        future=True, connect_args={"timeout": 30})
            self._sqlite_schema()

    def _sqlite_schema(self):
        with self.engine.begin() as c:
            c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_billing_invoices(
                invoice_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,customer_id TEXT NOT NULL,
                invoice_number TEXT NOT NULL,currency TEXT NOT NULL,subtotal_minor INTEGER NOT NULL,
                tax_total_minor INTEGER NOT NULL,total_minor INTEGER NOT NULL,status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,issued_at TEXT,created_at TEXT NOT NULL,
                UNIQUE(tenant_id,invoice_number),UNIQUE(tenant_id,idempotency_key))""")
            c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_billing_invoice_lines(
                line_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,invoice_id TEXT NOT NULL,
                description TEXT NOT NULL,quantity INTEGER NOT NULL,unit_amount_minor INTEGER NOT NULL,
                tax_breakdown TEXT NOT NULL,line_subtotal_minor INTEGER NOT NULL,line_tax_minor INTEGER NOT NULL)""")
            c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_billing_refunds(
                refund_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,invoice_id TEXT NOT NULL,
                credit_note_number TEXT NOT NULL,amount_minor INTEGER NOT NULL,currency TEXT NOT NULL,
                reason TEXT NOT NULL,idempotency_key TEXT NOT NULL,created_at TEXT NOT NULL,
                UNIQUE(tenant_id,idempotency_key),UNIQUE(tenant_id,credit_note_number))""")
            c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_billing_settlements(
                settlement_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,provider TEXT NOT NULL,
                provider_reference TEXT NOT NULL,currency TEXT NOT NULL,amount_minor INTEGER NOT NULL,
                settled_at TEXT,created_at TEXT NOT NULL,
                UNIQUE(tenant_id,provider,provider_reference))""")
            c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_billing_reconciliations(
                reconciliation_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,settlement_id TEXT NOT NULL,
                expected_amount_minor INTEGER NOT NULL,settled_amount_minor INTEGER NOT NULL,
                difference_minor INTEGER NOT NULL,status TEXT NOT NULL,notes TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(tenant_id,idempotency_key))""")
            c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_billing_audit_events(
                event_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,event_type TEXT NOT NULL,actor_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,details TEXT NOT NULL,occurred_at TEXT NOT NULL,
                UNIQUE(tenant_id,idempotency_key))""")

    def _audit(self, conn, tenant, entity_type, entity_id, event_type, actor, key, details):
        conn.execute(text("""INSERT INTO air_billing_audit_events
            (event_id,tenant_id,entity_type,entity_id,event_type,actor_id,idempotency_key,details,occurred_at)
            VALUES(:id,:tenant,:entity_type,:entity_id,:event_type,:actor,:key,:details,:now)"""),
            {"id":str(uuid4()),"tenant":tenant,"entity_type":entity_type,"entity_id":entity_id,
             "event_type":event_type,"actor":actor,"key":f"{entity_type}:{event_type}:{key}","details":json.dumps(details,sort_keys=True),
             "now":_now()})

    def _invoice(self, conn, tenant, invoice_id):
        row=conn.execute(text("""SELECT * FROM air_billing_invoices
            WHERE tenant_id=:tenant AND invoice_id=:id"""),{"tenant":tenant,"id":invoice_id}).mappings().first()
        if not row: return None
        item=dict(row)
        lines=conn.execute(text("""SELECT * FROM air_billing_invoice_lines
            WHERE tenant_id=:tenant AND invoice_id=:id ORDER BY line_id"""),{"tenant":tenant,"id":invoice_id}).mappings().all()
        item["lines"]=[]
        for line in lines:
            obj=dict(line)
            if isinstance(obj.get("tax_breakdown"),str): obj["tax_breakdown"]=json.loads(obj["tax_breakdown"])
            item["lines"].append(obj)
        refunds=conn.execute(text("""SELECT refund_id,credit_note_number,amount_minor,currency,reason,created_at
            FROM air_billing_refunds WHERE tenant_id=:tenant AND invoice_id=:id ORDER BY created_at,refund_id"""),
            {"tenant":tenant,"id":invoice_id}).mappings().all()
        item["credit_notes"]=[dict(x) for x in refunds]
        item["refunded_minor"]=sum(int(x["amount_minor"]) for x in refunds)
        return item

    @_tenant_scoped
    def create_invoice(self, tenant_id, customer_id, invoice_number, currency, lines, idempotency_key, actor_id):
        number=str(invoice_number or "").strip()
        key=str(idempotency_key or "").strip()
        customer=str(customer_id or "").strip()
        code=_currency(currency)
        if not tenant_id or not customer or not number or len(number)>64 or not key or len(key)>200:
            raise ValueError("Tenant, customer, invoice number and bounded idempotency key are required")
        if not isinstance(lines,list) or not lines or len(lines)>100:
            raise ValueError("An invoice requires between 1 and 100 lines")
        normalized=[]; subtotal=tax_total=0
        for line in lines:
            if not isinstance(line,dict): raise ValueError("Invoice lines must be objects")
            desc=str(line.get("description") or "").strip()
            qty=line.get("quantity"); unit=line.get("unit_amount_minor")
            if not desc or len(desc)>200 or isinstance(qty,bool) or not isinstance(qty,int) or qty<=0 or qty>1000000:
                raise ValueError("Invoice line description and positive integer quantity are required")
            if isinstance(unit,bool) or not isinstance(unit,int) or unit<0:
                raise ValueError("unit_amount_minor must be a non-negative integer")
            tax_parts,tax=_taxes(line.get("tax_breakdown",[]))
            line_sub=qty*unit
            if line_sub>9_000_000_000_000_000 or subtotal+line_sub>9_000_000_000_000_000:
                raise ValueError("Invoice amount exceeds supported minor-unit range")
            normalized.append({"description":desc,"quantity":qty,"unit_amount_minor":unit,
                               "tax_breakdown":tax_parts,"line_subtotal_minor":line_sub,"line_tax_minor":tax})
            subtotal+=line_sub; tax_total+=tax
        total=subtotal+tax_total
        if total>9_000_000_000_000_000: raise ValueError("Invoice total exceeds supported minor-unit range")
        with self.engine.begin() as conn:
            prior=conn.execute(text("SELECT invoice_id,invoice_number,currency,total_minor FROM air_billing_invoices WHERE tenant_id=:t AND idempotency_key=:k"),
                               {"t":tenant_id,"k":key}).first()
            if prior:
                existing=self._invoice(conn,tenant_id,prior[0])
                expected_lines=[{"description":x["description"],"quantity":x["quantity"],"unit_amount_minor":x["unit_amount_minor"],"tax_breakdown":x["tax_breakdown"]} for x in normalized]
                actual_lines=[{"description":x["description"],"quantity":int(x["quantity"]),"unit_amount_minor":int(x["unit_amount_minor"]),"tax_breakdown":x["tax_breakdown"]} for x in existing["lines"]]
                if (
                    prior[1] != number
                    or prior[2] != code
                    or int(prior[3]) != total
                    or sorted(actual_lines, key=lambda item: json.dumps(item, sort_keys=True))
                    != sorted(expected_lines, key=lambda item: json.dumps(item, sort_keys=True))
                ):
                    raise BillingConflict("Invoice idempotency key was reused with different content")
                return existing | {"idempotent_replay":True}
            invoice_id=str(uuid4())
            conn.execute(text("""INSERT INTO air_billing_invoices
                (invoice_id,tenant_id,customer_id,invoice_number,currency,subtotal_minor,tax_total_minor,total_minor,status,idempotency_key,created_at)
                VALUES(:id,:t,:c,:number,:currency,:subtotal,:tax,:total,'DRAFT',:key,:now)"""),
                {"id":invoice_id,"t":tenant_id,"c":customer,"number":number,"currency":code,
                 "subtotal":subtotal,"tax":tax_total,"total":total,"key":key,"now":_now()})
            for line in normalized:
                conn.execute(text("""INSERT INTO air_billing_invoice_lines
                    (line_id,tenant_id,invoice_id,description,quantity,unit_amount_minor,tax_breakdown,line_subtotal_minor,line_tax_minor)
                    VALUES(:id,:t,:invoice,:description,:quantity,:unit_amount_minor,:taxes,:subtotal,:tax)"""),
                    {"id":str(uuid4()),"t":tenant_id,"invoice":invoice_id,**line,
                     "taxes":json.dumps(line["tax_breakdown"]),
                     "subtotal":line["line_subtotal_minor"],"tax":line["line_tax_minor"]})
            self._audit(conn,tenant_id,"INVOICE",invoice_id,"INVOICE_CREATED",actor_id,key,
                        {"currency":code,"subtotal_minor":subtotal,"tax_total_minor":tax_total,"total_minor":total})
            return self._invoice(conn,tenant_id,invoice_id)

    @_tenant_scoped
    def get_invoice(self, tenant_id, invoice_id):
        with self.engine.connect() as conn: return self._invoice(conn,tenant_id,invoice_id)

    @_tenant_scoped
    def list_invoices(self, tenant_id, limit=100):
        size=max(1,min(int(limit),200))
        with self.engine.connect() as conn:
            ids=conn.execute(text("""SELECT invoice_id FROM air_billing_invoices
                WHERE tenant_id=:t ORDER BY created_at DESC LIMIT :limit"""),{"t":tenant_id,"limit":size}).scalars().all()
            return [self._invoice(conn,tenant_id,item) for item in ids]

    @_tenant_scoped
    def issue_invoice(self, tenant_id, invoice_id, actor_id, idempotency_key):
        key=str(idempotency_key or "").strip()
        if not key or len(key)>200: raise ValueError("A bounded idempotency key is required")
        with self.engine.begin() as conn:
            item=self._invoice(conn,tenant_id,invoice_id)
            if not item: raise KeyError(invoice_id)
            if item["status"]=="ISSUED": return item | {"idempotent_replay":True}
            if item["status"]!="DRAFT": raise BillingConflict("Only a draft invoice can be issued")
            conn.execute(text("""UPDATE air_billing_invoices SET status='ISSUED',issued_at=:now
                WHERE tenant_id=:t AND invoice_id=:id AND status='DRAFT'"""),{"now":_now(),"t":tenant_id,"id":invoice_id})
            self._audit(conn,tenant_id,"INVOICE",invoice_id,"INVOICE_ISSUED",actor_id,key,{})
            return self._invoice(conn,tenant_id,invoice_id)

    @_tenant_scoped
    def refund_invoice(self, tenant_id, invoice_id, amount_minor, reason, actor_id, idempotency_key):
        key=str(idempotency_key or "").strip(); why=str(reason or "").strip()
        if not key or len(key)>200 or not why or len(why)>500: raise ValueError("Refund reason and bounded idempotency key are required")
        if isinstance(amount_minor,bool) or not isinstance(amount_minor,int) or amount_minor<=0: raise ValueError("Refund amount must be positive integer minor units")
        with self.engine.begin() as conn:
            prior=conn.execute(text("""SELECT refund_id,invoice_id,amount_minor,reason FROM air_billing_refunds
                WHERE tenant_id=:t AND idempotency_key=:k"""),{"t":tenant_id,"k":key}).first()
            if prior:
                if prior[1]!=invoice_id or int(prior[2])!=amount_minor or prior[3]!=why:
                    raise BillingConflict("Refund idempotency key was reused with different content")
                return {"refund_id":prior[0],"amount_minor":amount_minor,"status":"DUPLICATE"}
            suffix=" FOR UPDATE" if self.engine.dialect.name=="postgresql" else ""
            locked=conn.execute(text("SELECT invoice_id FROM air_billing_invoices WHERE tenant_id=:t AND invoice_id=:id"+suffix),{"t":tenant_id,"id":invoice_id}).first()
            invoice=self._invoice(conn,tenant_id,invoice_id)
            if not locked or not invoice: raise KeyError(invoice_id)
            if invoice["status"]!="ISSUED": raise BillingConflict("Only an issued invoice can be credited")
            remaining=int(invoice["total_minor"])-int(invoice["refunded_minor"])
            if amount_minor>remaining: raise BillingConflict("Refund exceeds the remaining invoice balance")
            refund_id=str(uuid4()); credit=f"CN-{refund_id[:12].upper()}"
            conn.execute(text("""INSERT INTO air_billing_refunds
                (refund_id,tenant_id,invoice_id,credit_note_number,amount_minor,currency,reason,idempotency_key,created_at)
                VALUES(:id,:t,:invoice,:credit,:amount,:currency,:reason,:key,:now)"""),
                {"id":refund_id,"t":tenant_id,"invoice":invoice_id,"credit":credit,"amount":amount_minor,
                 "currency":invoice["currency"],"reason":why,"key":key,"now":_now()})
            self._audit(conn,tenant_id,"CREDIT_NOTE",refund_id,"CREDIT_NOTE_ISSUED",actor_id,key,
                        {"invoice_id":invoice_id,"amount_minor":amount_minor,"currency":invoice["currency"],"reason":why})
            return {"refund_id":refund_id,"credit_note_number":credit,"invoice_id":invoice_id,
                    "amount_minor":amount_minor,"currency":invoice["currency"],"status":"RECORDED"}

    @_tenant_scoped
    def record_settlement(self, tenant_id, provider, provider_reference, currency, amount_minor, settled_at=None):
        vendor=str(provider or "").strip().lower(); reference=str(provider_reference or "").strip(); code=_currency(currency)
        if not vendor or len(vendor)>64 or not reference or len(reference)>200: raise ValueError("Provider and provider reference are required")
        if isinstance(amount_minor,bool) or not isinstance(amount_minor,int) or amount_minor<0: raise ValueError("Settlement amount must be non-negative integer minor units")
        with self.engine.begin() as conn:
            prior=conn.execute(text("""SELECT settlement_id,currency,amount_minor FROM air_billing_settlements
                WHERE tenant_id=:t AND provider=:p AND provider_reference=:r"""),{"t":tenant_id,"p":vendor,"r":reference}).first()
            if prior:
                if prior[1]!=code or int(prior[2])!=amount_minor: raise BillingConflict("Provider settlement reference was reused with different values")
                return {"settlement_id":prior[0],"status":"DUPLICATE"}
            sid=str(uuid4())
            conn.execute(text("""INSERT INTO air_billing_settlements
                (settlement_id,tenant_id,provider,provider_reference,currency,amount_minor,settled_at,created_at)
                VALUES(:id,:t,:p,:r,:c,:amount,:settled,:now)"""),
                {"id":sid,"t":tenant_id,"p":vendor,"r":reference,"c":code,"amount":amount_minor,"settled":settled_at,"now":_now()})
            self._audit(conn,tenant_id,"SETTLEMENT",sid,"SETTLEMENT_RECORDED","system",f"settlement:{vendor}:{reference}",
                        {"provider":vendor,"provider_reference":reference,"currency":code,"amount_minor":amount_minor})
            return {"settlement_id":sid,"provider":vendor,"provider_reference":reference,
                    "currency":code,"amount_minor":amount_minor,"status":"RECORDED"}

    @_tenant_scoped
    def reconcile_settlement(self, tenant_id, settlement_id, expected_amount_minor, actor_id, idempotency_key, notes=""):
        key=str(idempotency_key or "").strip(); note=str(notes or "")
        if not key or len(key)>200 or len(note)>500: raise ValueError("A bounded idempotency key and notes are required")
        if isinstance(expected_amount_minor,bool) or not isinstance(expected_amount_minor,int) or expected_amount_minor<0:
            raise ValueError("Expected amount must be a non-negative integer minor-unit amount")
        with self.engine.begin() as conn:
            prior=conn.execute(text("""SELECT reconciliation_id,settlement_id,expected_amount_minor,status,difference_minor FROM air_billing_reconciliations
                WHERE tenant_id=:t AND idempotency_key=:k"""),{"t":tenant_id,"k":key}).first()
            if prior:
                if prior[1]!=settlement_id or int(prior[2])!=expected_amount_minor:
                    raise BillingConflict("Reconciliation idempotency key was reused with different content")
                return {"reconciliation_id":prior[0],"status":prior[3],"difference_minor":int(prior[4]),"idempotent_replay":True}
            settlement=conn.execute(text("""SELECT currency,amount_minor FROM air_billing_settlements
                WHERE tenant_id=:t AND settlement_id=:id"""),{"t":tenant_id,"id":settlement_id}).first()
            if not settlement: raise KeyError(settlement_id)
            settled=int(settlement[1]); difference=settled-expected_amount_minor
            status="MATCH" if difference==0 else "MISMATCH"
            rid=str(uuid4())
            conn.execute(text("""INSERT INTO air_billing_reconciliations
                (reconciliation_id,tenant_id,settlement_id,expected_amount_minor,settled_amount_minor,difference_minor,status,notes,idempotency_key,created_at)
                VALUES(:id,:t,:sid,:expected,:settled,:diff,:status,:notes,:key,:now)"""),
                {"id":rid,"t":tenant_id,"sid":settlement_id,"expected":expected_amount_minor,"settled":settled,
                 "diff":difference,"status":status,"notes":note,"key":key,"now":_now()})
            self._audit(conn,tenant_id,"RECONCILIATION",rid,"SETTLEMENT_RECONCILED",actor_id,key,
                        {"settlement_id":settlement_id,"expected_amount_minor":expected_amount_minor,
                         "settled_amount_minor":settled,"difference_minor":difference,"status":status})
            return {"reconciliation_id":rid,"settlement_id":settlement_id,"expected_amount_minor":expected_amount_minor,
                    "settled_amount_minor":settled,"difference_minor":difference,"status":status}

    @_tenant_scoped
    def audit_events(self, tenant_id, entity_type=None, entity_id=None):
        query="SELECT * FROM air_billing_audit_events WHERE tenant_id=:t"
        params={"t":tenant_id}
        if entity_type: query+=" AND entity_type=:kind"; params["kind"]=entity_type
        if entity_id: query+=" AND entity_id=:id"; params["id"]=entity_id
        query+=" ORDER BY occurred_at,event_id"
        with self.engine.connect() as conn:
            rows=conn.execute(text(query),params).mappings().all()
            return [{**dict(row),"details":json.loads(row["details"]) if isinstance(row["details"],str) else row["details"]} for row in rows]
