"""Durable AIR MPDSM cycle and immutable evaluation snapshot repository."""
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path
from uuid import uuid4
from app.db_compat import PostgresConnection, read_database_url

class AirMonthlyPdStore:
    def __init__(self, db_path: str|None=None):
        url=None if db_path is not None else (read_database_url("AIR_MONTHLY_PD_DATABASE_URL") or read_database_url("AIR_DATABASE_URL"))
        self.is_postgres=bool(url)
        if url:
            self.db=PostgresConnection(url)
            try:
                self.db.execute("SELECT 1 FROM air_monthly_pd_cycles LIMIT 0")
                self.db.execute("SELECT 1 FROM air_monthly_pd_snapshots LIMIT 0")
            except Exception as exc:
                self.db.close()
                raise RuntimeError("AIR MPDSM schema missing; apply Alembic migrations first") from exc
        else:
            path=db_path or os.getenv("AIR_MONTHLY_PD_DB_PATH","data/air_monthly_pd.sqlite3")
            if path!=":memory:": Path(path).parent.mkdir(parents=True,exist_ok=True)
            self.db=sqlite3.connect(path,check_same_thread=False,timeout=30)
            self.db.row_factory=sqlite3.Row
            self.db.execute("PRAGMA busy_timeout=30000")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS air_monthly_pd_cycles(
              cycle_id TEXT PRIMARY KEY,instrument_type TEXT NOT NULL,symbol TEXT NOT NULL,
              cycle_month TEXT NOT NULL,reference_date TEXT NOT NULL,
              previous_month_pml REAL NOT NULL,previous_month_pmh REAL NOT NULL,equilibrium REAL NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(instrument_type,symbol,cycle_month));
            CREATE INDEX IF NOT EXISTS ix_air_monthly_pd_cycle_month ON air_monthly_pd_cycles(cycle_month,instrument_type);
            CREATE TABLE IF NOT EXISTS air_monthly_pd_snapshots(
              snapshot_id TEXT PRIMARY KEY,cycle_id TEXT NOT NULL REFERENCES air_monthly_pd_cycles(cycle_id),
              as_of_date TEXT NOT NULL,snapshot_type TEXT NOT NULL,support_status TEXT NOT NULL,
              pattern TEXT NOT NULL,pattern_state TEXT NOT NULL,expiry_metadata TEXT NOT NULL DEFAULT '{}',
              evidence TEXT NOT NULL DEFAULT '{}',forecast TEXT NOT NULL DEFAULT '{}',actual TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(cycle_id,as_of_date,snapshot_type));
            CREATE INDEX IF NOT EXISTS ix_air_monthly_pd_snapshot_date ON air_monthly_pd_snapshots(as_of_date,snapshot_type);
            """)
            self.db.commit()

    def save_cycle(self, *, instrument_type, symbol, cycle_month, reference_date, pml, pmh, eq):
        if instrument_type not in {"EQUITY","INDEX"}: raise ValueError("instrument_type must be EQUITY or INDEX")
        if not symbol or not cycle_month or not (0 < float(pml) <= float(pmh)) or not float(pml) <= float(eq) <= float(pmh):
            raise ValueError("Invalid monthly cycle identity or levels")
        cycle_id=str(uuid4())
        with self.db:
            self.db.execute("""INSERT INTO air_monthly_pd_cycles
              (cycle_id,instrument_type,symbol,cycle_month,reference_date,previous_month_pml,previous_month_pmh,equilibrium)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(instrument_type,symbol,cycle_month) DO NOTHING""",
              (cycle_id,instrument_type,symbol.upper(),cycle_month,reference_date,pml,pmh,eq))
        row=self.db.execute("SELECT * FROM air_monthly_pd_cycles WHERE instrument_type=? AND symbol=? AND cycle_month=?",
                            (instrument_type,symbol.upper(),cycle_month)).fetchone()
        return dict(row)

    def save_snapshot(self, *, cycle_id, as_of_date, snapshot_type, support_status, pattern,
                      pattern_state, expiry_metadata=None, evidence=None, forecast=None, actual=None):
        snapshot_id=str(uuid4())
        vals=(snapshot_id,cycle_id,as_of_date,snapshot_type,support_status,pattern,pattern_state,
              json.dumps(expiry_metadata or {},allow_nan=False),json.dumps(evidence or {},allow_nan=False),
              json.dumps(forecast or {},allow_nan=False),json.dumps(actual or {},allow_nan=False))
        with self.db:
            self.db.execute("""INSERT INTO air_monthly_pd_snapshots
              (snapshot_id,cycle_id,as_of_date,snapshot_type,support_status,pattern,pattern_state,
               expiry_metadata,evidence,forecast,actual)
              VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cycle_id,as_of_date,snapshot_type) DO NOTHING""",vals)
        row=self.db.execute("SELECT * FROM air_monthly_pd_snapshots WHERE cycle_id=? AND as_of_date=? AND snapshot_type=?",
                            (cycle_id,as_of_date,snapshot_type)).fetchone()
        return self._decode(row)

    @staticmethod
    def _decode(row):
        if row is None:return None
        item=dict(row)
        for key in ("expiry_metadata","evidence","forecast","actual"):
            if isinstance(item.get(key),str): item[key]=json.loads(item[key])
        return item

    def list_cycles(self, symbol=None, cycle_month=None, limit=500):
        clauses=[]; params=[]
        if symbol: clauses.append("symbol=?"); params.append(symbol.upper())
        if cycle_month: clauses.append("cycle_month=?"); params.append(cycle_month)
        where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
        rows=self.db.execute("SELECT * FROM air_monthly_pd_cycles"+where+" ORDER BY cycle_month DESC,symbol LIMIT ?",
                             (*params,max(1,min(int(limit),2000)))).fetchall()
        return [dict(x) for x in rows]

    def list_snapshots(self, cycle_id=None, limit=500):
        where=" WHERE cycle_id=?" if cycle_id else ""
        params=(cycle_id,max(1,min(int(limit),2000))) if cycle_id else (max(1,min(int(limit),2000)),)
        rows=self.db.execute("SELECT * FROM air_monthly_pd_snapshots"+where+" ORDER BY as_of_date DESC LIMIT ?",params).fetchall()
        return [self._decode(x) for x in rows]

    def close(self): self.db.close()
