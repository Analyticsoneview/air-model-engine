"""Persistent provider-specific instrument token directory.

Broker instrument tokens are not interchangeable. Admins can import/maintain the
mapping obtained from each broker's official instrument master.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


class MarketInstrumentDirectory:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv(
            "AIR_MARKET_INSTRUMENT_DB_PATH", "data/air_market_instruments.sqlite3"
        )
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS market_instruments (
                provider TEXT NOT NULL,
                account_id TEXT NOT NULL,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                token TEXT NOT NULL,
                segment TEXT NOT NULL,
                expiry TEXT,
                strike TEXT,
                option_type TEXT,
                lot_size INTEGER,
                instrument_type TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(provider, account_id, token)
            )
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_instruments_symbol
            ON market_instruments(provider, account_id, symbol)
        """)
        self.db.commit()

    def upsert(self, provider: str, account_id: str, *, exchange: str,
               symbol: str, token: str, segment: str, expiry: str | None = None,
               strike: str | None = None, option_type: str | None = None,
               lot_size: int | None = None, instrument_type: str | None = None) -> dict:
        values = [provider.strip().lower(), account_id.strip(), exchange.strip().upper(),
                  symbol.strip().upper(), token.strip(), segment.strip().upper()]
        if not all(values):
            raise ValueError("Provider, account, exchange, symbol, token and segment are required")
        with self.db:
            self.db.execute("""
                INSERT INTO market_instruments(
                    provider,account_id,exchange,symbol,token,segment,expiry,strike,
                    option_type,lot_size,instrument_type,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(provider,account_id,token) DO UPDATE SET
                    exchange=excluded.exchange,symbol=excluded.symbol,segment=excluded.segment,
                    expiry=excluded.expiry,strike=excluded.strike,option_type=excluded.option_type,
                    lot_size=excluded.lot_size,instrument_type=excluded.instrument_type,
                    updated_at=CURRENT_TIMESTAMP
            """, (*values, expiry, strike, option_type, lot_size, instrument_type))
        return self.get(provider, account_id, values[4]) or {}

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
            WHERE provider=? AND account_id=? AND symbol LIKE ?
            ORDER BY CASE WHEN symbol=? THEN 0 ELSE 1 END, expiry, strike
            LIMIT ?
        """, (provider.lower(), account_id, f"%{needle}%", needle, max(1, min(limit, 500)))).fetchall()
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
            (*params, max(1, min(limit, 2000))),
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
