"""Durable tenant usage metering and quota enforcement for Gate 17F-3.

PostgreSQL is the production ledger; SQLite is the self-hosted/local fallback.
Usage events are immutable, tenant-scoped and idempotent. No overage is billed.
"""
from __future__ import annotations
import json, os
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
from functools import wraps
from sqlalchemy import create_engine, text

METRICS = frozenset({"api_calls", "compute_seconds", "storage_bytes", "seats", "licensed_data_bytes"})
PERIODS = frozenset({"DAILY", "MONTHLY", "ANNUAL"})
PLAN_QUOTAS = {
 "B2C_FREE":{"api_calls":("DAILY",1000,1200),"compute_seconds":("MONTHLY",3600,4200),"storage_bytes":("MONTHLY",1073741824,1181116006),"seats":("MONTHLY",1,1),"licensed_data_bytes":("MONTHLY",0,0)},
 "B2C_ESSENTIAL_ANNUAL":{"api_calls":("DAILY",10000,12000),"compute_seconds":("MONTHLY",36000,43200),"storage_bytes":("MONTHLY",5368709120,5905580032),"seats":("MONTHLY",1,1),"licensed_data_bytes":("MONTHLY",5368709120,5905580032)},
 "B2C_TRADER_ANNUAL":{"api_calls":("DAILY",50000,60000),"compute_seconds":("MONTHLY",144000,172800),"storage_bytes":("MONTHLY",26843545600,29527900160),"seats":("MONTHLY",1,1),"licensed_data_bytes":("MONTHLY",21474836480,23622320128)},
 "B2C_PROFESSIONAL_ANNUAL":{"api_calls":("DAILY",200000,240000),"compute_seconds":("MONTHLY",720000,864000),"storage_bytes":("MONTHLY",107374182400,118111600640),"seats":("MONTHLY",3,3),"licensed_data_bytes":("MONTHLY",107374182400,118111600640)},
 "B2C_ELITE_ANNUAL":{"api_calls":("DAILY",1000000,1200000),"compute_seconds":("MONTHLY",3600000,4320000),"storage_bytes":("MONTHLY",1099511627776,1209462790554),"seats":("MONTHLY",5,5),"licensed_data_bytes":("MONTHLY",1099511627776,1209462790554)},
 "B2B_TEAM_ANNUAL":{"api_calls":("DAILY",100000,120000),"compute_seconds":("MONTHLY",360000,432000),"storage_bytes":("MONTHLY",107374182400,118111600640),"seats":("MONTHLY",10,10),"licensed_data_bytes":("MONTHLY",107374182400,118111600640)},
 "B2B_BUSINESS_ANNUAL":{"api_calls":("DAILY",500000,600000),"compute_seconds":("MONTHLY",1800000,2160000),"storage_bytes":("MONTHLY",536870912000,590558003200),"seats":("MONTHLY",50,50),"licensed_data_bytes":("MONTHLY",536870912000,590558003200)},
 "B2B_INSTITUTIONAL_ANNUAL":{"api_calls":("DAILY",2000000,2400000),"compute_seconds":("MONTHLY",7200000,8640000),"storage_bytes":("MONTHLY",2199023255552,2418925581107),"seats":("MONTHLY",250,250),"licensed_data_bytes":("MONTHLY",2199023255552,2418925581107)},
}
UNITS={"api_calls":"calls","compute_seconds":"seconds","storage_bytes":"bytes","seats":"seats","licensed_data_bytes":"bytes"}

def _tenant_scoped(method):
    @wraps(method)
    def wrapped(self, tenant_id, customer_id, *args, **kwargs):
        if self.engine.dialect.name == "postgresql":
            from app.tenant_context import tenant_scope
            with tenant_scope(tenant_id=tenant_id, customer_id=customer_id):
                return method(self, tenant_id, customer_id, *args, **kwargs)
        return method(self, tenant_id, customer_id, *args, **kwargs)
    return wrapped

class UsageQuotaExceeded(RuntimeError): pass
class UnknownUsagePlan(ValueError): pass

def usage_period(period: str, now: datetime | None = None):
    kind=str(period).upper()
    if kind not in PERIODS: raise ValueError("Unsupported usage period")
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None: current=current.replace(tzinfo=timezone.utc)
    day=current.astimezone(timezone.utc).date()
    if kind=="DAILY": return day,date.fromordinal(day.toordinal()+1)
    if kind=="MONTHLY":
        start=day.replace(day=1)
        end=date(start.year+1,1,1) if start.month==12 else date(start.year,start.month+1,1)
        return start,end
    return date(day.year,1,1),date(day.year+1,1,1)

class UsageMeter:
    def __init__(self,database_url: str | None=None,sqlite_path: str | None=None):
        self.database_url=database_url or (Path(os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE","")).read_text(encoding="utf-8").strip()
            if os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE") else os.getenv("AIR_CUSTOMER_DATABASE_URL","").strip())
        self.sqlite_path=sqlite_path or os.getenv("AIR_USAGE_DB_PATH","data/usage_metering.sqlite3")
        if self.database_url.startswith(("postgresql://","postgresql+psycopg://")):
            self.engine=create_engine(self.database_url,pool_pre_ping=True,future=True)
            from app.tenant_context import install_tenant_context
            install_tenant_context(self.engine)
            with self.engine.connect() as conn:
                if not conn.execute(text("SELECT to_regclass('public.air_usage_events')")).scalar():
                    raise RuntimeError("Usage metering migration 0023 must be applied before use")
        elif self.database_url: raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must use PostgreSQL")
        else:
            Path(self.sqlite_path).parent.mkdir(parents=True,exist_ok=True)
            self.engine=create_engine("sqlite:///"+str(Path(self.sqlite_path).resolve()),future=True,connect_args={"timeout":30})
            self._sqlite_schema()

    def _sqlite_schema(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_usage_events(
              event_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,customer_id TEXT NOT NULL,metric TEXT NOT NULL,
              quantity BIGINT NOT NULL,unit TEXT NOT NULL,period TEXT NOT NULL,period_start DATE NOT NULL,
              period_end DATE NOT NULL,event_type TEXT NOT NULL,status TEXT NOT NULL,idempotency_key TEXT NOT NULL,
              actor_id TEXT NOT NULL,metadata_json TEXT NOT NULL,occurred_at TIMESTAMP NOT NULL,
              UNIQUE(tenant_id,idempotency_key),CHECK(metric IN ('api_calls','compute_seconds','storage_bytes','seats','licensed_data_bytes')),
              CHECK(status IN ('ACCEPTED','REJECTED')),CHECK(quantity <> 0))""")
            conn.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_usage_counters(
              tenant_id TEXT NOT NULL,metric TEXT NOT NULL,period TEXT NOT NULL,period_start DATE NOT NULL,
              period_end DATE NOT NULL,quantity BIGINT NOT NULL DEFAULT 0,updated_at TIMESTAMP NOT NULL,
              PRIMARY KEY(tenant_id,metric,period,period_start),CHECK(quantity >= 0))""")
            conn.exec_driver_sql("""CREATE TABLE IF NOT EXISTS air_usage_quota_overrides(
              tenant_id TEXT NOT NULL,metric TEXT NOT NULL,period TEXT NOT NULL,soft_limit BIGINT,hard_limit BIGINT,
              updated_by TEXT NOT NULL,updated_at TIMESTAMP NOT NULL,PRIMARY KEY(tenant_id,metric,period),
              CHECK(soft_limit IS NULL OR soft_limit >= 0),CHECK(hard_limit IS NULL OR hard_limit >= 0),
              CHECK(soft_limit IS NULL OR hard_limit IS NULL OR soft_limit <= hard_limit))""")

    def _quota(self,conn,tenant_id,plan_code,metric):
        plan=PLAN_QUOTAS.get(str(plan_code or "").upper())
        if plan is None: raise UnknownUsagePlan("Unknown plan has no usage allowance")
        period,soft,hard=plan[metric]
        override=conn.execute(text("SELECT period,soft_limit,hard_limit FROM air_usage_quota_overrides WHERE tenant_id=:t AND metric=:m"),
                              {"t":tenant_id,"m":metric}).mappings().first()
        if override:
            period=override["period"]
            if override["soft_limit"] is not None: soft=int(override["soft_limit"])
            if override["hard_limit"] is not None: hard=int(override["hard_limit"])
        return period,soft,hard

    @_tenant_scoped
    def record_usage(self,tenant_id,customer_id,metric,quantity=1,*,plan_code,idempotency_key,actor_id=None,now=None,metadata=None):
        tenant,customer,key=str(tenant_id or "").strip(),str(customer_id or "").strip(),str(idempotency_key or "").strip()
        name=str(metric or "").strip().lower()
        amount=int(quantity)
        if not tenant or not customer or not key or len(key)>200: raise ValueError("Tenant, customer and bounded idempotency key are required")
        if name not in METRICS or amount<=0: raise ValueError("A supported metric and positive quantity are required")
        if len(json.dumps(metadata or {},sort_keys=True))>8192: raise ValueError("Usage metadata exceeds the allowed size")
        current=now or datetime.now(timezone.utc)
        if current.tzinfo is None: current=current.replace(tzinfo=timezone.utc)
        occurred=current.astimezone(timezone.utc)
        with self.engine.begin() as conn:
            period,soft,hard=self._quota(conn,tenant,plan_code,name)
            start,end=usage_period(period,occurred)
            conn.execute(text("""INSERT INTO air_usage_counters(tenant_id,metric,period,period_start,period_end,quantity,updated_at)
              VALUES(:t,:m,:p,:s,:e,0,:n) ON CONFLICT(tenant_id,metric,period,period_start) DO NOTHING"""),
              {"t":tenant,"m":name,"p":period,"s":start,"e":end,"n":occurred})
            suffix="" if self.engine.dialect.name=="sqlite" else " FOR UPDATE"
            current_total=int(conn.execute(text(f"""SELECT quantity FROM air_usage_counters
              WHERE tenant_id=:t AND metric=:m AND period=:p AND period_start=:s{suffix}"""),
              {"t":tenant,"m":name,"p":period,"s":start}).scalar_one())
            allowed=hard is None or current_total+amount<=int(hard)
            soft_exceeded=soft is not None and current_total+amount>int(soft)
            status="ACCEPTED" if allowed else "REJECTED"
            inserted=conn.execute(text("""INSERT INTO air_usage_events
              (event_id,tenant_id,customer_id,metric,quantity,unit,period,period_start,period_end,event_type,status,
               idempotency_key,actor_id,metadata_json,occurred_at)
              VALUES(:id,:t,:c,:m,:q,:u,:p,:s,:e,'METERED',:status,:key,:actor,:metadata,:n)
              ON CONFLICT(tenant_id,idempotency_key) DO NOTHING"""),
              {"id":str(uuid4()),"t":tenant,"c":customer,"m":name,"q":amount,"u":UNITS[name],"p":period,
               "s":start,"e":end,"status":status,"key":key,"actor":actor_id or customer,
               "metadata":json.dumps(metadata or {},sort_keys=True),"n":occurred})
            if inserted.rowcount==0:
                old=conn.execute(text("""SELECT event_id,customer_id,metric,quantity,unit,period,period_start,period_end,status,idempotency_key
                  FROM air_usage_events WHERE tenant_id=:t AND idempotency_key=:key"""),{"t":tenant,"key":key}).mappings().one()
                if (old["customer_id"] != customer or old["metric"] != name or int(old["quantity"]) != amount
                    or old["period"] != period or str(old["period_start"]) != str(start)):
                    raise ValueError("Idempotency key was already used for a different usage event")
                return {**dict(old),"allowed":old["status"]=="ACCEPTED","idempotent_replay":True,"soft_limit_exceeded":False}
            if allowed:
                conn.execute(text("""UPDATE air_usage_counters SET quantity=quantity+:q,updated_at=:n
                  WHERE tenant_id=:t AND metric=:m AND period=:p AND period_start=:s"""),
                  {"q":amount,"n":occurred,"t":tenant,"m":name,"p":period,"s":start})
            event_id=conn.execute(text("SELECT event_id FROM air_usage_events WHERE tenant_id=:t AND idempotency_key=:k"),
                                  {"t":tenant,"k":key}).scalar_one()
            return {"event_id":event_id,"metric":name,"quantity":amount,"unit":UNITS[name],"period":period,
              "period_start":start,"period_end":end,"status":status,"allowed":allowed,
              "soft_limit_exceeded":bool(soft_exceeded),"used":current_total+(amount if allowed else 0),
              "soft_limit":soft,"hard_limit":hard,"idempotent_replay":False}

    @_tenant_scoped
    def adjust_usage(self,tenant_id,customer_id,metric,quantity,*,plan_code,idempotency_key,actor_id,now=None,reason=""):
        tenant,customer,key=str(tenant_id or "").strip(),str(customer_id or "").strip(),str(idempotency_key or "").strip()
        name,delta=str(metric or "").lower(),int(quantity)
        if not tenant or not customer or not key or len(key)>200 or not actor_id:
            raise ValueError("Tenant, customer, actor and bounded idempotency key are required")
        if name not in METRICS or delta==0:
            raise ValueError("A supported metric and non-zero adjustment are required")
        current=now or datetime.now(timezone.utc)
        if current.tzinfo is None: current=current.replace(tzinfo=timezone.utc)
        occurred=current.astimezone(timezone.utc)
        with self.engine.begin() as conn:
            period,_,_=self._quota(conn,tenant,plan_code,name)
            start,end=usage_period(period,occurred)
            conn.execute(text("""INSERT INTO air_usage_counters(tenant_id,metric,period,period_start,period_end,quantity,updated_at)
              VALUES(:t,:m,:p,:s,:e,0,:n) ON CONFLICT(tenant_id,metric,period,period_start) DO NOTHING"""),
              {"t":tenant,"m":name,"p":period,"s":start,"e":end,"n":occurred})
            suffix="" if self.engine.dialect.name=="sqlite" else " FOR UPDATE"
            used=int(conn.execute(text(f"""SELECT quantity FROM air_usage_counters
              WHERE tenant_id=:t AND metric=:m AND period=:p AND period_start=:s{suffix}"""),
              {"t":tenant,"m":name,"p":period,"s":start}).scalar_one())
            if used+delta<0: raise ValueError("Adjustment would make usage negative")
            inserted=conn.execute(text("""INSERT INTO air_usage_events
              (event_id,tenant_id,customer_id,metric,quantity,unit,period,period_start,period_end,event_type,status,
               idempotency_key,actor_id,metadata_json,occurred_at)
              VALUES(:id,:t,:c,:m,:q,:u,:p,:s,:e,'ADJUSTMENT','ACCEPTED',:key,:actor,:metadata,:n)
              ON CONFLICT(tenant_id,idempotency_key) DO NOTHING"""),
              {"id":str(uuid4()),"t":tenant,"c":customer,"m":name,"q":delta,"u":UNITS[name],"p":period,
               "s":start,"e":end,"key":key,"actor":actor_id,
               "metadata":json.dumps({"reason":reason},sort_keys=True),"n":occurred})
            if inserted.rowcount==0:
                old=conn.execute(text("SELECT event_id,customer_id,metric,quantity,event_type,status,idempotency_key FROM air_usage_events WHERE tenant_id=:t AND idempotency_key=:k"),
                                 {"t":tenant,"k":key}).mappings().one()
                if (old["customer_id"] != customer or old["metric"] != name or int(old["quantity"]) != delta
                    or old["event_type"] != "ADJUSTMENT"):
                    raise ValueError("Idempotency key was already used for a different usage event")
                return {**dict(old),"idempotent_replay":True}
            conn.execute(text("""UPDATE air_usage_counters SET quantity=quantity+:delta,updated_at=:n
              WHERE tenant_id=:t AND metric=:m AND period=:p AND period_start=:s"""),
              {"delta":delta,"n":occurred,"t":tenant,"m":name,"p":period,"s":start})
            event_id=conn.execute(text("SELECT event_id FROM air_usage_events WHERE tenant_id=:t AND idempotency_key=:k"),
                                  {"t":tenant,"k":key}).scalar_one()
            return {"event_id":event_id,"metric":name,"adjustment":delta,"used":used+delta,
                    "idempotent_replay":False,"actor_id":actor_id}

    def consume(self,*args,**kwargs):
        result=self.record_usage(*args,**kwargs)
        if not result["allowed"]: raise UsageQuotaExceeded(f"Tenant {result['metric']} quota has been reached")
        return result

    def get_usage(self,tenant_id,plan_code,now=None):
        current=now or datetime.now(timezone.utc)
        rows=[]
        with self.engine.connect() as conn:
            for metric in sorted(METRICS):
                period,soft,hard=self._quota(conn,tenant_id,plan_code,metric)
                start,end=usage_period(period,current)
                used=conn.execute(text("""SELECT quantity FROM air_usage_counters
                  WHERE tenant_id=:t AND metric=:m AND period=:p AND period_start=:s"""),
                  {"t":tenant_id,"m":metric,"p":period,"s":start}).scalar()
                count=int(used or 0)
                rows.append({"metric":metric,"unit":UNITS[metric],"period":period,"period_start":start,"period_end":end,
                  "used":count,"soft_limit":soft,"hard_limit":hard,
                  "soft_limit_exceeded":soft is not None and count>=int(soft),
                  "hard_limit_reached":hard is not None and count>=int(hard)})
        return rows

    def set_quota_override(self,tenant_id,metric,period,*,soft_limit,hard_limit,actor_id):
        name,kind=str(metric or "").lower(),str(period or "").upper()
        if not tenant_id or name not in METRICS or kind not in PERIODS: raise ValueError("A valid tenant, metric and period are required")
        if (soft_limit is not None and int(soft_limit)<0) or (hard_limit is not None and int(hard_limit)<0):
            raise ValueError("Quota limits cannot be negative")
        if soft_limit is not None and hard_limit is not None and int(soft_limit)>int(hard_limit):
            raise ValueError("Soft limit cannot exceed hard limit")
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO air_usage_quota_overrides
              (tenant_id,metric,period,soft_limit,hard_limit,updated_by,updated_at)
              VALUES(:t,:m,:p,:s,:h,:a,:n) ON CONFLICT(tenant_id,metric,period) DO UPDATE SET
              period=excluded.period,soft_limit=excluded.soft_limit,hard_limit=excluded.hard_limit,
              updated_by=excluded.updated_by,updated_at=excluded.updated_at"""),
              {"t":tenant_id,"m":name,"p":kind,"s":soft_limit,"h":hard_limit,"a":actor_id,"n":datetime.now(timezone.utc)})
        return {"tenant_id":tenant_id,"metric":name,"period":kind,"soft_limit":soft_limit,"hard_limit":hard_limit,"updated_by":actor_id}
