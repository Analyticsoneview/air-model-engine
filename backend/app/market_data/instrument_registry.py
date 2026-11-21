"""Persistent provider-specific instrument token directory.

Broker instrument tokens are not interchangeable. Admins can import/maintain the
mapping obtained from each broker's official instrument master.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from app.db_compat import PostgresConnection, read_database_url


class MarketInstrumentDirectory:
    def __init__(self, db_path: str | None = None):
        database_url = read_database_url("AIR_MARKET_INSTRUMENT_DATABASE_URL") if db_path is None else None
        self._is_postgres = database_url is not None
        if self._is_postgres:
            self.db_path = None
            self.db = PostgresConnection(database_url)
            try:
                self.db.execute("SELECT 1 FROM market_instruments LIMIT 0")
                self.db.execute("SELECT 1 FROM market_master_refresh LIMIT 0")
                self.db.execute("SELECT 1 FROM market_instrument_lot_size_history LIMIT 0")
                self.db.execute("SELECT 1 FROM market_equity_sector_history LIMIT 0")
            except Exception as exc:
                self.db.close()
                raise RuntimeError("PostgreSQL instrument-master schema is missing; run Alembic migrations first") from exc
        else:
            self.db_path = db_path or os.getenv(
                "AIR_MARKET_INSTRUMENT_DB_PATH", "data/air_market_instruments.sqlite3"
            )
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA busy_timeout=30000")
        if not self._is_postgres:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS market_instruments (
                    provider TEXT NOT NULL, account_id TEXT NOT NULL, exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL, underlying_symbol TEXT, token TEXT NOT NULL,
                    segment TEXT NOT NULL, expiry TEXT, strike TEXT, option_type TEXT,
                    lot_size INTEGER, instrument_type TEXT, tick_size TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(provider, account_id, token)
                )
            """)
            columns = {row["name"] for row in self.db.execute("PRAGMA table_info(market_instruments)")}
            if "tick_size" not in columns:
                self.db.execute("ALTER TABLE market_instruments ADD COLUMN tick_size TEXT")
            if "underlying_symbol" not in columns:
                self.db.execute("ALTER TABLE market_instruments ADD COLUMN underlying_symbol TEXT")
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS market_master_refresh (
                    provider TEXT NOT NULL, account_id TEXT NOT NULL,
                    row_count INTEGER NOT NULL, source TEXT, refreshed_at TEXT NOT NULL,
                    PRIMARY KEY(provider, account_id)
                )
            """)
            self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_instruments_symbol
                ON market_instruments(provider, account_id, symbol)
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS market_instrument_lot_size_history (
                    provider TEXT NOT NULL, account_id TEXT NOT NULL, effective_date TEXT NOT NULL,
                    exchange TEXT NOT NULL, symbol TEXT NOT NULL, underlying_symbol TEXT,
                    token TEXT NOT NULL, segment TEXT NOT NULL, expiry TEXT, strike TEXT,
                    option_type TEXT, lot_size INTEGER, instrument_type TEXT, source TEXT,
                    captured_at TEXT NOT NULL,
                    PRIMARY KEY(provider,account_id,effective_date,token),
                    CHECK(lot_size IS NULL OR lot_size > 0)
                )
            """)
            self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_lot_size_history_contract_date
                ON market_instrument_lot_size_history(symbol,expiry,strike,option_type,effective_date)
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS market_equity_sector_history (
                    exchange TEXT NOT NULL, symbol TEXT NOT NULL, sector TEXT NOT NULL,
                    effective_from TEXT NOT NULL, effective_through TEXT,
                    source TEXT NOT NULL, source_reference TEXT, verified_at TEXT NOT NULL,
                    PRIMARY KEY(exchange,symbol,effective_from),
                    CHECK(effective_through IS NULL OR effective_through >= effective_from)
                )
            """)
            self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_equity_sector_symbol_effective
                ON market_equity_sector_history(exchange,symbol,effective_from)
            """)
            self.db.commit()

    def upsert(self, provider: str, account_id: str, *, exchange: str,
               symbol: str, token: str, segment: str, expiry: str | None = None,
               strike: str | None = None, option_type: str | None = None,
               lot_size: int | None = None, instrument_type: str | None = None,
               tick_size: str | None = None,
               underlying_symbol: str | None = None) -> dict:
        values = [provider.strip().lower(), account_id.strip(), exchange.strip().upper(),
                  symbol.strip().upper(), token.strip(), segment.strip().upper()]
        if not all(values):
            raise ValueError("Provider, account, exchange, symbol, token and segment are required")
        with self.db:
            self.db.execute("""
                INSERT INTO market_instruments(
                    provider,account_id,exchange,symbol,underlying_symbol,token,segment,expiry,strike,
                    option_type,lot_size,instrument_type,tick_size,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(provider,account_id,token) DO UPDATE SET
                    exchange=excluded.exchange,symbol=excluded.symbol,segment=excluded.segment,
                    expiry=excluded.expiry,strike=excluded.strike,option_type=excluded.option_type,
                    lot_size=excluded.lot_size,instrument_type=excluded.instrument_type,
                    tick_size=excluded.tick_size,underlying_symbol=excluded.underlying_symbol,
                    updated_at=CURRENT_TIMESTAMP
            """, (values[0], values[1], values[2], values[3], underlying_symbol or values[3],
                  values[4], values[5], expiry, strike, option_type, lot_size, instrument_type, tick_size))
        return self.get(provider, account_id, values[4]) or {}

    def replace_snapshot(self, provider: str, account_id: str,
                         instruments: list[dict], *, effective_date: str | None = None,
                         source: str | None = None) -> int:
        """Replace one provider/account master atomically after caller validation."""
        provider, account_id = provider.strip().lower(), account_id.strip()
        if not provider or not account_id or not instruments:
            raise ValueError("Provider, account and non-empty instrument master are required")
        required = ("exchange", "symbol", "token", "segment")
        seen = set()
        values = []
        for item in instruments:
            if any(not str(item.get(key) or "").strip() for key in required):
                raise ValueError("Instrument master contains incomplete rows")
            token = str(item["token"]).strip()
            if token in seen:
                continue
            seen.add(token)
            values.append((provider, account_id, str(item["exchange"]).upper(),
                str(item["symbol"]).upper(), str(item.get("underlying_symbol") or item["symbol"]).upper(),
                token, str(item["segment"]).upper(), item.get("expiry"), item.get("strike"),
                item.get("option_type"), item.get("lot_size"), item.get("instrument_type"),
                item.get("tick_size")))
        stamp = datetime.now(timezone.utc).isoformat()
        effective = date.fromisoformat(effective_date).isoformat() if effective_date else date.today().isoformat()
        with self.db:
            self.db.executemany("""
                INSERT INTO market_instrument_lot_size_history(
                    provider,account_id,effective_date,exchange,symbol,underlying_symbol,
                    token,segment,expiry,strike,option_type,lot_size,instrument_type,source,captured_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(provider,account_id,effective_date,token) DO NOTHING
            """, [(*row[:13], source, stamp) for row in values])
            self.db.execute("DELETE FROM market_instruments WHERE provider=? AND account_id=?",
                            (provider, account_id))
            self.db.executemany("""
                INSERT INTO market_instruments(
                    provider,account_id,exchange,symbol,underlying_symbol,token,segment,expiry,strike,
                    option_type,lot_size,instrument_type,tick_size,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [(*row, stamp) for row in values])
            self.db.execute("""
                INSERT INTO market_master_refresh(provider,account_id,row_count,refreshed_at)
                VALUES(?,?,?,?)
                ON CONFLICT(provider,account_id) DO UPDATE SET
                    row_count=excluded.row_count,refreshed_at=excluded.refreshed_at
            """, (provider, account_id, len(values), stamp))
        return len(values)

    def master_status(self) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT provider,account_id,row_count,source,refreshed_at FROM market_master_refresh "
            "ORDER BY provider,account_id"
        ).fetchall()]

    def get(self, provider: str, account_id: str, token: str) -> dict | None:
        row = self.db.execute("""
            SELECT * FROM market_instruments WHERE provider=? AND account_id=? AND token=?
        """, (provider.lower(), account_id, token)).fetchone()
        return dict(row) if row else None

    def search(self, provider: str, account_id: str, query: str,
               limit: int = 100) -> list[dict]:
        needle = query.strip().upper()
        if not needle:
            return []
        rows = self.db.execute("""
            SELECT * FROM market_instruments
            WHERE provider=? AND account_id=? AND (symbol LIKE ? OR underlying_symbol LIKE ?)
            ORDER BY CASE WHEN symbol=? OR underlying_symbol=? THEN 0 ELSE 1 END, expiry, strike
            LIMIT ?
        """, (provider.lower(), account_id, f"%{needle}%", f"%{needle}%", needle, needle,
              max(1, min(limit, 500)))).fetchall()
        return [dict(row) for row in rows]

    def list_all(self, provider: str | None = None, account_id: str | None = None,
                 limit: int = 500) -> list[dict]:
        clauses, params = [], []
        if provider:
            clauses.append("provider=?")
            params.append(provider.lower())
        if account_id:
            clauses.append("account_id=?")
            params.append(account_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.execute(
            "SELECT * FROM market_instruments" + where +
            " ORDER BY provider,account_id,symbol,expiry,strike LIMIT ?",
            (*params, max(1, min(limit, 50000))),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, provider: str, account_id: str, token: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "DELETE FROM market_instruments WHERE provider=? AND account_id=? AND token=?",
                (provider.lower(), account_id, token),
            )
        return cursor.rowcount > 0

    def close(self) -> None:
        self.db.close()


    def lot_size_as_of(self, provider: str, account_id: str, *, symbol: str,
                       expiry: str | None, strike: str | None,
                       option_type: str | None, as_of: str) -> dict | None:
        row = self.db.execute("""
            SELECT * FROM market_instrument_lot_size_history
            WHERE provider=? AND account_id=? AND upper(symbol)=? AND expiry=?
              AND strike=? AND upper(option_type)=? AND effective_date<=?
              AND lot_size IS NOT NULL AND lot_size>0
            ORDER BY effective_date DESC LIMIT 1
        """, (provider.lower(), account_id, symbol.upper(), expiry, strike,
              (option_type or "").upper(), as_of[:10])).fetchone()
        return dict(row) if row else None

    def upsert_sector(self, *, exchange: str, symbol: str, sector: str,
                      effective_from: str, source: str,
                      source_reference: str | None = None,
                      effective_through: str | None = None) -> dict:
        exchange, symbol, sector = exchange.strip().upper(), symbol.strip().upper(), sector.strip()
        if not all((exchange, symbol, sector, source.strip())):
            raise ValueError("Exchange, symbol, sector and source are required")
        start = date.fromisoformat(effective_from).isoformat()
        end = date.fromisoformat(effective_through).isoformat() if effective_through else None
        if end and end < start:
            raise ValueError("effective_through cannot precede effective_from")
        verified = datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.execute("""
                INSERT INTO market_equity_sector_history(
                    exchange,symbol,sector,effective_from,effective_through,
                    source,source_reference,verified_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(exchange,symbol,effective_from) DO UPDATE SET
                    sector=excluded.sector,effective_through=excluded.effective_through,
                    source=excluded.source,source_reference=excluded.source_reference,
                    verified_at=excluded.verified_at
            """, (exchange, symbol, sector, start, end, source.strip(), source_reference, verified))
        return self.sector_as_of(exchange, symbol, start) or {}

    def sector_as_of(self, exchange: str, symbol: str, as_of: str) -> dict | None:
        row = self.db.execute("""
            SELECT * FROM market_equity_sector_history
            WHERE exchange=? AND upper(symbol)=? AND effective_from<=?
              AND (effective_through IS NULL OR effective_through>=?)
            ORDER BY effective_from DESC LIMIT 1
        """, (exchange.upper(), symbol.upper(), as_of[:10], as_of[:10])).fetchone()
        return dict(row) if row else None
