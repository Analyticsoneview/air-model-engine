"""AIR JSON market-data vendor connector.

This is a configurable adapter contract, not a claim that every vendor has the same
API. Vendors with a different schema require a small provider-specific subclass.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
import websockets

from app.market_data.contracts import HistoricalBar, MarketInstrument
from app.market_data.hub import MarketDataHub


def _timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, timezone.utc)
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


class GenericVendorMarketDataAdapter:
    provider_code = "custom_vendor"

    def __init__(self, account_id: str, credentials: dict[str, str], hub: MarketDataHub):
        self.account_id = account_id
        self.credentials = dict(credentials)
        self.hub = hub
        self.base_url = self.credentials["base_url"].rstrip("/")
        self.websocket_url = self.credentials["websocket_url"]
        if urlparse(self.base_url).scheme != "https" or urlparse(self.websocket_url).scheme != "wss":
            raise ValueError("Vendor endpoints must use HTTPS and WSS")
        header = self.credentials.get("auth_header", "Authorization")
        prefix = self.credentials.get("auth_prefix", "Bearer").strip()
        token = self.credentials["api_key"]
        self.headers = {header: f"{prefix} {token}".strip(), "Accept": "application/json"}
        self._http = httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=20)
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._instruments: dict[str, MarketInstrument] = {}
        self._state = "not_connected"
        self._last_error: str | None = None
        self._last_tick_at: str | None = None
        self._stop = False
        self._send_lock = asyncio.Lock()

    async def authenticate(self, account_id: str) -> None:
        if account_id != self.account_id:
            raise ValueError("Vendor account ID mismatch")
        path = self.credentials.get("health_path", "/health")
        response = await self._http.get(path)
        response.raise_for_status()
        self._state = "connected"

    async def search_instruments(self, query: str, limit: int = 100,
                                 exchange_segment: str | None = None) -> list[MarketInstrument]:
        path = self.credentials.get("instruments_path", "/instruments")
        response = await self._http.get(path, params={"q": query, "limit": min(limit, 500),
                                                       "segment": exchange_segment or ""})
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("instruments", payload.get("data", payload)) if isinstance(payload, dict) else payload
        result = []
        for row in rows if isinstance(rows, list) else []:
            result.append(MarketInstrument(
                exchange=str(row["exchange"]), symbol=str(row["symbol"]),
                token=str(row["token"]), segment=str(row["segment"]),
                expiry=row.get("expiry"),
                strike=Decimal(str(row["strike"])) if row.get("strike") is not None else None,
                option_type=row.get("option_type"), lot_size=row.get("lot_size"),
                instrument_type=row.get("instrument_type"),
            ))
        return result

    async def get_historical(self, instrument: MarketInstrument, start: datetime,
                             end: datetime, interval: str) -> list[HistoricalBar]:
        path = self.credentials.get("historical_path", "/history")
        response = await self._http.get(path, params={
            "token": instrument.token, "symbol": instrument.symbol,
            "from": start.isoformat(), "to": end.isoformat(), "interval": interval,
        })
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("candles", payload.get("bars", payload.get("data", payload))) if isinstance(payload, dict) else payload
        result = []
        for row in rows if isinstance(rows, list) else []:
            result.append(HistoricalBar(
                provider=self.provider_code, exchange=instrument.exchange,
                symbol=instrument.symbol, interval=interval,
                start_time=_timestamp(row.get("time") or row.get("timestamp") or row.get("date")),
                open=Decimal(str(row["open"])), high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])), close=Decimal(str(row["close"])),
                volume=int(row["volume"]) if row.get("volume") is not None else None,
                open_interest=int(row["open_interest"]) if row.get("open_interest") is not None else None,
            ))
        return result

    async def _connect(self) -> None:
        self._ws = await websockets.connect(
            self.websocket_url, additional_headers=self.headers,
            ping_interval=20, ping_timeout=20, close_timeout=5,
        )
        if self._instruments:
            await self._send_subscribe(list(self._instruments.values()))
        self._state = "connected"
        self._last_error = None
        self._reader = asyncio.create_task(self._read_loop(), name=f"air-vendor-ws-{self.account_id}")

    async def _send_subscribe(self, instruments: list[MarketInstrument]) -> None:
        async with self._send_lock:
            await self._ws.send(json.dumps({
                "action": "subscribe", "tokens": [item.token for item in instruments],
            }))

    async def _read_loop(self) -> None:
        delay = 1.0
        while not self._stop:
            try:
                async for raw in self._ws:
                    payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                    rows = payload if isinstance(payload, list) else [payload]
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        token = str(row.get("token") or row.get("instrument_token") or "")
                        instrument = self._instruments.get(token)
                        if not instrument or row.get("ltp") is None:
                            continue
                        received = datetime.now(timezone.utc).isoformat()
                        await self.hub.publish({
                            "provider": self.provider_code, "account_id": self.account_id,
                            "exchange": instrument.exchange, "symbol": instrument.symbol,
                            "token": token, "ltp": row.get("ltp"),
                            "open": row.get("open"), "high": row.get("high"),
                            "low": row.get("low"), "close": row.get("close"),
                            "volume": row.get("volume"), "open_interest": row.get("open_interest"),
                            "bid": row.get("bid"), "ask": row.get("ask"),
                            "exchange_time": row.get("timestamp"), "received_at": received,
                            "feed_type": "websocket",
                        })
                        self._last_tick_at = received
                raise RuntimeError("Vendor WebSocket closed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._state = "degraded"
                self._last_error = type(exc).__name__
                if self._stop:
                    break
                await asyncio.sleep(delay)
                delay = min(30.0, delay * 2)
                try:
                    await self._connect()
                    return
                except Exception as reconnect_error:
                    self._state = "outage"
                    self._last_error = type(reconnect_error).__name__

    async def subscribe(self, instruments: list[MarketInstrument]) -> None:
        if not instruments:
            raise ValueError("At least one vendor instrument is required")
        self._instruments.update({item.token: item for item in instruments})
        if self._ws is None or self._ws.closed:
            await self._connect()
        else:
            await self._send_subscribe(instruments)

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        tokens = [item.token for item in instruments]
        if self._ws is not None and not self._ws.closed:
            async with self._send_lock:
                await self._ws.send(json.dumps({"action": "unsubscribe", "tokens": tokens}))
        for token in tokens:
            self._instruments.pop(token, None)

    def health(self) -> dict[str, Any]:
        state = self._state
        if self._instruments and self._last_tick_at:
            age = (datetime.now(timezone.utc) - _timestamp(self._last_tick_at)).total_seconds()
            if age > 30 and state == "connected":
                state = "stale"
        return {
            "provider": self.provider_code, "account_id": self.account_id,
            "feed_state": state, "feed_mode": "vendor_json_websocket",
            "websocket_open": self._ws is not None and not self._ws.closed,
            "subscribed_instruments": len(self._instruments),
            "last_tick_at": self._last_tick_at, "last_error_type": self._last_error,
        }

    async def close(self) -> None:
        self._stop = True
        if self._reader:
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
            self._reader = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        await self._http.aclose()
        self._state = "disconnected"
