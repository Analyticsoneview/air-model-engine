"""Read-only NSE settlement versus broker EOD close comparison feed."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from app.market_data.contracts import MarketInstrument
from app.market_data.customer_runtime import (
    get_customer_market_data_service,
    get_customer_market_data_status,
)
from app.nse_bhavcopy import nse_data_rows, nse_data_status
from app.security import require_customer

router = APIRouter(prefix="/api/v1/model-engine", tags=["AIR Settlement Comparison"])
IST = ZoneInfo("Asia/Kolkata")


def _identity(row: dict, market: str) -> tuple:
    if market == "CM":
        return (str(row.get("symbol") or "").upper(),)
    return (
        str(row.get("symbol") or "").upper(),
        str(row.get("expiry") or "")[:10],
        str(row.get("strike") if row.get("strike") is not None else ""),
        str(row.get("option_type") or "").upper(),
    )


def _settlement_delta(current: float | None, previous: float | None) -> tuple[float | None, str]:
    if current is None or previous is None:
        return None, "DATA MISSING"
    delta = round(float(current) - float(previous), 4)
    return delta, "UP" if delta > 0 else "DOWN" if delta < 0 else "UNCHANGED"


def _broker_signal(broker_close: float | None, settlement: float | None) -> tuple:
    if broker_close is None or settlement is None or settlement == 0:
        return None, None, "DATA MISSING", "NO SIGNAL"
    variance = round(float(broker_close) - float(settlement), 4)
    pct = round((variance / float(settlement)) * 100, 4)
    if variance > 0:
        return variance, pct, "OPTION CLOSE UP", "SELL WATCH"
    if variance < 0:
        return variance, pct, "OPTION CLOSE DOWN", "BUY WATCH"
    return variance, pct, "UNCHANGED", "NO SIGNAL"


def _broker_instrument(row: dict, market: str, provider: str, account_id: str,
                       master: list[dict]) -> MarketInstrument | None:
    symbol = str(row.get("symbol") or "").upper()
    matches = []
    for item in master:
        item_symbol = str(item.get("symbol") or "").upper()
        underlying = str(item.get("underlying_symbol") or item_symbol).upper()
        if market == "CM":
            if item_symbol != symbol or "FO" in str(item.get("segment") or "").upper():
                continue
        else:
            if underlying != symbol:
                continue
            if str(item.get("expiry") or "")[:10] != str(row.get("expiry") or "")[:10]:
                continue
            try:
                if Decimal(str(item.get("strike"))) != Decimal(str(row.get("strike"))):
                    continue
            except Exception:
                continue
            if str(item.get("option_type") or "").upper() != str(row.get("option_type") or "").upper():
                continue
            if "FO" not in str(item.get("segment") or "").upper():
                continue
        matches.append(item)
    if len(matches) != 1:
        return None
    item = matches[0]
    return MarketInstrument(
        exchange=str(item.get("exchange") or "NSE"),
        symbol=str(item.get("symbol") or symbol),
        token=str(item.get("token") or ""),
        segment=str(item.get("segment") or ("NSE_EQ" if market == "CM" else "NSE_FO")),
        expiry=item.get("expiry"),
        strike=Decimal(str(item["strike"])) if item.get("strike") is not None else None,
        option_type=item.get("option_type"),
        lot_size=item.get("lot_size"),
        instrument_type=item.get("instrument_type"),
        underlying_symbol=item.get("underlying_symbol") or symbol,
    )


async def _broker_closes(service, market: str, rows: list[dict],
                         trade_date: str) -> tuple[dict[tuple, float], str | None, str]:
    source = service.router.resolve("historical")
    if not source:
        return {}, None, "BROKER HISTORICAL SOURCE NOT CONNECTED"
    provider, account_id, adapter = source[0]
    if provider == "nse_bhavcopy":
        return {}, provider, "NSE EOD ACTIVE; BROKER CLOSE UNAVAILABLE"
    master = service.instruments.list_all(provider, account_id, limit=50000) if service.instruments else []
    start_day = date.fromisoformat(trade_date)
    start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    semaphore = asyncio.Semaphore(6)
    results: dict[tuple, float] = {}

    async def load(row: dict) -> None:
        instrument = _broker_instrument(row, market, provider, account_id, master)
        if instrument is None:
            return
        async with semaphore:
            try:
                bars = await adapter.get_historical(instrument, start, end, "day")
            except Exception:
                return
        for bar in bars:
            try:
                bar_day = bar.start_time.astimezone(IST).date().isoformat()
            except Exception:
                continue
            if bar_day == trade_date and bar.close is not None:
                results[_identity(row, market)] = float(bar.close)
                return

    await asyncio.gather(*(load(row) for row in rows))
    return results, provider, "BROKER DAILY HISTORICAL CLOSES; UNMATCHED CONTRACTS LEFT BLANK"


def _build_rows(market: str, current_rows: list[dict], history_rows: list[dict],
                broker_closes: dict[tuple, float]) -> list[dict]:
    previous_by_key: dict[tuple, dict] = {}
    for row in history_rows:
        key = _identity(row, market)
        old = previous_by_key.get(key)
        if old is None or str(row.get("trade_date") or "") > str(old.get("trade_date") or ""):
            previous_by_key[key] = row
    result = []
    for row in current_rows:
        key = _identity(row, market)
        previous = previous_by_key.get(key)
        settlement = row.get("settlement") if market == "FO" else row.get("close")
        previous_settlement = (
            previous.get("settlement") if market == "FO" else previous.get("close")
        ) if previous else None
        settlement_basis = (
            "NSE FO SETTLEMENT PRICE" if market == "FO"
            else "NSE CM CLOSE (CASH MARKET REFERENCE)"
        )
        change, direction = _settlement_delta(settlement, previous_settlement)
        broker_close = broker_closes.get(key)
        variance, variance_pct, close_direction, action = _broker_signal(broker_close, settlement)
        result.append({
            "market": market,
            "instrument_type": "STOCK" if market == "CM" else "OPTION",
            "symbol": row.get("symbol"),
            "expiry": row.get("expiry"),
            "strike": row.get("strike"),
            "option_type": row.get("option_type"),
            "trade_date": row.get("trade_date"),
            "broker_close": broker_close,
            "nse_settlement": settlement,
            "nse_settlement_basis": settlement_basis,
            "broker_variance": variance,
            "broker_variance_pct": variance_pct,
            "broker_close_direction": close_direction,
            "action": action if market == "FO" else "—",
            "previous_nse_settlement": previous_settlement,
            "settlement_change": change,
            "settlement_direction": direction,
            "volume": row.get("volume"),
            "open_interest": row.get("open_interest"),
            "oi_change": row.get("oi_change"),
            "bid_ask_available": False,
            "liquidity_status": (
                "VOLUME_AND_OI_PRESENT; BID/ASK NOT IN EOD DATA"
                if row.get("volume") is not None and row.get("open_interest") is not None
                else "VOLUME/OI DATA INCOMPLETE"
            ),
            "nse_instrument_id": row.get("instrument_id"),
        })
    return result


@router.get("/settlement-comparison")
async def get_settlement_comparison(
    limit: int = Query(default=500, ge=1, le=5000),
    customer_id: str = Depends(require_customer),
) -> dict:
    """Compare official NSE settlement values with selected broker daily closes."""
    status = nse_data_status()
    cm_status = status.get("markets", {}).get("CM", {})
    fo_status = status.get("markets", {}).get("FO", {})
    cm_day, fo_day = cm_status.get("last_date"), fo_status.get("last_date")
    dates = [value for value in (cm_day, fo_day) if value]
    if not dates:
        return {
            "data_status": "AWAITING_NSE_EOD_DATA", "trade_date": None,
            "stocks": {"rows": [], "up": 0, "down": 0},
            "options": {"rows": [], "up": 0, "down": 0, "sell_watch": 0, "buy_watch": 0},
            "note": "NSE CM/FO EOD bhavcopy has not completed its initial import.",
        }
    trade_date = min(dates)
    current_day = date.fromisoformat(trade_date)
    previous_end = (current_day - timedelta(days=1)).isoformat()
    previous_start = (current_day - timedelta(days=10)).isoformat()
    cm_current = nse_data_rows("CM", start_date=trade_date, end_date=trade_date, limit=limit)
    fo_current = nse_data_rows("FO", start_date=trade_date, end_date=trade_date, limit=limit)
    cm_history = nse_data_rows("CM", start_date=previous_start, end_date=previous_end, limit=limit)
    fo_history = nse_data_rows("FO", start_date=previous_start, end_date=previous_end, limit=limit)
    service = await get_customer_market_data_service(customer_id)
    cm_broker, cm_provider, cm_note = await _broker_closes(service, "CM", cm_current, trade_date)
    fo_broker, fo_provider, fo_note = await _broker_closes(service, "FO", fo_current, trade_date)
    stocks = _build_rows("CM", cm_current, cm_history, cm_broker)
    options = _build_rows("FO", fo_current, fo_history, fo_broker)
    stocks.sort(key=lambda row: (row.get("settlement_direction") != "UP", row.get("symbol") or ""))
    options.sort(key=lambda row: (row.get("action") not in ("SELL WATCH", "BUY WATCH"),
                                  row.get("symbol") or "", row.get("expiry") or "",
                                  row.get("strike") or 0, row.get("option_type") or ""))
    return {
        "data_status": "POPULATED" if stocks or options else "NO_ROWS_FOR_LATEST_SESSION",
        "trade_date": trade_date,
        "row_limit_per_market": limit,
        "coverage_note": "Each market response is capped at row_limit_per_market. Increase the endpoint limit up to 5000 when a broader universe is required.",
        "nse_source": "NSE UDiFF official CM/FO EOD bhavcopy",
        "broker_source": {
            "stocks": cm_provider, "options": fo_provider,
            "historical_source": (await get_customer_market_data_status(customer_id)).get("historical_source"),
        },
        "stocks": {
            "rows": stocks,
            "up": sum(row["settlement_direction"] == "UP" for row in stocks),
            "down": sum(row["settlement_direction"] == "DOWN" for row in stocks),
            "broker_close_note": cm_note,
        },
        "options": {
            "rows": options,
            "up": sum(row["broker_close_direction"] == "OPTION CLOSE UP" for row in options),
            "down": sum(row["broker_close_direction"] == "OPTION CLOSE DOWN" for row in options),
            "sell_watch": sum(row["action"] == "SELL WATCH" for row in options),
            "buy_watch": sum(row["action"] == "BUY WATCH" for row in options),
            "broker_close_note": fo_note,
            "qualification_note": "Volume/OI are shown where available. NSE EOD data does not contain live bid/ask spread; no liquidity-qualified status is inferred.",
        },
        "note": "Watch-only comparison. Positive broker_close - NSE settlement = OPTION CLOSE UP / SELL WATCH; negative = OPTION CLOSE DOWN / BUY WATCH. Missing broker history or settlement produces no signal. No orders are placed.",
        "updated_at": datetime.now(IST).isoformat(),
    }
