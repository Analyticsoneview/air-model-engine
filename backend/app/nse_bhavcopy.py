"""NSE CM and F&O UDiFF bhavcopy bootstrap and query store.

Downloads official NSE end-of-day CM and FO UDiFF ZIP archives for the configured
initial history window (3 calendar months by default). Raw
ZIPs are retained; normalized contract rows are indexed in SQLite for app
queries. This is EOD data, not intraday ticks or full bid/ask snapshots.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
import sqlite3
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("air.nse.bhavcopy")
IST = ZoneInfo("Asia/Kolkata")
NSE_BASE = "https://nsearchives.nseindia.com/content"
MARKETS = ("CM", "FO")


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    import calendar
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _configured_history_months() -> int:
    """Initial AIR bootstrap defaults to three months; older history is an explicit backfill."""
    try:
        requested = int(os.getenv("AIR_NSE_HISTORY_MONTHS", "3"))
    except (TypeError, ValueError):
        requested = 3
    return max(3, min(requested, 60))


def _bootstrap_end_date(now: datetime) -> date:
    """Do not treat today's not-yet-published EOD archive as a missing session."""
    return now.date() if now.hour >= 21 else now.date() - timedelta(days=1)


def _date_range(start: date, end: date, holidays: set[str] | None = None):
    holidays = holidays or set()
    current = start
    while current <= end:
        if current.weekday() < 5 and current.isoformat() not in holidays:
            yield current
        current += timedelta(days=1)


def _parse_nse_calendar(payload: Any, year: int) -> dict[str, Any]:
    """Normalize NSE holiday-master JSON by segment; never assume CM and FO match."""
    if not isinstance(payload, dict):
        raise ValueError("NSE holiday calendar response is not an object")
    segments: dict[str, list[dict[str, str]]] = {}
    for segment in ("CM", "FO"):
        entries = payload.get(segment)
        if not isinstance(entries, list):
            raise ValueError(f"NSE holiday calendar is missing {segment}")
        normalized = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_date = str(entry.get("tradingDate") or "").strip()
            try:
                holiday_date = datetime.strptime(raw_date, "%d-%b-%Y").date()
            except ValueError:
                try:
                    holiday_date = date.fromisoformat(raw_date[:10])
                except ValueError:
                    continue
            if holiday_date.year == year:
                normalized.append({
                    "date": holiday_date.isoformat(),
                    "weekday": str(entry.get("weekDay") or ""),
                    "description": str(entry.get("description") or ""),
                })
        segments[segment] = sorted(normalized, key=lambda item: item["date"])
    return {
        "source": "NSE holiday-master?type=trading",
        "year": year,
        "segments": segments,
        "fetched_at": datetime.now(IST).isoformat(),
    }


async def _refresh_trading_calendar(client: httpx.AsyncClient, store: "NSEBhavcopyStore",
                                    year: int) -> dict[str, Any]:
    url = f"https://www.nseindia.com/api/holiday-master?type=trading&year={year}"
    try:
        response = await client.get(url, headers={"Accept": "application/json",
                                                  "X-Requested-With": "XMLHttpRequest"})
        response.raise_for_status()
        calendar = _parse_nse_calendar(response.json(), year)
        store.set_meta(f"trading_calendar_{year}", calendar)
        return calendar
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        cached = store.get_meta(f"trading_calendar_{year}")
        if cached:
            cached["refresh_error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
            cached["using_cached_calendar"] = True
            log.warning("NSE holiday calendar refresh failed; using persisted calendar: %s", type(exc).__name__)
            return cached
        raise RuntimeError("NSE trading calendar unavailable and no cached calendar exists") from exc


def _archive_url(market: str, day: date) -> str:
    stamp = day.strftime("%Y%m%d")
    return f"{NSE_BASE}/{market.lower()}/BhavCopy_NSE_{market}_0_0_0_{stamp}_F_0000.csv.zip"

def _archive_is_valid(path: str | Path) -> bool:
    """Return true only for a readable NSE ZIP containing a CRC-valid CSV."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            return bool(names) and archive.testzip() is None
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return False


def _expiry_iso(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        pass
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y", "%d/%m/%y", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if not raw or raw in {"-", "--", "NA", "N/A", "null", "None"}:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _field_from(normalized: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = normalized.get(re.sub(r"[^A-Z0-9]", "", name.upper()))
        if value is not None and str(value).strip() not in {"", "NA", "N/A"}:
            return str(value).strip()
    return None


def _normalize(market: str, trade_date: str, row: dict[str, Any]) -> dict[str, Any]:
    normalized = {re.sub(r"[^A-Z0-9]", "", str(key).upper()): value
                  for key, value in row.items()}
    field = lambda *names: _field_from(normalized, *names)
    symbol = field("TckrSymb", "TckrSym", "Underlying", "Symbol") or ""
    instrument_id = field("FinInstrmId", "FinInstrmID", "SctySrs") or ""
    instrument_type = field("FinInstrmTp", "FinInstrmNm", "Instrument") or ""
    expiry = field("XpryDt", "FininstrmActlXpryDt", "Expiry")
    option_type = field("OptnTp", "OptionType")
    strike = _number(field("StrkPric", "StrikePrice"))
    if not symbol and not instrument_id:
        return {}
    key = "|".join((instrument_id, symbol, expiry or "", str(strike or ""), option_type or ""))
    return {
        "market": market,
        "trade_date": trade_date,
        "instrument_key": key,
        "instrument_id": instrument_id,
        "symbol": symbol.upper(),
        "instrument_type": instrument_type.upper(),
        "expiry": _expiry_iso(expiry) or expiry,
        "strike": strike,
        "option_type": option_type.upper() if option_type else None,
        "open": _number(field( "OpnPric", "OpenPrice")),
        "high": _number(field( "HghPric", "HighPrice")),
        "low": _number(field( "LwPric", "LowPrice")),
        "close": _number(field( "ClsPric", "ClosePrice")),
        "last": _number(field( "LastPric", "LastPrice")),
        "previous_close": _number(field( "PrvsClsgPric", "PreviousClose")),
        "settlement": _number(field( "SttlmPric", "SettlementPrice")),
        "underlying_price": _number(field( "UndrlygPric", "UnderlyingPrice")),
        "volume": _number(field( "TtlTradgVol", "TtlTrdngVol", "Volume")),
        "turnover": _number(field( "TtlTrfVal", "Turnover")),
        "trades": _number(field( "TtlNbOfTxsExctd", "NumberOfTrades")),
        "open_interest": _number(field( "OpnIntrst", "OpenInterest")),
        "oi_change": _number(field( "ChngInOpnIntrst", "ChangeInOpenInterest")),
        "lot_size": _number(field( "NewBrdLotQty", "LotSize")),
        "isin": field( "ISIN"),
    }


class NSEBhavcopyStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("AIR_NSE_DB_PATH", "data/nse_bhavcopy.sqlite3")
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
                CREATE TABLE IF NOT EXISTS nse_bhavcopy (
                    market TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    instrument_key TEXT NOT NULL,
                    instrument_id TEXT,
                    symbol TEXT NOT NULL,
                    instrument_type TEXT,
                    expiry TEXT,
                    strike REAL,
                    option_type TEXT,
                    open REAL, high REAL, low REAL, close REAL, last REAL,
                    previous_close REAL, settlement REAL, underlying_price REAL,
                    volume REAL, turnover REAL, trades REAL, open_interest REAL,
                    oi_change REAL, lot_size REAL, isin TEXT,
                    PRIMARY KEY (market, trade_date, instrument_key)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_nse_symbol_date ON nse_bhavcopy(market, symbol, trade_date)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_nse_expiry ON nse_bhavcopy(market, expiry, symbol, option_type)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS nse_bhavcopy_files (
                    market TEXT NOT NULL, trade_date TEXT NOT NULL,
                    status TEXT NOT NULL, record_count INTEGER NOT NULL DEFAULT 0,
                    source_record_count INTEGER,
                    expired_removed_count INTEGER NOT NULL DEFAULT 0,
                    archive_path TEXT, source_url TEXT, error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (market, trade_date)
                )
            """)
            file_columns = {row["name"] for row in db.execute("PRAGMA table_info(nse_bhavcopy_files)")}
            if "source_record_count" not in file_columns:
                db.execute("ALTER TABLE nse_bhavcopy_files ADD COLUMN source_record_count INTEGER")
            if "expired_removed_count" not in file_columns:
                db.execute("ALTER TABLE nse_bhavcopy_files ADD COLUMN expired_removed_count INTEGER NOT NULL DEFAULT 0")
            db.execute("""
                CREATE TABLE IF NOT EXISTS nse_bhavcopy_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def file_status(self, market: str, trade_date: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM nse_bhavcopy_files WHERE market=? AND trade_date=?",
                (market, trade_date),
            ).fetchone()
            return dict(row) if row else None

    def set_file_status(self, market: str, trade_date: str, status: str,
                        count: int = 0, archive_path: str | None = None,
                        source_url: str | None = None, error: str | None = None,
                        source_record_count: int | None = None,
                        expired_removed_count: int = 0) -> None:
        with self._db() as db:
            db.execute("""
                INSERT INTO nse_bhavcopy_files
                    (market, trade_date, status, record_count, source_record_count,
                     expired_removed_count, archive_path, source_url, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(market, trade_date) DO UPDATE SET
                    status=excluded.status, record_count=excluded.record_count,
                    source_record_count=excluded.source_record_count,
                    expired_removed_count=excluded.expired_removed_count,
                    archive_path=excluded.archive_path, source_url=excluded.source_url,
                    error=excluded.error, updated_at=CURRENT_TIMESTAMP
            """, (market, trade_date, status, count, source_record_count,
                  expired_removed_count, archive_path, source_url, error))

    def actual_record_count(self, market: str, trade_date: str) -> int:
        with self._db() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM nse_bhavcopy WHERE market=? AND trade_date=?",
                (market, trade_date),
            ).fetchone()
        return int(row["n"])

    def reconcile_session(self, trade_date: str, expected_markets: tuple[str, ...]) -> dict[str, Any]:
        checks = []
        mismatch = False
        for market in expected_markets:
            status = self.file_status(market, trade_date)
            actual = self.actual_record_count(market, trade_date)
            source_count = status.get("source_record_count") if status else None
            stored_count = status.get("record_count", 0) if status else 0
            intentionally_removed = status.get("expired_removed_count", 0) if status else 0
            complete = bool(
                status and status.get("status") == "IMPORTED"
                and source_count is not None and source_count > 0
                and actual + intentionally_removed == source_count
                and stored_count == source_count
            )
            mismatch = mismatch or not complete
            checks.append({
                "market": market, "status": status.get("status") if status else "MISSING",
                "nse_source_records": source_count, "app_db_records": actual,
                "imported_record_count": stored_count,
                "expired_contract_records_removed": intentionally_removed,
                "complete": complete,
            })
        if mismatch:
            self.clear_session_for_repair(trade_date)
        return {"date": trade_date, "status": "COMPLETE" if not mismatch else "PARTIAL",
                "markets": checks, "repair_triggered": mismatch}

    def clear_session_for_repair(self, trade_date: str) -> None:
        """Remove both markets for a date so no mixed/partial session is exposed."""
        with self._db() as db:
            db.execute("DELETE FROM nse_bhavcopy WHERE trade_date=?", (trade_date,))
            db.execute("""
                UPDATE nse_bhavcopy_files
                SET status='PARTIAL', record_count=0, source_record_count=NULL,
                    expired_removed_count=0,
                    error='Session count mismatch; cleaned for complete NSE re-download',
                    updated_at=CURRENT_TIMESTAMP
                WHERE trade_date=?
            """, (trade_date,))

    def save_rows(self, market: str, trade_date: str, rows: list[dict[str, Any]]) -> int:
        normalized_by_key = {}
        for raw in rows:
            row = _normalize(market, trade_date, raw)
            if row:
                normalized_by_key[row["instrument_key"]] = row
        normalized = list(normalized_by_key.values())
        if not normalized:
            raise ValueError(f"NSE {market} archive contained no usable rows")
        columns = list(normalized[0].keys())
        sql = (
            f"INSERT OR REPLACE INTO nse_bhavcopy ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})"
        )
        with self._db() as db:
            # Replace the complete market/date snapshot in one transaction. A
            # repaired archive may contain fewer rows than a previously imported
            # copy; INSERT OR REPLACE alone would leave stale instruments behind.
            db.execute(
                "DELETE FROM nse_bhavcopy WHERE market=? AND trade_date=?",
                (market, trade_date),
            )
            db.executemany(sql, [[row[column] for column in columns] for row in normalized])
        return len(normalized)

    def cleanup_expired_fo(self, as_of: date) -> dict[str, Any]:
        """Purge only expired FO rows older than the configured research retention.

        Expired contracts inside the twelve-month (or larger configured) history
        window remain queryable for AIR options research. Older matching strategy
        evidence is enriched before deletion; lifecycle, entry/exit, quantity and
        stored P&L fields are not overwritten. Original NSE ZIPs remain retained and
        per-session removal counts preserve source-count reconciliation.
        """
        history_months = _configured_history_months()
        retention_start = _subtract_months(as_of, history_months)
        with self._db() as db:
            rows = db.execute("""
                SELECT trade_date, instrument_key, symbol, expiry, strike, option_type,
                       open, high, low, close, volume, underlying_price
                FROM nse_bhavcopy
                WHERE market='FO'
            """).fetchall()
            expired_rows = []
            expired_contracts = set()
            removed_by_date: dict[str, int] = {}
            unparsed_expiry_records = 0
            retained_expired_records = 0
            for row in rows:
                expiry = _expiry_iso(row["expiry"])
                if not expiry:
                    unparsed_expiry_records += 1
                    continue
                if date.fromisoformat(expiry) < as_of:
                    if date.fromisoformat(row["trade_date"]) >= retention_start:
                        # Keep expired contracts inside the configured research
                        # history window; raw archives alone are not queryable data.
                        retained_expired_records += 1
                        continue
                    expired_rows.append((row["trade_date"], row["instrument_key"]))
                    expired_contracts.add((row["symbol"], expiry, row["strike"], row["option_type"]))
                    removed_by_date[row["trade_date"]] = removed_by_date.get(row["trade_date"], 0) + 1
            strategy_snapshot = {
                "status": "NOT_NEEDED" if not expired_rows else "LEDGER_DATABASE_NOT_FOUND",
                "matched_contracts": 0, "strategy_rows_updated": 0,
                "daily_bars_attached": 0,
            }
            if expired_rows:
                ledger_path = Path(os.getenv(
                    "AIR_MODEL_LEDGER_DB_PATH", "data/air_model_ledger.sqlite3"
                ))
                if ledger_path.exists():
                    from app.model_engine_ledger import ModelEngineLedger
                    ledger = ModelEngineLedger(str(ledger_path))
                    try:
                        strategy_snapshot = ledger.attach_expired_fo_bars(
                            [dict(row) for row in rows
                             if (row["trade_date"], row["instrument_key"]) in set(expired_rows)]
                        )
                        strategy_snapshot["status"] = (
                            "SNAPSHOTTED" if strategy_snapshot["strategy_rows_updated"]
                            else "NO_MATCHING_STRATEGY_ROWS"
                        )
                    finally:
                        ledger.close()
                db.executemany(
                    "DELETE FROM nse_bhavcopy WHERE market='FO' AND trade_date=? AND instrument_key=?",
                    expired_rows,
                )
                for trade_date, count in removed_by_date.items():
                    db.execute("""
                        UPDATE nse_bhavcopy_files
                        SET expired_removed_count=expired_removed_count+?,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE market='FO' AND trade_date=? AND status='IMPORTED'
                    """, (count, trade_date))
            result = {
                "as_of": as_of.isoformat(),
                "retention_months": history_months,
                "retention_start_date": retention_start.isoformat(),
                "retained_expired_records": retained_expired_records,
                "removed_records": len(expired_rows),
                "removed_contract_keys": len(expired_contracts),
                "unparsed_expiry_records": unparsed_expiry_records,
                "retained_raw_nse_archives": True,
                "strategy_snapshot": strategy_snapshot,
                "strategy_ledger_modified": strategy_snapshot["strategy_rows_updated"] > 0,
                "strategy_lifecycle_and_pnl_fields_overwritten": False,
                "updated_at": datetime.now(IST).isoformat(),
            }
            db.execute("""
                INSERT INTO nse_bhavcopy_meta(key, value, updated_at)
                VALUES ('expired_fo_cleanup', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value, updated_at=CURRENT_TIMESTAMP
            """, (json.dumps(result, separators=(",", ":")),))
        return result

    def set_meta(self, key: str, value: Any) -> None:
        with self._db() as db:
            db.execute("""
                INSERT INTO nse_bhavcopy_meta(key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value, updated_at=CURRENT_TIMESTAMP
            """, (key, json.dumps(value, separators=(",", ":"))))

    def get_meta(self, key: str) -> Any:
        with self._db() as db:
            row = db.execute("SELECT value FROM nse_bhavcopy_meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def status(self) -> dict[str, Any]:
        with self._db() as db:
            file_rows = db.execute("""
                SELECT market, status, COUNT(*) AS files,
                       SUM(record_count - expired_removed_count) AS records,
                       SUM(expired_removed_count) AS expired_removed_records,
                       MIN(CASE WHEN status='IMPORTED' THEN trade_date END) AS first_date,
                       MAX(CASE WHEN status='IMPORTED' THEN trade_date END) AS last_date
                FROM nse_bhavcopy_files GROUP BY market, status
            """).fetchall()
            totals = db.execute("""
                SELECT market, COUNT(*) AS records, COUNT(DISTINCT trade_date) AS sessions,
                       MIN(trade_date) AS first_date, MAX(trade_date) AS last_date
                FROM nse_bhavcopy GROUP BY market
            """).fetchall()
        return {
            "bootstrap": self.get_meta("bootstrap") or {"status": "NOT_STARTED"},
            "markets": {row["market"]: dict(row) for row in totals},
            "files": [dict(row) for row in file_rows],
            "expired_fo_cleanup": self.get_meta("expired_fo_cleanup") or {},
            "updated_at": datetime.now(IST).isoformat(),
            "source": "NSE UDiFF official end-of-day CM and F&O bhavcopy archives",
            "data_scope": "EOD bhavcopy; not intraday ticks or historical bid/ask snapshots",
        "trading_calendar": self.get_meta(f"trading_calendar_{datetime.now(IST).year}") or {},
        }

    def symbol_coverage(self, symbols: list[str], start_date: str, end_date: str,
                        expected_sessions: int, minimum_sessions: int = 45) -> dict[str, Any]:
        """Report CM EOD coverage for each current index constituent."""
        unique_symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        if not unique_symbols:
            return {
                "status": "BLOCKED", "expected_symbols": 0, "observed_symbols": 0,
                "missing_symbols": [], "below_minimum_symbols": [],
                "minimum_sessions": minimum_sessions, "expected_sessions": expected_sessions,
            }
        placeholders = ",".join("?" for _ in unique_symbols)
        with self._db() as db:
            rows = db.execute(
                f"""
                SELECT symbol, COUNT(DISTINCT trade_date) AS sessions,
                       MIN(trade_date) AS first_date, MAX(trade_date) AS last_date
                FROM nse_bhavcopy
                WHERE market='CM' AND instrument_type='STK'
                  AND trade_date>=? AND trade_date<=?
                  AND symbol IN ({placeholders})
                GROUP BY symbol
                """,
                [start_date, end_date, *unique_symbols],
            ).fetchall()
        observed = {row["symbol"]: dict(row) for row in rows}
        by_symbol = []
        missing = []
        below_minimum = []
        for symbol in unique_symbols:
            item = observed.get(symbol)
            sessions = int(item["sessions"]) if item else 0
            if sessions == 0:
                missing.append(symbol)
            elif sessions < minimum_sessions:
                below_minimum.append(symbol)
            by_symbol.append({
                "symbol": symbol,
                "sessions": sessions,
                "coverage_pct": round(sessions / max(1, expected_sessions) * 100, 1),
                "first_date": item["first_date"] if item else None,
                "last_date": item["last_date"] if item else None,
                "status": "MISSING" if sessions == 0 else (
                    "INSUFFICIENT" if sessions < minimum_sessions else "READY"
                ),
            })
        return {
            "status": "BLOCKED" if missing else (
                "READY_WITH_WARNINGS" if below_minimum else "READY"
            ),
            "expected_symbols": len(unique_symbols),
            "observed_symbols": len(unique_symbols) - len(missing),
            "missing_count": len(missing),
            "missing_symbols": missing,
            "below_minimum_count": len(below_minimum),
            "below_minimum_symbols": below_minimum,
            "minimum_sessions": minimum_sessions,
            "expected_sessions": expected_sessions,
            "by_symbol": by_symbol,
        }

    def query_exact_symbol(self, market: str, symbol: str,
                            start_date: str | None = None, end_date: str | None = None,
                            limit: int = 5000) -> list[dict[str, Any]]:
        clauses = ["market=?", "symbol=?"]
        params: list[Any] = [market, symbol.strip().upper()]
        if start_date:
            clauses.append("trade_date>=?")
            params.append(start_date)
        if end_date:
            clauses.append("trade_date<=?")
            params.append(end_date)
        params.append(max(1, min(limit, 5000)))
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM nse_bhavcopy WHERE " + " AND ".join(clauses) +
                " ORDER BY trade_date ASC, expiry ASC, strike ASC LIMIT ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def query(self, market: str, symbol: str | None = None,
              start_date: str | None = None, end_date: str | None = None,
              instrument_type: str | None = None, instrument_id: str | None = None,
              limit: int = 100) -> list[dict[str, Any]]:
        clauses = ["market=?"]
        params: list[Any] = [market]
        if symbol:
            clauses.append("symbol LIKE ?")
            params.append(f"%{symbol.strip().upper()}%")
        if start_date:
            clauses.append("trade_date>=?")
            params.append(start_date)
        if end_date:
            clauses.append("trade_date<=?")
            params.append(end_date)
        if instrument_type:
            clauses.append("instrument_type LIKE ?")
            params.append(f"%{instrument_type.strip().upper()}%")
        if instrument_id:
            clauses.append("(instrument_id=? OR instrument_key=?)")
            params.extend([instrument_id.strip(), instrument_id.strip()])
        params.append(max(1, min(limit, 5000)))
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM nse_bhavcopy WHERE " + " AND ".join(clauses) +
                " ORDER BY trade_date DESC, symbol ASC, expiry ASC, strike ASC LIMIT ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]


async def _download_one(client: httpx.AsyncClient, semaphore: asyncio.Semaphore,
                        store: NSEBhavcopyStore, market: str, day: date,
                        archive_root: Path) -> dict[str, Any]:
    stamp = day.isoformat()
    existing = store.file_status(market, stamp)
    if existing and existing["status"] == "IMPORTED" and existing["record_count"] > 0:
        persisted_archive = Path(
            existing.get("archive_path") or (archive_root / market / f"{stamp}.zip")
        )
        if _archive_is_valid(persisted_archive):
            return {"market": market, "date": stamp, "status": "SKIPPED", "records": existing["record_count"]}
        log.warning(
            "NSE %s archive %s is missing or corrupt; re-downloading session",
            market, stamp,
        )
    url = _archive_url(market, day)
    async with semaphore:
        response = None
        for attempt in range(3):
            try:
                response = await client.get(url)
                if response.status_code == 404:
                    store.set_file_status(market, stamp, "NO_FILE", source_url=url)
                    return {"market": market, "date": stamp, "status": "NO_FILE", "records": 0}
                response.raise_for_status()
                break
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                if attempt == 2:
                    store.set_file_status(market, stamp, "FAILED", source_url=url,
                                          error=f"{type(exc).__name__}: {str(exc)[:180]}")
                    return {"market": market, "date": stamp, "status": "FAILED", "error": type(exc).__name__}
                await asyncio.sleep(1.5 * (attempt + 1))
        if response is None:
            return {"market": market, "date": stamp, "status": "FAILED", "error": "no response"}
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                raise ValueError("ZIP contains no CSV file")
            with archive.open(csv_names[0]) as member:
                text = io.TextIOWrapper(member, encoding="utf-8-sig", newline="")
                rows = list(csv.DictReader(text))
        if not rows:
            raise ValueError("CSV contains no data rows")
        count = store.save_rows(market, stamp, rows)
        folder = archive_root / market
        folder.mkdir(parents=True, exist_ok=True)
        archive_path = folder / f"{stamp}.zip"
        temp_path = folder / f"{stamp}.zip.part"
        temp_path.write_bytes(response.content)
        temp_path.replace(archive_path)
        store.set_file_status(market, stamp, "IMPORTED", count,
                              str(archive_path), url, source_record_count=count)
        return {"market": market, "date": stamp, "status": "IMPORTED", "records": count}
    except (zipfile.BadZipFile, OSError, UnicodeError, csv.Error, ValueError) as exc:
        store.set_file_status(market, stamp, "FAILED", source_url=url,
                              error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return {"market": market, "date": stamp, "status": "FAILED", "error": type(exc).__name__}


_store_instance: NSEBhavcopyStore | None = None


def _get_store() -> NSEBhavcopyStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = NSEBhavcopyStore()
    return _store_instance


async def run_nse_bootstrap(*, force: bool = False) -> dict[str, Any]:
    store = _get_store()
    now = datetime.now(IST)
    today = now.date()
    end_date = _bootstrap_end_date(now)
    history_months = _configured_history_months()
    history_start = _subtract_months(end_date, history_months)
    start = history_start
    days: list[date] = []
    archive_root = Path(os.getenv("AIR_NSE_ARCHIVE_DIR", "data/nse_archives"))
    state = {
        "status": "RUNNING", "started_at": datetime.now(IST).isoformat(),
        "start_date": start.isoformat(), "target_start_date": history_start.isoformat(),
        "end_date": end_date.isoformat(), "history_months": history_months,
        "calendar_months": history_months, "weekdays_to_check": len(days),
        "completed_files": 0, "imported_files": 0, "failed_files": 0,
        "no_file_days": 0, "records": {"CM": 0, "FO": 0},
    }
    store.set_meta("bootstrap", state)
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132.0 Safari/537.36",
        "Accept": "application/zip,application/octet-stream,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    results: list[dict[str, Any]] = []
    semaphore = asyncio.Semaphore(2)
    timeout = httpx.Timeout(35.0, connect=15.0)
    try:
        async with httpx.AsyncClient(headers=headers, timeout=timeout,
                                     follow_redirects=True, http2=False) as client:
            # Warm the NSE site once for installations where archive requests
            # require the standard NSE session cookies. Static archive access
            # may still work if this landing-page request is blocked.
            try:
                await client.get("https://www.nseindia.com/", timeout=12.0)
            except httpx.HTTPError:
                log.warning("NSE homepage warm-up failed; attempting archive host directly")
            calendars = {}
            for calendar_year in range(start.year, end_date.year + 1):
                calendars[str(calendar_year)] = await _refresh_trading_calendar(client, store, calendar_year)
            cm_holidays = {
                item["date"] for year_calendar in calendars.values()
                for item in year_calendar["segments"]["CM"]
            }
            fo_holidays = {
                item["date"] for year_calendar in calendars.values()
                for item in year_calendar["segments"]["FO"]
            }
            calendar = calendars[str(end_date.year)]
            # On restart, backfill from the last paired CM+FO session as well as
            # maintaining the rolling three-calendar-month minimum.
            with store._db() as db:
                last_pair = db.execute("""
                    SELECT MAX(cm.trade_date) AS last_date
                    FROM nse_bhavcopy_files cm
                    JOIN nse_bhavcopy_files fo
                      ON fo.trade_date=cm.trade_date
                     AND fo.market='FO' AND fo.status='IMPORTED'
                    WHERE cm.market='CM' AND cm.status='IMPORTED'
                """).fetchone()
            if last_pair and last_pair["last_date"]:
                recovery_start = date.fromisoformat(last_pair["last_date"]) + timedelta(days=1)
                # Always cover the full configured research window. If the last
                # paired session is older, extend backward to include the gap.
                start = min(history_start, recovery_start)
            days = list(_date_range(start, end_date))
            expected_files = sum(
                int(day.isoformat() not in cm_holidays) + int(day.isoformat() not in fo_holidays)
                for day in days
            )
            expected_paired_sessions = sum(
                1 for day in days
                if day.isoformat() not in cm_holidays and day.isoformat() not in fo_holidays
            )
            state.update({
                "start_date": start.isoformat(),
                "end_date": end_date.isoformat(),
                "target_start_date": history_start.isoformat(),
                "history_months": history_months,
                "weekdays_to_check": len(days),
                "expected_paired_sessions": expected_paired_sessions,
                "calendar_years": list(calendars.keys()),
                "cm_holiday_dates": len(cm_holidays),
                "fo_holiday_dates": len(fo_holidays),
                "expected_archive_files": expected_files,
                "calendar_source": "NSE official holiday-master trading calendar",
                "calendar_fetched_at": calendar["fetched_at"],
                "recovery_start_date": start.isoformat(),
            })
            store.set_meta("bootstrap", state)
            integrity_checks = []
            for day in days:
                stamp = day.isoformat()
                expected_markets = tuple(
                    market for market, holidays_for_market in (("CM", cm_holidays), ("FO", fo_holidays))
                    if stamp not in holidays_for_market
                )
                if expected_markets:
                    integrity_checks.append(store.reconcile_session(stamp, expected_markets))
            state["integrity_checked_sessions"] = len(integrity_checks)
            state["partial_sessions_found"] = sum(
                item["status"] == "PARTIAL" for item in integrity_checks
            )
            state["repaired_sessions"] = sum(
                item["repair_triggered"] for item in integrity_checks
            )
            state["integrity_mismatches"] = [
                item for item in integrity_checks if item["repair_triggered"]
            ]
            store.set_meta("bootstrap", state)
            for offset in range(0, len(days), 5):
                batch = days[offset:offset + 5]
                tasks = [
                    _download_one(client, semaphore, store, market, day, archive_root)
                    for day in batch
                    for market, holidays_for_market in (("CM", cm_holidays), ("FO", fo_holidays))
                    if day.isoformat() not in holidays_for_market
                ]
                batch_results = await asyncio.gather(*tasks)
                results.extend(batch_results)
                state["completed_files"] = len(results)
                state["imported_files"] = sum(item["status"] in {"IMPORTED", "SKIPPED"} for item in results)
                state["failed_files"] = sum(item["status"] == "FAILED" for item in results)
                state["no_file_days"] = sum(item["status"] == "NO_FILE" for item in results)
                state["records"] = {
                    market: sum(item.get("records", 0) for item in results if item["market"] == market)
                    for market in MARKETS
                }
                state["progress_pct"] = round(len(results) / max(1, expected_files) * 100, 1)
                state["updated_at"] = datetime.now(IST).isoformat()
                store.set_meta("bootstrap", state)
                await asyncio.sleep(0.15)
        imported_dates = {
            market: {item["date"] for item in results if item["market"] == market and item["status"] in {"IMPORTED", "SKIPPED"}}
            for market in MARKETS
        }
        paired_sessions = len(imported_dates["CM"] & imported_dates["FO"])
        any_failed = state["failed_files"] > 0
        any_missing_archive = state["no_file_days"] > 0
        expected_paired_sessions = int(state.get("expected_paired_sessions", 0))
        from app.nse_universe import INDEX_UNIVERSES, NSEUniverseStore, run_nse_universe_bootstrap
        universe_result = await run_nse_universe_bootstrap()
        state["universe"] = universe_result
        universe_store = NSEUniverseStore()
        universe_symbols = universe_store.symbols()
        expected_universe_symbols = sum(int(spec["expected_count"]) for spec in INDEX_UNIVERSES.values())
        expected_cm_sessions = sum(
            1 for day in days
            if day >= history_start and day.isoformat() not in cm_holidays
        )
        symbol_coverage = store.symbol_coverage(
            universe_symbols, history_start.isoformat(), end_date.isoformat(),
            expected_sessions=expected_cm_sessions, minimum_sessions=45,
        )
        state["symbol_coverage"] = symbol_coverage
        universe_ready = (
            universe_result.get("status") == "READY"
            and len(universe_symbols) == expected_universe_symbols
            and symbol_coverage.get("status") in {"READY", "READY_WITH_WARNINGS"}
        )
        complete_archive_set = (
            state["completed_files"] == expected_files
            and state["imported_files"] == expected_files
            and not any_failed
            and not any_missing_archive
        )
        state["paired_sessions"] = paired_sessions
        state["paired_session_coverage_pct"] = round(
            paired_sessions / max(1, expected_paired_sessions) * 100, 1
        )
        state["archive_coverage_pct"] = round(
            state["imported_files"] / max(1, expected_files) * 100, 1
        )
        state["status"] = "READY" if (
            complete_archive_set and expected_paired_sessions > 0
            and paired_sessions == expected_paired_sessions and universe_ready
        ) else ("PARTIAL" if any(imported_dates.values()) else "FAILED")

        # Strategy replays must finish before expired FO rows are purged. This
        # runs after the initial bootstrap and every scheduled/recovery refresh.
        # A still-partial download is deliberately left intact for the next repair.
        if state["status"] == "READY":
            try:
                from app.model_engine_orchestrator import run_post_import_strategy_cycle_async
                from app.market_data.service import get_default_market_data_service
                strategy_run = await run_post_import_strategy_cycle_async(
                    end_date.isoformat(), get_default_market_data_service())
                state["strategy_run"] = strategy_run
            except Exception as strategy_exc:  # noqa: BLE001
                strategy_run = {
                    "status": "FAILED",
                    "error": f"{type(strategy_exc).__name__}: {str(strategy_exc)[:200]}",
                }
                state["strategy_run"] = strategy_run
                log.exception("Post-import AIR strategy replay failed; expired FO cleanup deferred")
            if strategy_run.get("status") == "COMPLETED":
                try:
                    from app.air_monthly_pd_scanner import scan_monthly_pd_universe
                    scan_result = await asyncio.to_thread(
                        scan_monthly_pd_universe, end_date.isoformat()
                    )
                    state["monthly_pd_scan"] = {
                        key: scan_result.get(key) for key in (
                            "status", "as_of_date", "timeframe", "universe", "coverage",
                            "qualified_stock_symbols", "persisted_stock_snapshots",
                            "persisted_option_snapshots", "options_disclosure",
                            "broker_orders_placed",
                        ) if key in scan_result
                    }
                    if state["monthly_pd_scan"].get("status") not in {"COMPLETED", "WAITING_FOR_REFERENCE_SESSION"}:
                        state["status"] = "PARTIAL"
                except Exception as scan_exc:  # noqa: BLE001
                    state["monthly_pd_scan"] = {
                        "status": "FAILED",
                        "error": f"{type(scan_exc).__name__}: {str(scan_exc)[:200]}",
                    }
                    state["status"] = "PARTIAL"
                    log.exception("AIR MPDSM initial universe scan failed")
                state["expired_fo_cleanup"] = store.cleanup_expired_fo(today)
            else:
                state["monthly_pd_scan"] = {"status": "DEFERRED_STRATEGY_RUN_INCOMPLETE"}
                # Initial installation is not fully ready until the research
                # replay has completed successfully; a later bootstrap retries it.
                state["status"] = "PARTIAL"
                state["expired_fo_cleanup"] = {
                    "status": "DEFERRED_STRATEGY_RUN_INCOMPLETE",
                    "removed_records": 0,
                    "removed_contract_keys": 0,
                }
        else:
            state["strategy_run"] = {"status": "DEFERRED_DATA_PARTIAL"}
            state["expired_fo_cleanup"] = {
                "status": "DEFERRED_DATA_PARTIAL",
                "removed_records": 0,
                "removed_contract_keys": 0,
            }

        state["finished_at"] = datetime.now(IST).isoformat()
        state["note"] = (
            f"Complete {history_months}-month NSE CM/FO EOD history downloaded and reconciled."
            if state["status"] == "READY" else
            "Initial NSE history is incomplete: one or more expected archives are missing, failed, or unreconciled. Retry bootstrap to resume the missing sessions."
        )
        store.set_meta("bootstrap", state)
        return state
    except Exception as exc:
        state.update({"status": "FAILED", "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                      "finished_at": datetime.now(IST).isoformat()})
        store.set_meta("bootstrap", state)
        log.exception("NSE CM/FO bootstrap failed")
        return state


def nse_bootstrap_is_ready(bootstrap: dict[str, Any] | None) -> bool:
    """Accept the configured three-month initial window only with complete coverage."""
    if not isinstance(bootstrap, dict) or bootstrap.get("status") != "READY":
        return False
    try:
        months = int(bootstrap.get("history_months", 0))
        archive_coverage = float(bootstrap.get("archive_coverage_pct", 0))
        paired_coverage = float(bootstrap.get("paired_session_coverage_pct", 0))
    except (TypeError, ValueError):
        return False
    universes = bootstrap.get("universe") or {}
    indices = universes.get("indices") or {}
    required = {"NIFTY100": 100, "NIFTYMIDCAP150": 150, "NIFTYSMALLCAP250": 251}
    universes_ready = universes.get("status") == "READY" and all(
        (indices.get(code) or {}).get("status") == "READY"
        and (indices.get(code) or {}).get("actual_count") == expected
        for code, expected in required.items()
    )
    symbol_coverage = bootstrap.get("symbol_coverage") or {}
    coverage_ready = (
        symbol_coverage.get("status") in {"READY", "READY_WITH_WARNINGS"}
        and symbol_coverage.get("expected_symbols") == sum(required.values())
        and symbol_coverage.get("missing_count") == 0
    )
    strategy_run = bootstrap.get("strategy_run") or {}
    monthly_pd_scan = bootstrap.get("monthly_pd_scan") or {}
    return (
        months >= 3 and archive_coverage >= 100.0
        and paired_coverage >= 100.0 and universes_ready and coverage_ready
        and strategy_run.get("status") == "COMPLETED"
        and monthly_pd_scan.get("status") in {"COMPLETED", "WAITING_FOR_REFERENCE_SESSION"}
    )


def nse_data_rows_exact_symbol(market: str, symbol: str, **filters: Any) -> list[dict[str, Any]]:
    return _get_store().query_exact_symbol(market, symbol, **filters)


def nse_data_status() -> dict[str, Any]:
    return _get_store().status()


def nse_data_rows(market: str, **filters: Any) -> list[dict[str, Any]]:
    return _get_store().query(market, **filters)


_bootstrap_task: asyncio.Task | None = None
_scheduler = None


async def _daily_refresh() -> None:
    global _bootstrap_task
    if _bootstrap_task is not None and not _bootstrap_task.done():
        log.info("Skipping scheduled NSE refresh because a bootstrap is already running")
        return
    _bootstrap_task = asyncio.create_task(run_nse_bootstrap(force=True))
    await _bootstrap_task


def trigger_nse_bootstrap() -> dict[str, Any]:
    global _bootstrap_task
    if _bootstrap_task is not None and not _bootstrap_task.done():
        return {"status": "RUNNING", "message": "NSE CM/FO bootstrap is already running"}
    _bootstrap_task = asyncio.create_task(run_nse_bootstrap(force=True))
    return {"status": "QUEUED", "message": "NSE CM/FO initial-history bootstrap has been queued"}


def start_nse_data_jobs() -> None:
    global _bootstrap_task, _scheduler
    if os.getenv("AIR_NSE_BOOTSTRAP_ENABLED", "true").lower() != "true":
        log.info("NSE historical data bootstrap and refresh are disabled")
        return
    if _bootstrap_task is None or _bootstrap_task.done():
        _bootstrap_task = asyncio.create_task(run_nse_bootstrap())
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        _scheduler = AsyncIOScheduler(timezone=IST)
        _scheduler.add_job(_daily_refresh, CronTrigger(hour=21, minute=0, day_of_week="mon-fri", timezone=IST),
                           id="air-nse-cm-fo-daily-refresh", replace_existing=True,
                           max_instances=1, coalesce=True)
        _scheduler.start()
    except Exception:
        log.exception("Could not start NSE daily refresh scheduler")


def stop_nse_data_jobs() -> None:
    global _bootstrap_task, _scheduler
    if _bootstrap_task and not _bootstrap_task.done():
        _bootstrap_task.cancel()
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
