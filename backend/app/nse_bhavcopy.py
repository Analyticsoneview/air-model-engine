"""NSE CM and F&O UDiFF bhavcopy bootstrap and query store.

Downloads official NSE end-of-day CM and FO UDiFF ZIP archives for the
previous three calendar months. Raw ZIPs are retained; normalized contract
rows are indexed in SQLite for app queries. This is EOD data, not intraday
ticks or full bid/ask option-chain snapshots.
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
        "expiry": expiry,
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
                    archive_path TEXT, source_url TEXT, error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (market, trade_date)
                )
            """)
            file_columns = {row["name"] for row in db.execute("PRAGMA table_info(nse_bhavcopy_files)")}
            if "source_record_count" not in file_columns:
                db.execute("ALTER TABLE nse_bhavcopy_files ADD COLUMN source_record_count INTEGER")
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
                        source_record_count: int | None = None) -> None:
        with self._db() as db:
            db.execute("""
                INSERT INTO nse_bhavcopy_files
                    (market, trade_date, status, record_count, source_record_count,
                     archive_path, source_url, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(market, trade_date) DO UPDATE SET
                    status=excluded.status, record_count=excluded.record_count,
                    source_record_count=excluded.source_record_count,
                    archive_path=excluded.archive_path, source_url=excluded.source_url,
                    error=excluded.error, updated_at=CURRENT_TIMESTAMP
            """, (market, trade_date, status, count, source_record_count,
                  archive_path, source_url, error))

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
            complete = bool(
                status and status.get("status") == "IMPORTED"
                and source_count is not None and source_count > 0
                and actual == source_count and stored_count == source_count
            )
            mismatch = mismatch or not complete
            checks.append({
                "market": market, "status": status.get("status") if status else "MISSING",
                "nse_source_records": source_count, "app_db_records": actual,
                "imported_record_count": stored_count, "complete": complete,
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
            db.executemany(sql, [[row[column] for column in columns] for row in normalized])
        return len(normalized)

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
                SELECT market, status, COUNT(*) AS files, SUM(record_count) AS records,
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
            "updated_at": datetime.now(IST).isoformat(),
            "source": "NSE UDiFF official end-of-day CM and F&O bhavcopy archives",
            "data_scope": "EOD bhavcopy; not intraday ticks or historical bid/ask snapshots",
        "trading_calendar": self.get_meta(f"trading_calendar_{datetime.now(IST).year}") or {},
        }

    def query(self, market: str, symbol: str | None = None,
              start_date: str | None = None, end_date: str | None = None,
              instrument_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
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
        params.append(max(1, min(limit, 500)))
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
        return {"market": market, "date": stamp, "status": "SKIPPED", "records": existing["record_count"]}
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
    today = datetime.now(IST).date()
    three_month_start = _subtract_months(today, 3)
    start = three_month_start
    days: list[date] = []
    archive_root = Path(os.getenv("AIR_NSE_ARCHIVE_DIR", "data/nse_archives"))
    state = {
        "status": "RUNNING", "started_at": datetime.now(IST).isoformat(),
        "start_date": start.isoformat(), "end_date": today.isoformat(),
        "calendar_months": 3, "weekdays_to_check": len(days),
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
            for calendar_year in range(start.year, today.year + 1):
                calendars[str(calendar_year)] = await _refresh_trading_calendar(client, store, calendar_year)
            cm_holidays = {
                item["date"] for year_calendar in calendars.values()
                for item in year_calendar["segments"]["CM"]
            }
            fo_holidays = {
                item["date"] for year_calendar in calendars.values()
                for item in year_calendar["segments"]["FO"]
            }
            calendar = calendars[str(today.year)]
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
                start = min(three_month_start, recovery_start)
            days = list(_date_range(start, today))
            expected_files = sum(
                int(day.isoformat() not in cm_holidays) + int(day.isoformat() not in fo_holidays)
                for day in days
            )
            state.update({
                "start_date": start.isoformat(),
                "weekdays_to_check": len(days),
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
        state["paired_sessions"] = paired_sessions
        state["status"] = "READY" if paired_sessions >= 45 and not any_failed else (
            "PARTIAL" if any(imported_dates.values()) else "FAILED"
        )
        state["finished_at"] = datetime.now(IST).isoformat()
        state["note"] = (
            "At least three calendar months of paired CM and FO sessions are available."
            if state["status"] == "READY" else
            "Some NSE archive downloads failed or paired session coverage is incomplete. Retry bootstrap to fill gaps."
        )
        store.set_meta("bootstrap", state)
        return state
    except Exception as exc:
        state.update({"status": "FAILED", "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                      "finished_at": datetime.now(IST).isoformat()})
        store.set_meta("bootstrap", state)
        log.exception("NSE CM/FO bootstrap failed")
        return state


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
    return {"status": "QUEUED", "message": "NSE CM/FO three-month bootstrap has been queued"}


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
