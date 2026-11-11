"""Private SQLite store for normalized AIR QOC option-chain observations.

Raw provider payloads are deliberately not stored. Records are scoped by
provider/account/underlying/expiry and carry their market observation timestamp.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from app.db_compat import PostgresConnection, read_database_url
from typing import Any


class AirQocStore:
    def __init__(self, db_path: str | None = None):
        database_url = read_database_url("AIR_QOC_DATABASE_URL") if db_path is None else None
        self._is_postgres = database_url is not None
        if self._is_postgres:
            self.db_path = None
            self.db = PostgresConnection(database_url)
            try:
                self.db.execute("SELECT 1 FROM option_observations LIMIT 0")
            except Exception as exc:
                self.db.close()
                raise RuntimeError("PostgreSQL QOC schema is missing; run Alembic migrations first") from exc
        else:
            self.db_path = db_path or os.getenv("AIR_QOC_DB_PATH", "data/air_qoc.sqlite3")
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.db_path, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS option_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                account_id TEXT NOT NULL,
                underlying_scrip INTEGER NOT NULL,
                underlying_segment TEXT NOT NULL,
                expiry TEXT NOT NULL,
                underlying_price REAL,
                strike TEXT NOT NULL,
                option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
                security_id TEXT,
                last_price REAL,
                previous_close REAL,
                volume INTEGER,
                previous_volume INTEGER,
                open_interest INTEGER,
                previous_oi INTEGER,
                bid_price REAL,
                bid_quantity INTEGER,
                ask_price REAL,
                ask_quantity INTEGER,
                implied_volatility REAL,
                observed_at TEXT NOT NULL,
                UNIQUE(provider, account_id, underlying_scrip, expiry, strike, option_type, observed_at)
            )
        """)
        if not self._is_postgres:
            columns = {row["name"] for row in self.db.execute("PRAGMA table_info(option_observations)").fetchall()}
            if "underlying_price" not in columns:
                self.db.execute("ALTER TABLE option_observations ADD COLUMN underlying_price REAL")
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_qoc_latest
            ON option_observations(provider, account_id, underlying_scrip, expiry, observed_at DESC)
        """)
        self.db.commit()

    def save_option_chain(self, *, account_id: str, underlying_scrip: int,
                          underlying_segment: str, expiry: str,
                          underlying_price: float | None,
                          observed_at: str, chain: dict[str, Any],
                          provider: str = "dhan") -> int:
        rows = []
        for strike, sides in (chain.get("oc") or {}).items():
            if not isinstance(sides, dict):
                continue
            for side_key, option_type in (("ce", "CE"), ("pe", "PE")):
                item = sides.get(side_key)
                if not isinstance(item, dict):
                    continue
                greeks = item.get("greeks") or {}
                rows.append((
                    provider, account_id, underlying_scrip, underlying_segment, expiry,
                    underlying_price, str(strike), option_type, str(item.get("security_id") or ""),
                    _number(item.get("last_price")), _number(item.get("previous_close_price")),
                    _integer(item.get("volume")), _integer(item.get("previous_volume")),
                    _integer(item.get("oi")), _integer(item.get("previous_oi")),
                    _number(item.get("top_bid_price")), _integer(item.get("top_bid_quantity")),
                    _number(item.get("top_ask_price")), _integer(item.get("top_ask_quantity")),
                    _number(item.get("implied_volatility")), observed_at,
                ))
        with self.db:
            self.db.executemany("""
                INSERT INTO option_observations (
                    provider,account_id,underlying_scrip,underlying_segment,expiry,
                    underlying_price,strike,option_type,security_id,last_price,previous_close,volume,
                    previous_volume,open_interest,previous_oi,bid_price,bid_quantity,
                    ask_price,ask_quantity,implied_volatility,observed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(provider, account_id, underlying_scrip, expiry, strike, option_type, observed_at)
                DO UPDATE SET
                    underlying_segment=excluded.underlying_segment,
                    underlying_price=excluded.underlying_price,
                    security_id=excluded.security_id,
                    last_price=excluded.last_price,
                    previous_close=excluded.previous_close,
                    volume=excluded.volume,
                    previous_volume=excluded.previous_volume,
                    open_interest=excluded.open_interest,
                    previous_oi=excluded.previous_oi,
                    bid_price=excluded.bid_price,
                    bid_quantity=excluded.bid_quantity,
                    ask_price=excluded.ask_price,
                    ask_quantity=excluded.ask_quantity,
                    implied_volatility=excluded.implied_volatility
            """, rows)
        return len(rows)

    def latest_observations(self, *, account_id: str, provider: str = "dhan",
                            limit: int = 500) -> list[dict[str, Any]]:
        rows = self.db.execute("""
            SELECT * FROM option_observations
            WHERE provider=? AND account_id=?
            ORDER BY observed_at DESC, underlying_scrip, expiry, strike, option_type
            LIMIT ?
        """, (provider, account_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.db.close()


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
