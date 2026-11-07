"""Persistent, independent historical/live market-data source selection.

Provider capability flags describe adapters actually wired into AIR today; a broker
being present in the broker catalog does not imply its market-data adapter is ready.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


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
        "adapter_ready": {"historical": False, "live": False},
        "data_scope": "Broker integration catalog entry; market-data adapter pending",
        "requires_account": True,
    },
    {
        "code": "upstox",
        "name": "Upstox API",
        "kind": "broker",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": False, "live": False},
        "data_scope": "Broker integration catalog entry; market-data adapter pending",
        "requires_account": True,
    },
    {
        "code": "fyers",
        "name": "FYERS API",
        "kind": "broker",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": False, "live": False},
        "data_scope": "Broker integration catalog entry; market-data adapter pending",
        "requires_account": True,
    },
    {
        "code": "angelone",
        "name": "Angel One SmartAPI",
        "kind": "broker",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": False, "live": False},
        "data_scope": "Broker integration catalog entry; market-data adapter pending",
        "requires_account": True,
    },
    {
        "code": "custom_vendor",
        "name": "External Market-Data Vendor (adapter extension)",
        "kind": "vendor",
        "channels": ["historical", "live"],
        "adapter_ready": {"historical": False, "live": False},
        "data_scope": "Vendor-neutral adapter contract; vendor-specific adapter and credentials required",
        "requires_account": True,
    },
)

CHANNELS = ("historical", "live")


class MarketDataSourceRegistry:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv(
            "AIR_MARKET_SOURCE_DB_PATH", "data/air_market_sources.sqlite3"
        )
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS market_data_sources (
                channel TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                account_id TEXT,
                enabled INTEGER NOT NULL DEFAULT 0,
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
            "SELECT channel, provider, account_id, enabled, updated_at FROM market_data_sources"
        ).fetchall()
        values = {row["channel"]: {
            "provider": row["provider"], "account_id": row["account_id"],
            "enabled": bool(row["enabled"]), "updated_at": row["updated_at"],
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
        """, (channel, provider, account_id, int(enabled)))
        self.db.commit()
        return self.selections()[channel] or {}

    def close(self) -> None:
        self.db.close()
