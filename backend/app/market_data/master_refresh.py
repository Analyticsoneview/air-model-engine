"""Daily provider-specific instrument-master refresh and safe snapshot cleanup."""
from __future__ import annotations

import csv
import gzip
import io
import json
import os
import re
from datetime import date
from datetime import datetime, timezone
from typing import Any

import httpx

from app.market_data.instrument_registry import MarketInstrumentDirectory


# URLs are configurable because broker download URLs/coverage can change.
# Each entry must be an official broker instrument-master endpoint.
DEFAULT_MASTER_URLS = {
    "zerodha": "https://api.kite.trade/instruments",
    "upstox": "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz",
    "angelone": "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
    "dhan": "https://images.dhan.co/api-data/api-scrip-master-detailed.csv",
    "fyers": [
        "https://public.fyers.in/sym_details/NSE_CM_sym_master.json",
        "https://public.fyers.in/sym_details/NSE_FO_sym_master.json",
        "https://public.fyers.in/sym_details/BSE_CM_sym_master.json",
        "https://public.fyers.in/sym_details/BSE_FO_sym_master.json",
    ],
}

ALIASES = {
    "exchange": ("exchange", "exch", "exch_seg", "exchange_code", "sem_exm_exch_id", "exchangename"),
    "symbol": ("tradingsymbol", "trading_symbol", "symbol", "sem_trading_symbol", "name", "symbol ticker", "symbol ticker", "symticker"),
    "underlying_symbol": ("underlying_symbol", "underlying", "sem_underlying_symbol", "underlying symbol", "undersym"),
    "token": ("instrument_token", "instrument_key", "token", "symboltoken", "symbol_token",
              "security_id", "sem_smst_security_id", "fy_token", "fytoken"),
    "segment": ("segment", "exchange_segment", "exch_seg", "sem_segment"),
    "expiry": ("expiry", "expiry_date", "sem_expiry_date", "expiry date", "expirydate"),
    "strike": ("strike", "strike_price", "sem_strike_price", "strike price", "strikeprice"),
    "option_type": ("option_type", "instrument_type", "instrumenttype", "right", "optt", "sem_option_type", "option type", "opttype"),
    "lot_size": ("lot_size", "lotsize", "sem_lot_units", "minimum lot size", "minlotsize"),
    "tick_size": ("tick_size", "ticksize", "sem_tick_size", "tick size", "ticksize"),
}


def _key_map(row: dict[str, Any]) -> dict[str, Any]:
    lower = {str(k).strip().lower(): v for k, v in row.items()}
    result = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            if alias in lower and lower[alias] not in (None, ""):
                result[target] = lower[alias]
                break
    return result


def _normalize(provider: str, row: dict[str, Any]) -> dict[str, Any] | None:
    value = _key_map(row)
    exchange = str(value.get("exchange") or "").strip().upper()
    symbol = str(value.get("symbol") or "").strip().upper()
    raw_type = str(value.get("option_type") or "").strip().upper()
    underlying_raw = value.get("underlying_symbol")
    if not underlying_raw and raw_type in {"CE", "PE", "FUT", "OPTIDX", "OPTSTK", "FUTIDX", "FUTSTK"}:
        underlying_raw = row.get("name")
    underlying_symbol = str(underlying_raw or symbol).strip().upper()
    token = str(value.get("token") or "").strip()
    segment = str(value.get("segment") or "").strip().upper()
    if provider == "fyers":
        exchange = {"10": "NSE", "11": "MCX", "12": "BSE"}.get(exchange, exchange)
        segment = {
            "10": f"{exchange}_CM", "11": f"{exchange}_FO",
            "12": f"{exchange}_CD", "20": f"{exchange}_COM",
        }.get(segment, segment)
    if not all((exchange, symbol, token, segment)):
        return None
    option_type = {"CE": "CE", "PE": "PE", "CALL": "CE", "PUT": "PE"}.get(raw_type)
    instrument_type = str(value.get("instrument_type") or raw_type or "").strip() or None
    if option_type is None and raw_type in {"OPTIDX", "OPTSTK"}:
        suffix = re.search(r"(CE|PE)$", symbol)
        option_type = suffix.group(1) if suffix else None
    expiry = str(value.get("expiry") or "").strip() or None
    if expiry and provider == "fyers" and expiry.isdigit():
        try:
            expiry = datetime.fromtimestamp(int(expiry), timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    if expiry:
        for fmt in ("%Y-%m-%d", "%d%b%Y", "%d-%m-%Y", "%Y%m%d"):
            try:
                candidate = expiry if fmt == "%Y-%m-%d" else expiry[:9]
                expiry = datetime.strptime(candidate, fmt).date().isoformat()
                break
            except ValueError:
                continue
    strike = value.get("strike")
    try:
        strike_value = float(strike) if strike not in (None, "") else None
        if strike_value is not None and strike_value < 0:
            strike_value = None
        # Angel SmartAPI publishes option strike in paise; normalize to rupees.
        if provider == "angelone" and strike_value is not None:
            strike_value /= 100
        strike = str(strike_value) if strike_value is not None else None
    except (TypeError, ValueError):
        strike = None
    try:
        lot_size = int(float(value["lot_size"])) if value.get("lot_size") not in (None, "") else None
    except (TypeError, ValueError):
        lot_size = None
    try:
        tick_size = str(float(value["tick_size"])) if value.get("tick_size") not in (None, "") else None
    except (TypeError, ValueError):
        tick_size = None
    return {
        "exchange": exchange, "symbol": symbol, "underlying_symbol": underlying_symbol,
        "token": token, "segment": segment,
        "expiry": expiry, "strike": strike, "option_type": option_type,
        "lot_size": lot_size, "instrument_type": instrument_type, "tick_size": tick_size,
    }


def parse_master(provider: str, content: bytes, filename: str = "", *, min_rows: int = 100) -> list[dict[str, Any]]:
    raw = gzip.decompress(content) if content[:2] == b"\x1f\x8b" or filename.endswith(".gz") else content
    text = raw.decode("utf-8-sig", errors="replace")
    if filename.lower().endswith(".json") or text.lstrip().startswith(("[", "{")):
        payload = json.loads(text)
        if isinstance(payload, dict):
            for key in ("data", "instruments", "records", "result"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
            else:
                # FYERS publishes each symbol-master JSON as a ticker-keyed object.
                payload = [
                    {**value, "symTicker": value.get("symTicker") or ticker}
                    for ticker, value in payload.items() if isinstance(value, dict)
                ]
        rows = payload if isinstance(payload, list) else []
    else:
        rows = list(csv.DictReader(io.StringIO(text)))
    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _normalize(provider, row)
        if item and item["token"] not in seen:
            normalized.append(item)
            seen.add(item["token"])
    if len(normalized) < min_rows:
        raise ValueError(f"{provider} master validation failed: only {len(normalized)} normalized rows")
    return normalized


class BrokerMasterRefresher:
    def __init__(self, directory: MarketInstrumentDirectory):
        self.directory = directory
        self.client = httpx.AsyncClient(timeout=90, follow_redirects=True,
                                        headers={"User-Agent": "AIR-Model-Engine/1.0"})

    def urls_for(self, provider: str) -> list[str]:
        configured = json.loads(os.getenv("AIR_BROKER_MASTER_URLS", "{}"))
        value = configured.get(provider) or DEFAULT_MASTER_URLS.get(provider) or ""
        values = value if isinstance(value, list) else [value]
        return [str(item).strip() for item in values if str(item).strip()]

    def url_for(self, provider: str) -> str:
        return self.urls_for(provider)[0] if self.urls_for(provider) else ""

    async def refresh(self, provider: str, account_id: str,
                      headers: dict[str, str] | None = None) -> dict[str, Any]:
        provider = provider.strip().lower()
        urls = self.urls_for(provider)
        if not urls:
            return {"provider": provider, "account_id": account_id,
                    "status": "NOT_CONFIGURED", "reason": "official_master_url_not_configured"}
        combined: dict[str, dict[str, Any]] = {}
        for url in urls:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            rows = parse_master(provider, response.content, url.split("?")[0], min_rows=0)
            for item in rows:
                combined[item["token"]] = item
        rows = list(combined.values())
        if len(rows) < 100:
            raise ValueError(f"{provider} combined master validation failed: only {len(rows)} normalized rows")
        # Validate all URLs before atomically replacing the previous snapshot.
        imported = self.directory.replace_snapshot(provider, account_id, rows)
        return {"provider": provider, "account_id": account_id, "status": "REFRESHED",
                "rows": imported, "sources": urls,
                "refreshed_at": datetime.now(timezone.utc).isoformat()}

    async def close(self) -> None:
        await self.client.aclose()
