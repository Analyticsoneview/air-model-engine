"""Customer-isolated portfolio snapshots and evidence-backed risk analytics.

Broker data is read-only. Missing capital, sector, valuation or price fields remain
unavailable; the service never invents returns, equity or drawdown.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db_compat import PostgresConnection, read_database_url


def _first(row: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [dict(x) for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "netPositions", "net", "positions", "holdings", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(x) for x in value if isinstance(x, dict)]
            if isinstance(value, dict):
                nested = _rows(value)
                if nested:
                    return nested
        return [payload]
    return []


def _normalize_instrument(row: dict, kind: str) -> dict:
    quantity = _number(_first(row, ("netQty", "net_quantity", "quantity", "qty", "netqty", "sellQty")))
    average = _number(_first(row, ("buyAvg", "average_price", "avg_price", "cost_price", "buy_price", "avgCostPrice")))
    ltp = _number(_first(row, ("ltp", "last_price", "lastPrice", "market_price", "close", "price")))
    explicit_value = _number(_first(row, ("market_value", "marketValue", "current_value", "currentValue", "value")))
    invested = _number(_first(row, ("invested_value", "cost_value", "buy_value", "costValue")))
    if invested is None and quantity is not None and average is not None:
        invested = abs(quantity) * average
    market_value = explicit_value
    if market_value is None and quantity is not None and ltp is not None:
        market_value = abs(quantity) * ltp
    pnl = _number(_first(row, ("unrealizedProfit", "unrealized_pnl", "pnl", "profit", "pl", "mtm")))
    realized = _number(_first(row, ("realizedProfit", "realized_profit", "realized_pnl", "realisedProfit", "realised_profit")))
    day_pnl = _number(_first(row, ("dayProfit", "day_pnl", "dayPnL", "day_pnl_rupees")))
    if pnl is None and market_value is not None and invested is not None:
        pnl = market_value - invested
    symbol = _first(row, ("tradingSymbol", "tradingsymbol", "symbol", "trading_symbol", "securityName", "scripName"))
    side = str(_first(row, ("transactionType", "side", "position_type", "productType")) or "").upper()
    signed_value = market_value
    if signed_value is not None and quantity is not None and quantity < 0:
        signed_value = -signed_value
    return {
        "kind": kind,
        "symbol": str(symbol).strip().upper() if symbol else "UNKNOWN",
        "exchange": _first(row, ("exchange", "exchangeSegment", "segment")),
        "product": _first(row, ("productType", "product", "product_type")),
        "sector": _first(row, ("sector", "industry")),
        "side": side or ("SHORT" if quantity is not None and quantity < 0 else "LONG"),
        "quantity": quantity,
        "average_price": average,
        "last_price": ltp,
        "market_value": round(market_value, 2) if market_value is not None else None,
        "invested_value": round(invested, 2) if invested is not None else None,
        "pnl": round(pnl, 2) if pnl is not None else None,
        "realized_pnl": round(realized, 2) if realized is not None else None,
        "day_pnl": round(day_pnl, 2) if day_pnl is not None else None,
        "signed_exposure": round(signed_value, 2) if signed_value is not None else None,
        "raw": row,
    }


def build_portfolio_snapshot(payload: dict, broker: str, account_id: str) -> dict:
    positions = [_normalize_instrument(row, "POSITION") for row in _rows(payload.get("positions"))]
    holdings = [_normalize_instrument(row, "HOLDING") for row in _rows(payload.get("holdings"))]
    instruments = positions + holdings
    def total(key: str) -> float | None:
        values = [item[key] for item in instruments if item.get(key) is not None]
        return round(sum(values), 2) if values else None
    gross = total("market_value")
    signed = total("signed_exposure")
    invested = total("invested_value")
    pnl = total("pnl")
    realized_values = [item["realized_pnl"] for item in instruments if item.get("realized_pnl") is not None]
    day_values = [item["day_pnl"] for item in instruments if item.get("day_pnl") is not None]
    explicit_realized = _number(payload.get("realized_pnl"))
    explicit_day = _number(payload.get("day_pnl"))
    if explicit_realized is None and realized_values:
        explicit_realized = round(sum(realized_values), 2)
    if explicit_day is None and day_values:
        explicit_day = round(sum(day_values), 2)
    explicit_equity = _number(_first(payload, ("net_liquidation", "netLiquidation", "equity", "account_value")))
    capital = _number(_first(payload, ("capital_base", "opening_balance", "available_capital")))
    pnl_pct = round((pnl / invested) * 100, 2) if pnl is not None and invested not in (None, 0) else None
    by_symbol: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    for item in instruments:
        value = item.get("market_value")
        if value is None:
            continue
        by_symbol[item["symbol"]] = by_symbol.get(item["symbol"], 0.0) + value
        sector = item.get("sector")
        if sector:
            by_sector[str(sector)] = by_sector.get(str(sector), 0.0) + value
    concentration = round(max(by_symbol.values()) / gross * 100, 2) if gross and by_symbol else None
    sector_exposure = [
        {"sector": key, "market_value": round(value, 2),
         "exposure_pct": round(value / gross * 100, 2) if gross else None}
        for key, value in sorted(by_sector.items(), key=lambda x: abs(x[1]), reverse=True)
    ]
    missing = []
    if gross is None: missing.append("market_value")
    if invested is None: missing.append("invested_value")
    if explicit_equity is None: missing.append("account_equity")
    if not any(x.get("sector") for x in instruments): missing.append("sector_classification")
    if pnl is None: missing.append("pnl")
    return {
        "broker": broker, "account_id": account_id,
        "captured_at": str(payload.get("fetched_at") or datetime.now(timezone.utc).isoformat()),
        "positions": positions, "holdings": holdings,
        "summary": {
            "position_count": len(positions), "holding_count": len(holdings),
            "gross_market_value": gross, "net_exposure": signed,
            "invested_value": invested, "unrealized_pnl": pnl,
            "realized_pnl": explicit_realized, "day_pnl": explicit_day,
            "return_pct_on_observed_invested_value": pnl_pct,
            "account_equity": explicit_equity, "capital_base": capital,
            "concentration_top_position_pct": concentration,
            "leverage_on_known_capital": round(gross / capital, 3) if gross is not None and capital else None,
            "sector_exposure": sector_exposure,
            "max_drawdown_pct": None,
            "drawdown_status": "INSUFFICIENT_EQUITY_HISTORY",
            "data_quality": "COMPLETE" if not missing else "PARTIAL",
            "missing_fields": missing,
        },
    }


class PortfolioRiskStore:
    def __init__(self, db_path: str | None = None):
        url = read_database_url("AIR_PORTFOLIO_DATABASE_URL") or read_database_url("AIR_CUSTOMER_DATABASE_URL") or read_database_url("AIR_DATABASE_URL")
        if url:
            self.db = PostgresConnection(url)
            self.is_postgres = True
            try:
                self.db.execute("SELECT 1 FROM air_portfolio_snapshots LIMIT 0")
            except Exception as exc:
                self.db.close()
                raise RuntimeError("Portfolio PostgreSQL schema is missing; apply Alembic migrations first") from exc
        else:
            path = db_path or os.getenv("AIR_PORTFOLIO_DB_PATH", "data/air_portfolio.sqlite3")
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=30000")
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS air_portfolio_snapshots (
                    snapshot_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
                    broker TEXT NOT NULL, account_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL, summary_json TEXT NOT NULL,
                    positions_json TEXT NOT NULL, holdings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.db.execute("""CREATE INDEX IF NOT EXISTS idx_air_portfolio_customer_time
                ON air_portfolio_snapshots(customer_id,captured_at DESC)""")
            self.db.commit()

    def save(self, customer_id: str, snapshot: dict) -> str:
        snapshot_id = str(uuid4())
        with self.db:
            self.db.execute("""INSERT INTO air_portfolio_snapshots
                (snapshot_id,customer_id,broker,account_id,captured_at,summary_json,positions_json,holdings_json)
                VALUES(?,?,?,?,?,?,?,?)""", (
                snapshot_id, customer_id, snapshot["broker"], snapshot["account_id"],
                snapshot["captured_at"], json.dumps(snapshot["summary"], default=str),
                json.dumps(snapshot["positions"], default=str), json.dumps(snapshot["holdings"], default=str),
            ))
        return snapshot_id

    def _decode(self, row: Any) -> dict:
        return {
            "snapshot_id": row["snapshot_id"], "broker": row["broker"],
            "account_id": row["account_id"], "captured_at": row["captured_at"],
            "summary": json.loads(row["summary_json"]),
            "positions": json.loads(row["positions_json"]),
            "holdings": json.loads(row["holdings_json"]),
        }

    def latest(self, customer_id: str) -> list[dict]:
        rows = self.db.execute("""SELECT * FROM air_portfolio_snapshots
            WHERE customer_id=? ORDER BY captured_at DESC,created_at DESC""", (customer_id,)).fetchall()
        latest_by_account = {}
        for row in rows:
            key = (row["broker"], row["account_id"])
            latest_by_account.setdefault(key, self._decode(row))
        return list(latest_by_account.values())

    def history(self, customer_id: str, limit: int = 100) -> list[dict]:
        rows = self.db.execute("""SELECT snapshot_id,broker,account_id,captured_at,summary_json
            FROM air_portfolio_snapshots WHERE customer_id=?
            ORDER BY captured_at DESC,created_at DESC LIMIT ?""",
            (customer_id, max(1, min(limit, 500)))).fetchall()
        return [{
            "snapshot_id": row["snapshot_id"], "broker": row["broker"],
            "account_id": row["account_id"], "captured_at": row["captured_at"],
            "summary": json.loads(row["summary_json"]),
        } for row in rows]

    def overview(self, customer_id: str) -> dict:
        accounts = self.latest(customer_id)
        summaries = [item["summary"] for item in accounts]
        def aggregate(key: str) -> float | None:
            values = [s[key] for s in summaries if isinstance(s.get(key), (int, float))]
            return round(sum(values), 2) if values else None
        equity_points = [s["account_equity"] for s in summaries if isinstance(s.get("account_equity"), (int, float))]
        return {
            "accounts": accounts,
            "account_count": len(accounts),
            "summary": {
                "position_count": sum(int(s.get("position_count") or 0) for s in summaries),
                "holding_count": sum(int(s.get("holding_count") or 0) for s in summaries),
                "gross_market_value": aggregate("gross_market_value"),
                "net_exposure": aggregate("net_exposure"),
                "invested_value": aggregate("invested_value"),
                "unrealized_pnl": aggregate("unrealized_pnl"),
                "realized_pnl": aggregate("realized_pnl"),
                "day_pnl": aggregate("day_pnl"),
                "account_equity": aggregate("account_equity"),
                "return_pct_on_observed_invested_value": None,
                "max_drawdown_pct": None,
                "drawdown_status": "INSUFFICIENT_EQUITY_HISTORY",
                "data_quality": "NO_SNAPSHOTS" if not accounts else (
                    "COMPLETE" if all(s.get("data_quality") == "COMPLETE" for s in summaries) else "PARTIAL"
                ),
                "risk_note": "Returns and drawdown require a verified capital/equity time series. No estimate is substituted.",
            },
            "as_of": max((a["captured_at"] for a in accounts), default=None),
            "history": self.history(customer_id, 100),
        }

    def close(self) -> None:
        self.db.close()
