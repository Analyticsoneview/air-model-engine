"""Persistent, independent historical/live market-data source selection.

Provider capability flags describe adapters actually wired into AIR today; a broker
being present in the broker catalog does not imply its market-data adapter is ready.
"""
from __future__ import annotations

import os
import sqlite3
import json
from pathlib import Path
from typing import Any

from app.db_compat import PostgresConnection, read_database_url


PROVIDER_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "code": "nse_bhavcopy",
        "name": "NSE Official CM/FO Bhavcopy",
        "kind": "exchange",
        "channels": ["historical"],
        "adapter_ready": {"historical": True, "live": False},
        "data_scope": "Official EOD CM/FO daily OHLCV, OI and settlement fields; not intraday ticks",
        "requires_account": False,
    },
    {
        "code": "dhan",
        "name": "DhanHQ",
        "kind": "broker",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": True, "live": True, "option_chain": True},
        "data_scope": "Historical candles, live market feed and Dhan option-chain snapshots",
        "requires_account": True,
    },
    {
        "code": "zerodha",
        "name": "Zerodha Kite Connect",
        "kind": "broker",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": True, "live": True},
        "data_scope": "Historical REST candles and native broker WebSocket streaming with automatic reconnect",
        "requires_account": True,
    },
    {
        "code": "upstox",
        "name": "Upstox API",
        "kind": "broker",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": True, "live": True},
        "data_scope": "Historical REST candles and native broker WebSocket streaming with automatic reconnect",
        "requires_account": True,
    },
    {
        "code": "fyers",
        "name": "FYERS API",
        "kind": "broker",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": True, "live": True},
        "data_scope": "Historical REST candles and native broker WebSocket streaming with automatic reconnect",
        "requires_account": True,
    },
    {
        "code": "angelone",
        "name": "Angel One SmartAPI",
        "kind": "broker",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": True, "live": True},
        "data_scope": "Historical REST candles and native broker WebSocket streaming with automatic reconnect",
        "requires_account": True,
    },
    {
        "code": "custom_vendor",
        "name": "External Market-Data Vendor (adapter extension)",
        "kind": "vendor",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": True, "live": True},
        "data_scope": "AIR JSON vendor contract: HTTPS historical/instrument REST and native JSON WebSocket live feed; vendor-specific schema adapter may still be required",
        "requires_account": True,
    },
)

CHANNELS = ("historical", "live")


class MarketDataSourceRegistry:
    def __init__(self, db_path: str | None = None) -> None:
        database_url = read_database_url("AIR_MARKET_SOURCE_DATABASE_URL") if db_path is None else None
        self._is_postgres = database_url is not None
        if self._is_postgres:
            self.db_path = None
            self.db = PostgresConnection(database_url)
            try:
                self.db.execute("SELECT 1 FROM market_data_sources LIMIT 0")
                self.db.execute("SELECT 1 FROM market_data_failover LIMIT 0")
            except Exception as exc:
                self.db.close()
                raise RuntimeError("PostgreSQL market-data source schema is missing; run Alembic migrations first") from exc
        else:
            self.db_path = db_path or os.getenv(
                "AIR_MARKET_SOURCE_DB_PATH", "data/air_market_sources.sqlite3"
            )
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA busy_timeout=30000")
        if not self._is_postgres:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS market_data_sources (
                    channel TEXT PRIMARY KEY, provider TEXT NOT NULL, account_id TEXT,
                    enabled INTEGER NOT NULL DEFAULT 0, fallback_provider TEXT,
                    fallback_account_id TEXT, failover_enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            columns = {row["name"] for row in self.db.execute("PRAGMA table_info(market_data_sources)")}
            for name, declaration in (
                ("fallback_provider", "TEXT"),
                ("fallback_account_id", "TEXT"),
                ("failover_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    self.db.execute(f"ALTER TABLE market_data_sources ADD COLUMN {name} {declaration}")
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS market_data_failover (
                    channel TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    candidates_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.db.commit()

    @staticmethod
    def catalog() -> list[dict[str, Any]]:
        return [dict(item, adapter_ready=dict(item["adapter_ready"]),
                     channels=list(item["channels"])) for item in PROVIDER_CATALOG]

    def selections(self) -> dict[str, dict[str, Any] | None]:
        rows = self.db.execute(
            "SELECT channel, provider, account_id, enabled, fallback_provider, "
            "fallback_account_id, failover_enabled, updated_at FROM market_data_sources"
        ).fetchall()
        values = {row["channel"]: {
            "provider": row["provider"], "account_id": row["account_id"],
            "enabled": bool(row["enabled"]),
            "fallback_provider": row["fallback_provider"],
            "fallback_account_id": row["fallback_account_id"],
            "failover_enabled": bool(row["failover_enabled"]),
            "updated_at": row["updated_at"],
        } for row in rows}
        return {channel: values.get(channel) for channel in CHANNELS}

    def set_source(self, channel: str, provider: str, account_id: str | None,
                   enabled: bool) -> dict[str, Any]:
        if channel not in CHANNELS:
            raise ValueError("Unsupported data channel")
        definition = next((item for item in PROVIDER_CATALOG if item["code"] == provider), None)
        if definition is None or channel not in definition["channels"]:
            raise ValueError("Provider does not support the requested data channel")
        if enabled and not definition["adapter_ready"].get(channel, False):
            raise ValueError("Provider adapter is not implemented and verified for this channel")
        if enabled and definition["requires_account"] and not (account_id or "").strip():
            raise ValueError("A provider account ID is required")
        if not definition["requires_account"]:
            account_id = None
        self.db.execute("""
            INSERT INTO market_data_sources(channel, provider, account_id, enabled, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(channel) DO UPDATE SET
                provider=excluded.provider, account_id=excluded.account_id,
                enabled=excluded.enabled, updated_at=CURRENT_TIMESTAMP
        """, (channel, provider, account_id, bool(enabled)))
        self.db.commit()
        return self.selections()[channel] or {}

    def set_failover(self, channel: str, candidates: list[dict[str, str]], enabled: bool) -> dict[str, Any]:
        if channel not in CHANNELS:
            raise ValueError("Unsupported data channel")
        normalized = []
        for item in candidates:
            provider = str(item.get("provider", "")).strip().lower()
            account_id = str(item.get("account_id", "")).strip()
            if not provider or not account_id:
                raise ValueError("Failover candidates require provider and account_id")
            normalized.append({"provider": provider, "account_id": account_id})
        self.db.execute("""
            INSERT INTO market_data_failover(channel,enabled,candidates_json,updated_at)
            VALUES(?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(channel) DO UPDATE SET enabled=excluded.enabled,
                candidates_json=excluded.candidates_json,updated_at=CURRENT_TIMESTAMP
        """, (channel, bool(enabled), json.dumps(normalized)))
        self.db.commit()
        return self.failover()[channel]

    def failover(self) -> dict[str, dict[str, Any]]:
        rows = self.db.execute(
            "SELECT channel,enabled,candidates_json,updated_at FROM market_data_failover"
        ).fetchall()
        result = {channel: {"enabled": False, "candidates": []} for channel in CHANNELS}
        for row in rows:
            result[row["channel"]] = {
                "enabled": bool(row["enabled"]),
                "candidates": json.loads(row["candidates_json"] or "[]"),
                "updated_at": row["updated_at"],
            }
        return result

    def close(self) -> None:
        self.db.close()
