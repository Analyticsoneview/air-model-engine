"""Official NSE index-universe snapshot bootstrap for AIR research.

The three required universes are downloaded from NSE's published constituent
CSV files. A snapshot is stored only after the exact expected unique-symbol
count has been validated; a failed refresh never overwrites the last good
snapshot.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("air.nse.universe")
IST = ZoneInfo("Asia/Kolkata")

INDEX_UNIVERSES: dict[str, dict[str, Any]] = {
    "NIFTY100": {
        "name": "Nifty 100",
        "expected_count": 100,
        "urls": (
            "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
            "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
        ),
    },
    "NIFTYMIDCAP150": {
        "name": "Nifty Midcap 150",
        "expected_count": 150,
        "urls": (
            "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
            "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
        ),
    },
    "NIFTYSMALLCAP250": {
        "name": "Nifty Smallcap 250",
        "expected_count": 250,
        "urls": (
            "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
            "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
        ),
    },
}


def _header_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").strip().upper())


def parse_index_constituents(csv_text: str, index_code: str) -> list[dict[str, str]]:
    """Parse and validate an official constituent CSV against its expected size."""
    if index_code not in INDEX_UNIVERSES:
        raise ValueError(f"Unsupported AIR index universe: {index_code}")
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError(f"{index_code} CSV has no header")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in reader:
        normalized = {_header_key(k): str(v or "").strip() for k, v in raw.items()}
        symbol = (normalized.get("SYMBOL") or normalized.get("TICKERSYMBOL") or "").upper()
        if not symbol:
            continue
        if symbol in seen:
            raise ValueError(f"{index_code} CSV contains duplicate symbol {symbol}")
        seen.add(symbol)
        rows.append({
            "symbol": symbol,
            "company_name": normalized.get("COMPANYNAME") or normalized.get("COMPANY") or "",
            "industry": normalized.get("INDUSTRY") or normalized.get("SECTOR") or "",
            "series": normalized.get("SERIES") or "",
            "isin": normalized.get("ISINCODE") or normalized.get("ISIN") or "",
        })
    expected = int(INDEX_UNIVERSES[index_code]["expected_count"])
    if len(rows) != expected:
        raise ValueError(
            f"{index_code} expected {expected} unique symbols; received {len(rows)}"
        )
    return rows


class NSEUniverseStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("AIR_NSE_UNIVERSE_DB_PATH", "data/nse_universe.sqlite3")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _init(self) -> None:
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS nse_index_constituent_snapshots (
                    index_code TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    company_name TEXT NOT NULL DEFAULT '',
                    industry TEXT NOT NULL DEFAULT '',
                    series TEXT NOT NULL DEFAULT '',
                    isin TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL,
                    PRIMARY KEY(index_code, snapshot_date, symbol)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS nse_index_universe_status (
                    index_code TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    expected_count INTEGER NOT NULL,
                    actual_count INTEGER NOT NULL DEFAULT 0,
                    snapshot_date TEXT,
                    source_url TEXT,
                    error TEXT,
                    last_attempt_status TEXT,
                    last_attempt_error TEXT,
                    last_attempt_at TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            status_columns = {row["name"] for row in db.execute("PRAGMA table_info(nse_index_universe_status)")}
            if "last_attempt_status" not in status_columns:
                db.execute("ALTER TABLE nse_index_universe_status ADD COLUMN last_attempt_status TEXT")
            if "last_attempt_error" not in status_columns:
                db.execute("ALTER TABLE nse_index_universe_status ADD COLUMN last_attempt_error TEXT")
            if "last_attempt_at" not in status_columns:
                db.execute("ALTER TABLE nse_index_universe_status ADD COLUMN last_attempt_at TEXT")

    def save_snapshot(self, index_code: str, rows: list[dict[str, str]], source_url: str) -> dict[str, Any]:
        snapshot_date = datetime.now(IST).date().isoformat()
        expected = int(INDEX_UNIVERSES[index_code]["expected_count"])
        if len(rows) != expected or len({r["symbol"] for r in rows}) != expected:
            raise ValueError(f"{index_code} snapshot failed exact-count validation")
        with self._db() as db:
            db.executemany("""
                INSERT OR REPLACE INTO nse_index_constituent_snapshots
                    (index_code, snapshot_date, symbol, company_name, industry, series, isin, source_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                index_code, snapshot_date, row["symbol"], row["company_name"],
                row["industry"], row["series"], row["isin"], source_url,
            ) for row in rows])
            db.execute("""
                INSERT INTO nse_index_universe_status
                    (index_code, status, expected_count, actual_count, snapshot_date, source_url,
                     error,last_attempt_status,last_attempt_error,last_attempt_at,updated_at)
                VALUES (?, 'READY', ?, ?, ?, ?, NULL, 'SUCCEEDED', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(index_code) DO UPDATE SET
                    status='READY', expected_count=excluded.expected_count,
                    actual_count=excluded.actual_count, snapshot_date=excluded.snapshot_date,
                    source_url=excluded.source_url, error=NULL,
                    last_attempt_status='SUCCEEDED',last_attempt_error=NULL,
                    last_attempt_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            """, (index_code, expected, len(rows), snapshot_date, source_url))
        return {
            "status": "READY", "index_code": index_code,
            "expected_count": expected, "actual_count": len(rows),
            "snapshot_date": snapshot_date, "source_url": source_url,
        }

    def record_failure(self, index_code: str, error: str) -> None:
        expected = int(INDEX_UNIVERSES[index_code]["expected_count"])
        message = str(error or "NSE constituent refresh failed")[:300]
        with self._db() as db:
            existing = db.execute("""
                SELECT status,actual_count,snapshot_date
                FROM nse_index_universe_status WHERE index_code=?
            """, (index_code,)).fetchone()
            snapshot_count = 0
            if existing and existing["snapshot_date"]:
                snapshot_count = int(db.execute("""
                    SELECT COUNT(*) FROM nse_index_constituent_snapshots
                    WHERE index_code=? AND snapshot_date=?
                """, (index_code, existing["snapshot_date"])).fetchone()[0])
            has_last_good = bool(
                existing and existing["snapshot_date"] and snapshot_count == expected
                and int(existing["actual_count"] or 0) in {0, expected}
            )
            if has_last_good:
                db.execute("""
                    UPDATE nse_index_universe_status
                    SET status='READY',expected_count=?,actual_count=?,
                        error=?,last_attempt_status='FAILED',
                        last_attempt_error=?,last_attempt_at=CURRENT_TIMESTAMP,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE index_code=?
                """, (expected, expected, message, message, index_code))
            else:
                db.execute("""
                    INSERT INTO nse_index_universe_status
                        (index_code,status,expected_count,actual_count,error,
                         last_attempt_status,last_attempt_error,last_attempt_at,updated_at)
                    VALUES(?,'FAILED',?,0,?,'FAILED',?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                    ON CONFLICT(index_code) DO UPDATE SET
                        status='FAILED',expected_count=excluded.expected_count,
                        actual_count=0,error=excluded.error,
                        last_attempt_status='FAILED',last_attempt_error=excluded.last_attempt_error,
                        last_attempt_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                """, (index_code, expected, message, message))

    def symbols(self) -> list[str]:
        """Return the union of the latest validated snapshots for all required indices."""
        with self._db() as db:
            rows = db.execute("""
                SELECT DISTINCT snapshot.symbol
                FROM nse_index_constituent_snapshots AS snapshot
                JOIN nse_index_universe_status AS status
                  ON status.index_code = snapshot.index_code
                 AND status.snapshot_date = snapshot.snapshot_date
                WHERE status.status='READY'
                ORDER BY snapshot.symbol
            """).fetchall()
        return [str(row["symbol"]) for row in rows]

    def latest_universe(self) -> dict[str, Any]:
        """Return the latest validated constituent union in the MPDSM scanner contract."""
        status = self.status()
        if status["status"] != "READY":
            return {
                "status": "DATA_INSUFFICIENT",
                "reason": "One or more official NSE index snapshots are incomplete",
                "index_counts": {}, "unique_symbol_count": 0, "constituents": [],
            }
        code_map = {
            "NIFTY100": "NIFTY100",
            "NIFTYMIDCAP150": "NIFTY_MIDCAP150",
            "NIFTYSMALLCAP250": "NIFTY_SMALLCAP250",
        }
        members: dict[str, dict[str, Any]] = {}
        index_counts: dict[str, int] = {}
        with self._db() as db:
            status_rows = db.execute(
                "SELECT index_code, snapshot_date, actual_count FROM nse_index_universe_status WHERE status='READY'"
            ).fetchall()
            for item in status_rows:
                internal_code = str(item["index_code"])
                output_code = code_map.get(internal_code)
                if not output_code:
                    continue
                rows = db.execute("""
                    SELECT symbol, company_name, isin, industry, series, source_url
                    FROM nse_index_constituent_snapshots
                    WHERE index_code=? AND snapshot_date=? ORDER BY symbol
                """, (internal_code, item["snapshot_date"])).fetchall()
                if len(rows) != int(item["actual_count"]):
                    return {
                        "status": "DATA_INSUFFICIENT",
                        "reason": f"{internal_code} latest snapshot count mismatch",
                        "index_counts": index_counts, "unique_symbol_count": 0,
                        "constituents": [],
                    }
                index_counts[output_code] = len(rows)
                for row in rows:
                    symbol = str(row["symbol"])
                    member = members.setdefault(symbol, {
                        "symbol": symbol, "company_name": row["company_name"],
                        "isin": row["isin"], "index_memberships": [],
                        "retrieved_at": {},
                    })
                    member["index_memberships"].append(output_code)
                    member["retrieved_at"][output_code] = item["snapshot_date"]
        if len(members) != 500:
            return {
                "status": "DATA_INSUFFICIENT",
                "reason": f"Expected 500 unique symbols across the three indices; received {len(members)}",
                "index_counts": index_counts, "unique_symbol_count": len(members),
                "constituents": [],
            }
        return {
            "status": "READY",
            "source": "NSE Indices official constituent CSV",
            "index_counts": index_counts,
            "unique_symbol_count": len(members),
            "constituents": [members[key] for key in sorted(members)],
        }

    def status(self) -> dict[str, Any]:
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM nse_index_universe_status ORDER BY index_code"
            ).fetchall()
        by_code = {row["index_code"]: dict(row) for row in rows}
        return {
            "status": "READY" if all(
                code in by_code
                and by_code[code]["status"] == "READY"
                and by_code[code]["actual_count"] == int(spec["expected_count"])
                for code, spec in INDEX_UNIVERSES.items()
            ) else "INCOMPLETE",
            "required_indices": {
                code: {
                    "name": spec["name"],
                    "expected_count": int(spec["expected_count"]),
                    **(by_code.get(code) or {"status": "NOT_DOWNLOADED", "actual_count": 0}),
                }
                for code, spec in INDEX_UNIVERSES.items()
            },
        }


async def run_nse_universe_bootstrap() -> dict[str, Any]:
    """Fetch all three official universes; retain last good snapshots on failures."""
    store = NSEUniverseStore()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0 Safari/537.36",
        "Accept": "text/csv,text/plain,*/*",
        "Referer": "https://www.niftyindices.com/",
    }
    results: dict[str, Any] = {}
    timeout = httpx.Timeout(30.0, connect=12.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        for index_code, spec in INDEX_UNIVERSES.items():
            errors: list[str] = []
            saved = None
            for url in spec["urls"]:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    content = response.content.decode("utf-8-sig")
                    rows = parse_index_constituents(content, index_code)
                    saved = store.save_snapshot(index_code, rows, url)
                    break
                except (httpx.HTTPError, UnicodeError, csv.Error, ValueError) as exc:
                    errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
            if saved is None:
                message = "; ".join(errors) or "No official constituent source succeeded"
                store.record_failure(index_code, message)
                results[index_code] = {
                    "status": "FAILED",
                    "expected_count": int(spec["expected_count"]),
                    "actual_count": 0,
                    "error": message,
                }
            else:
                results[index_code] = saved
    summary = store.status()
    return {
        "status": "READY" if summary["status"] == "READY" else "FAILED",
        "indices": summary["required_indices"],
        "updated_at": datetime.now(IST).isoformat(),
    }


def nse_universe_status() -> dict[str, Any]:
    return NSEUniverseStore().status()
