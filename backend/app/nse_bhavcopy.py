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


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


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


def _field(row: dict[str, Any], *names: str) -> str | None:
    normalized = {re.sub(r"[^A-Z0-9]", "", str(key).upper()): value
                  for key, value in row.items()}
    for name in names:
        value = normalized.get(re.sub(r"[^A-Z0-9]", "", name.upper()))
        if value is not None and str(value).strip() not in {"", "NA", "N/A"}:
            return str(value).strip()
    return None


def _normalize(market: str, trade_date: str, row: dict[str, Any]) -> dict[str, Any]:
    symbol = _field(row, "TckrSymb", "TckrSym", "Underlying", "Symbol") or ""
    instrument_id = _field(row, "FinInstrmId", "FinInstrmID", "SctySrs") or ""
    instrument_type = _field(row, "FinInstrmTp", "FinInstrmNm", "Instrument") or ""
    expiry = _field(row, "XpryDt", "FininstrmActlXpryDt", "Expiry")
    option_type = _field(row, "OptnTp", "OptionType")
    strike = _number(_field(row, "StrkPric", "StrikePrice"))
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
        "open": _number(_field(row, "OpnPric", "OpenPrice")),
        "high": _number(_field(row, "HghPric", "HighPrice")),
        "low": _number(_field(row, "LwPric", "LowPrice")),
        "close": _number(_field(row, "ClsPric", "ClosePrice")),
        "last": _number(_field(row, "LastPric", "LastPrice")),
        "previous_close": _number(_field(row, "PrvsClsgPric", "PreviousClose")),
        "settlement": _number(_field(row, "SttlmPric", "SettlementPrice")),
        "underlying_price": _number(_field(row, "UndrlygPric", "UnderlyingPrice")),
        "volume": _number(_field(row, "TtlTradgVol", "TtlTrdngVol", "Volume")),
        "turnover": _number(_field(row, "TtlTrfVal", "Turnover")),
        "trades": _number(_field(row, "TtlNbOfTxsExctd", "NumberOfTrades")),
        "open_interest": _number(_field(row, "OpnIntrst", "OpenInterest")),
        "oi_change": _number(_field(row, "ChngInOpnIntrst", "ChangeInOpenInterest")),
        "lot_size": _number(_field(row, "NewBrdLotQty", "LotSize")),
        "isin": _field(row, "ISIN"),
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
                    archive_path TEXT, source_url TEXT, error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (market, trade_date)
                )
            """)
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
                        source_url: str | None = None, error: str | None = None) -> None:
        with self._db() as db:
            db.execute("""
                INSERT INTO nse_bhavcopy_files
                    (market, trade_date, status, record_count, archive_path, source_url, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(market, trade_date) DO UPDATE SET
                    status=excluded.status, record_count=excluded.record_count,
                    archive_path=excluded.archive_path, source_url=excluded.source_url,
                    error=excluded.error, updated_at=CURRENT_TIMESTAMP
            """, (market, trade_date, status, count, archive_path, source_url, error))

    def save_rows(self, market: str, trade_date: str, rows: list[dict[str, Any]]) -> int:
        normalized = [_normalize(market, trade_date, row) for row in rows]
        normalized = [row for row in normalized if row]
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
                              str(archive_path), url)
        return {"market": market, "date": stamp, "status": "IMPORTED", "records": count}
    except (zipfile.BadZipFile, OSError, UnicodeError, csv.Error, ValueError) as exc:
        store.set_file_status(market, stamp, "FAILED", source_url=url,
                              error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return {"market": market, "date": stamp, "status": "FAILED", "error": type(exc).__name__}


async def run_nse_bootstrap(*, force: bool = False) -> dict[str, Any]:
    store = NSEBhavcopyStore()
    today = datetime.now(IST).date()
    start = _subtract_months(today, 3)
    days = list(_date_range(start, today))
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
    semaphore = asyncio.Semaphore(4)
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
            for offset in range(0, len(days), 5):
                batch = days[offset:offset + 5]
                tasks = [
                    _download_one(client, semaphore, store, market, day, archive_root)
                    for day in batch for market in MARKETS
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
                state["progress_pct"] = round(len(results) / max(1, len(days) * 2) * 100, 1)
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
    return NSEBhavcopyStore().status()


def nse_data_rows(market: str, **filters: Any) -> list[dict[str, Any]]:
    return NSEBhavcopyStore().query(market, **filters)


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
    if os.getenv("AIR_NSE_BOOTSTRAP_ENABLED", "true").lower() == "true":
        if _bootstrap_task is None or _bootstrap_task.done():
            _bootstrap_task = asyncio.create_task(run_nse_bootstrap())
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        _scheduler = AsyncIOScheduler(timezone=IST)
        _scheduler.add_job(_daily_refresh, CronTrigger(hour=18, minute=15, day_of_week="mon-fri", timezone=IST),
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
