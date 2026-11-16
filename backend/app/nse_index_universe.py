"""Versioned NSE Indices constituent registry for AIR MPDSM stock universe.

Constituents are sourced only from NSE Indices published CSV files. A failed,
empty, malformed or wrong-sized list fails closed; no inferred membership.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

INDEX_SOURCES = {
    "NIFTY100": {
        "expected_count": 100,
        "url": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    },
    "NIFTY_MIDCAP150": {
        "expected_count": 150,
        "url": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    },
    "NIFTY_SMALLCAP250": {
        "expected_count": 250,
        "url": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    },
}


def parse_constituents(csv_text: str, index_code: str) -> list[dict[str, str]]:
    if index_code not in INDEX_SOURCES:
        raise ValueError(f"Unsupported index: {index_code}")
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("NSE constituent CSV has no header")
    normalized_headers = {str(name).strip().lower(): name for name in reader.fieldnames}
    symbol_key = normalized_headers.get("symbol")
    company_key = normalized_headers.get("company name") or normalized_headers.get("company")
    isin_key = normalized_headers.get("isin code") or normalized_headers.get("isin")
    if not symbol_key:
        raise ValueError("NSE constituent CSV is missing Symbol column")
    records: dict[str, dict[str, str]] = {}
    for row in reader:
        symbol = str(row.get(symbol_key) or "").strip().upper()
        if not symbol:
            continue
        if symbol in records:
            raise ValueError(f"Duplicate constituent symbol: {symbol}")
        records[symbol] = {
            "symbol": symbol,
            "company_name": str(row.get(company_key) or "").strip() if company_key else "",
            "isin": str(row.get(isin_key) or "").strip().upper() if isin_key else "",
            "index_code": index_code,
        }
    expected = INDEX_SOURCES[index_code]["expected_count"]
    if len(records) != expected:
        raise ValueError(f"{index_code} expected {expected} constituents, received {len(records)}")
    return [records[symbol] for symbol in sorted(records)]


class NSEIndexUniverseStore:
    """Persist immutable, versioned constituent snapshots in the NSE EOD database."""

    def __init__(self, path: str = "data/nse_bhavcopy.sqlite3"):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS nse_index_constituents (
                    snapshot_id TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    index_code TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    company_name TEXT,
                    isin TEXT,
                    source_url TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id, index_code, symbol)
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS ix_nse_index_constituents_symbol
                ON nse_index_constituents(symbol, retrieved_at)
            """)

    def save_snapshot(self, index_code: str, records: list[dict[str, str]],
                      retrieved_at: str, source_url: str) -> int:
        expected = INDEX_SOURCES[index_code]["expected_count"]
        if len(records) != expected:
            raise ValueError(f"{index_code} snapshot is incomplete")
        snapshot_id = f"{index_code}:{retrieved_at}"
        with sqlite3.connect(self.path) as db:
            db.executemany("""
                INSERT OR IGNORE INTO nse_index_constituents
                (snapshot_id,retrieved_at,index_code,symbol,company_name,isin,source_url)
                VALUES (?,?,?,?,?,?,?)
            """, [(snapshot_id, retrieved_at, index_code, row["symbol"],
                   row.get("company_name", ""), row.get("isin", ""), source_url)
                  for row in records])
        return len(records)

    def latest_universe(self) -> dict[str, Any]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            latest = db.execute("""
                SELECT index_code, MAX(retrieved_at) AS retrieved_at
                FROM nse_index_constituents GROUP BY index_code
            """).fetchall()
            if {row["index_code"] for row in latest} != set(INDEX_SOURCES):
                return {"status": "DATA_INSUFFICIENT", "reason": "One or more official index snapshots are missing",
                        "index_counts": {}, "constituents": []}
            members: dict[str, dict[str, Any]] = {}
            counts = {}
            for item in latest:
                rows = db.execute("""
                    SELECT symbol,company_name,isin,index_code,retrieved_at,source_url
                    FROM nse_index_constituents
                    WHERE index_code=? AND retrieved_at=? ORDER BY symbol
                """, (item["index_code"], item["retrieved_at"])).fetchall()
                expected = INDEX_SOURCES[item["index_code"]]["expected_count"]
                if len(rows) != expected:
                    return {"status": "DATA_INSUFFICIENT",
                            "reason": f"{item['index_code']} snapshot count mismatch",
                            "index_counts": counts, "constituents": []}
                counts[item["index_code"]] = len(rows)
                for row in rows:
                    entry = members.setdefault(row["symbol"], {
                        "symbol": row["symbol"], "company_name": row["company_name"],
                        "isin": row["isin"], "index_memberships": [], "retrieved_at": {},
                    })
                    entry["index_memberships"].append(row["index_code"])
                    entry["retrieved_at"][row["index_code"]] = row["retrieved_at"]
            return {"status": "READY", "source": "NSE Indices official constituent CSV",
                    "index_counts": counts, "unique_symbol_count": len(members),
                    "constituents": [members[key] for key in sorted(members)]}


async def refresh_nse_index_universe(store: NSEIndexUniverseStore) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 AIR research data client",
        "Accept": "text/csv,*/*",
        "Referer": "https://www.niftyindices.com/",
    }
    retrieved_at = datetime.now(timezone.utc).isoformat()
    results = {}
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30.0),
                                 follow_redirects=True) as client:
        for index_code, config in INDEX_SOURCES.items():
            response = await client.get(config["url"])
            response.raise_for_status()
            records = parse_constituents(response.text, index_code)
            count = store.save_snapshot(index_code, records, retrieved_at, config["url"])
            results[index_code] = {"status": "IMPORTED", "count": count,
                                   "source_url": config["url"], "retrieved_at": retrieved_at}
    universe = store.latest_universe()
    if universe["status"] != "READY":
        raise RuntimeError("NSE constituent registry failed completeness validation")
    return {"status": "READY", "snapshots": results,
            "index_counts": universe["index_counts"],
            "unique_symbol_count": universe["unique_symbol_count"],
            "source": universe["source"]}
