"""Normalized REST-history and live-quote polling adapters for AIR broker providers.

Live quote polling is deliberately labelled as polling, not a WebSocket tick feed.
Provider rate limits apply; subscriptions are batched and the poll interval is
configurable. Dhan retains its native WebSocket adapter.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.brokers.zerodha import KiteConnectClient
from app.brokers.upstox import UpstoxClient
from app.brokers.fyers import FyersClient
from app.brokers.angel import AngelSmartAPI
from app.market_data.contracts import HistoricalBar, MarketInstrument
from app.market_data.hub import MarketDataHub
from app.market_data.session import nse_regular_session_active


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000
        stamp = datetime.fromtimestamp(numeric, timezone.utc)
    else:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return stamp.astimezone(timezone.utc)


class BrokerPollingAdapter:
    provider_code = "unknown"
    def __init__(self, account_id: str, hub: MarketDataHub, poll_seconds: float = 3.0):
        self.account_id = account_id
        self.hub = hub
        self.poll_seconds = max(2.0, poll_seconds)
        self._symbols: dict[str, MarketInstrument] = {}
        self._poller: asyncio.Task | None = None
        self._state = "not_connected"
        self._last_error: str | None = None
        self._last_tick_at: str | None = None

    async def authenticate(self, account_id: str) -> None:
        if account_id != self.account_id:
            raise ValueError("Adapter account ID mismatch")
        await self._authenticate()
        self._state = "connected"

    async def _authenticate(self) -> None:
        raise NotImplementedError

    async def _quotes(self, instruments: list[MarketInstrument]) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def get_historical(self, instrument: MarketInstrument, start: datetime,
                             end: datetime, interval: str) -> list[HistoricalBar]:
        raise NotImplementedError

    async def search_instruments(self, query: str, limit: int = 100,
                                 exchange_segment: str | None = None) -> list[MarketInstrument]:
        raise RuntimeError(
            f"{self.provider_code} instrument master search is not configured; "
            "use a verified broker instrument token from the provider instrument master"
        )

    async def subscribe(self, instruments: list[MarketInstrument]) -> None:
        if not instruments:
            raise ValueError("At least one instrument is required")
        for item in instruments:
            if not item.token or not item.symbol:
                raise ValueError("Instrument symbol and provider token are required")
            self._symbols[item.token] = item
        if self._poller is None or self._poller.done():
            self._poller = asyncio.create_task(self._poll_loop(), name=f"{self.provider_code}-quote-poll")

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        for item in instruments:
            self._symbols.pop(item.token, None)
        if not self._symbols and self._poller is not None:
            self._poller.cancel()
            try:
                await self._poller
            except asyncio.CancelledError:
                pass
            self._poller = None

    async def _poll_loop(self) -> None:
        retry_delay = self.poll_seconds
        while self._symbols:
            try:
                items = list(self._symbols.values())
                for start in range(0, len(items), self.batch_size):
                    batch = items[start:start + self.batch_size]
                    for quote in await self._quotes(batch):
                        token = str(quote.get("token") or quote.get("symbol_token") or "")
                        instrument = self._symbols.get(token)
                        if instrument is None and quote.get("symbol"):
                            symbol_key = str(quote["symbol"])
                            instrument = next((item for item in self._symbols.values()
                                if item.symbol == symbol_key or f"{item.exchange}:{item.symbol}" == symbol_key), None)
                            if instrument is not None:
                                token = instrument.token
                        if instrument is None:
                            continue
                        tick = {
                            "provider": self.provider_code, "account_id": self.account_id,
                            "exchange": instrument.exchange, "symbol": instrument.symbol,
                            "token": token, "ltp": quote.get("ltp"),
                            "open": quote.get("open"), "high": quote.get("high"),
                            "low": quote.get("low"), "close": quote.get("close"),
                            "volume": quote.get("volume"), "open_interest": quote.get("open_interest"),
                            "bid": quote.get("bid"), "ask": quote.get("ask"),
                            "received_at": datetime.now(timezone.utc).isoformat(),
                            "exchange_time": quote.get("exchange_time"),
                            "feed_type": "rest_quote_poll",
                        }
                        if tick["ltp"] is not None:
                            await self.hub.publish(tick)
                            self._last_tick_at = tick["received_at"]
                self._state = "connected"
                self._last_error = None
                retry_delay = self.poll_seconds
                await asyncio.sleep(self.poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._state = "degraded"
                self._last_error = type(exc).__name__
                await asyncio.sleep(retry_delay)
                retry_delay = min(30.0, retry_delay * 2)

    @property
    def batch_size(self) -> int:
        return 50

    def health(self) -> dict[str, Any]:
        state = self._state
        if self._symbols and self._last_tick_at:
            age = (datetime.now(timezone.utc) - _dt(self._last_tick_at)).total_seconds()
            if age > max(15.0, self.poll_seconds * 5) and state == "connected" and nse_regular_session_active():
                state = "stale"
        elif self._symbols and not self._last_tick_at and state == "connected":
            state = "awaiting_first_tick"
        return {
            "provider": self.provider_code, "account_id": self.account_id,
            "feed_state": state,
            "feed_mode": "REST quote polling",
            "poll_interval_seconds": self.poll_seconds,
            "subscribed_instruments": len(self._symbols),
            "reader_running": self._poller is not None and not self._poller.done(),
            "last_tick_at": self._last_tick_at, "last_error_type": self._last_error,
        }

    async def close(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
            try:
                await self._poller
            except asyncio.CancelledError:
                pass
            self._poller = None
        await self._close_client()
        self._symbols.clear()
        self._state = "disconnected"

    async def _close_client(self) -> None:
        raise NotImplementedError


class ZerodhaMarketDataAdapter(BrokerPollingAdapter):
    provider_code = "zerodha"
    batch_size = 500

    def __init__(self, account_id: str, api_key: str, access_token: str,
                 hub: MarketDataHub, poll_seconds: float = 3.0):
        super().__init__(account_id, hub, poll_seconds)
        self.client = KiteConnectClient(api_key, access_token)

    async def _authenticate(self):
        profile = await self.client.profile()
        user_id = str(profile.get("user_id", ""))
        if user_id and user_id != self.account_id:
            raise RuntimeError("Authenticated Kite account does not match assigned account")

    def _quote_key(self, item: MarketInstrument) -> str:
        return f"{item.exchange}:{item.symbol}"

    async def _quotes(self, instruments):
        data = await self.client.quotes([self._quote_key(x) for x in instruments], "quote")
        result = []
        for item in instruments:
            row = data.get(self._quote_key(item), {})
            depth = row.get("depth") or {}
            buy = (depth.get("buy") or [{}])[0]
            sell = (depth.get("sell") or [{}])[0]
            result.append({
                "token": item.token, "ltp": row.get("last_price"),
                "open": (row.get("ohlc") or {}).get("open"),
                "high": (row.get("ohlc") or {}).get("high"),
                "low": (row.get("ohlc") or {}).get("low"),
                "close": (row.get("ohlc") or {}).get("close"),
                "volume": row.get("volume"), "open_interest": row.get("oi"),
                "bid": buy.get("price"), "ask": sell.get("price"),
                "exchange_time": row.get("timestamp"),
            })
        return result

    async def get_historical(self, instrument, start, end, interval):
        candles = await self.client.historical(
            int(instrument.token), interval, start, end, oi=True
        )
        return [HistoricalBar(
            provider=self.provider_code, exchange=instrument.exchange,
            symbol=instrument.symbol, interval=interval, start_time=_dt(row[0]),
            open=Decimal(str(row[1])), high=Decimal(str(row[2])),
            low=Decimal(str(row[3])), close=Decimal(str(row[4])),
            volume=int(row[5]) if len(row) > 5 and row[5] is not None else None,
            open_interest=int(row[6]) if len(row) > 6 and row[6] is not None else None,
        ) for row in candles]

    async def _close_client(self):
        await self.client.close()


class UpstoxMarketDataAdapter(BrokerPollingAdapter):
    provider_code = "upstox"
    batch_size = 500

    def __init__(self, account_id: str, access_token: str, hub: MarketDataHub,
                 poll_seconds: float = 3.0):
        super().__init__(account_id, hub, poll_seconds)
        self.client = UpstoxClient(access_token)

    async def _authenticate(self):
        profile = await self.client.profile()
        user_id = str(profile.get("user_id", ""))
        if user_id and user_id != self.account_id:
            raise RuntimeError("Authenticated Upstox account does not match assigned account")

    async def _quotes(self, instruments):
        keys = [item.token for item in instruments]
        payload = await self.client.quotes(keys, "full")
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        result = []
        for item in instruments:
            row = data.get(item.token, {})
            ohlc = row.get("ohlc") or {}
            depth = row.get("depth") or row.get("market_level") or {}
            bids = depth.get("buy") or depth.get("bidAskQuote") or []
            asks = depth.get("sell") or []
            result.append({
                "token": item.token, "ltp": row.get("last_price") or row.get("ltp"),
                "open": ohlc.get("open"), "high": ohlc.get("high"),
                "low": ohlc.get("low"), "close": ohlc.get("close"),
                "volume": row.get("volume"), "open_interest": row.get("oi"),
                "bid": (bids[0].get("price") or bids[0].get("bidP")) if bids else None,
                "ask": (asks[0].get("price") or asks[0].get("askP")) if asks else None,
                "exchange_time": row.get("timestamp"),
            })
        return result

    async def get_historical(self, instrument, start, end, interval):
        unit, value = _upstox_interval(interval)
        payload = await self.client.historical(
            instrument.token, unit, value, end.date().isoformat(), start.date().isoformat()
        )
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        candles = data.get("candles", []) if isinstance(data, dict) else []
        return [HistoricalBar(
            provider=self.provider_code, exchange=instrument.exchange,
            symbol=instrument.symbol, interval=interval, start_time=_dt(row[0]),
            open=Decimal(str(row[1])), high=Decimal(str(row[2])),
            low=Decimal(str(row[3])), close=Decimal(str(row[4])),
            volume=int(row[5]) if len(row) > 5 and row[5] is not None else None,
            open_interest=int(row[6]) if len(row) > 6 and row[6] is not None else None,
        ) for row in candles]

    async def _close_client(self):
        await self.client.close()


class FyersMarketDataAdapter(BrokerPollingAdapter):
    provider_code = "fyers"
    batch_size = 50

    def __init__(self, account_id: str, app_id: str, access_token: str,
                 hub: MarketDataHub, poll_seconds: float = 3.0):
        super().__init__(account_id, hub, poll_seconds)
        self.client = FyersClient(app_id, access_token)

    async def _authenticate(self):
        profile = await self.client.profile()
        data = profile.get("data", profile) if isinstance(profile, dict) else {}
        user_id = str(data.get("fy_id") or data.get("id") or "")
        if user_id and user_id != self.account_id:
            raise RuntimeError("Authenticated FYERS account does not match assigned account")

    async def _quotes(self, instruments):
        payload = await self.client.quotes([item.token for item in instruments])
        rows = payload.get("d", []) if isinstance(payload, dict) else []
        result = []
        for row in rows:
            values = row.get("v", {})
            result.append({
                "symbol": row.get("n") or values.get("symbol"),
                "ltp": values.get("lp"), "open": values.get("open_price"),
                "high": values.get("high_price"), "low": values.get("low_price"),
                "close": values.get("prev_close_price"),
                "volume": values.get("volume"), "open_interest": values.get("oi"),
                "bid": values.get("bid"), "ask": values.get("ask"),
                "exchange_time": values.get("tt"),
            })
        return result

    async def get_historical(self, instrument, start, end, interval):
        resolution = _fyers_resolution(interval)
        payload = await self.client.history(
            instrument.token, resolution, "1", start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
        candles = payload.get("candles", []) if isinstance(payload, dict) else []
        return [HistoricalBar(
            provider=self.provider_code, exchange=instrument.exchange,
            symbol=instrument.symbol, interval=interval, start_time=_dt(row[0]),
            open=Decimal(str(row[1])), high=Decimal(str(row[2])),
            low=Decimal(str(row[3])), close=Decimal(str(row[4])),
            volume=int(row[5]) if len(row) > 5 and row[5] is not None else None,
            open_interest=None,
        ) for row in candles]

    async def _close_client(self):
        await self.client.close()


class AngelOneMarketDataAdapter(BrokerPollingAdapter):
    provider_code = "angelone"
    batch_size = 50

    def __init__(self, account_id: str, credentials: dict[str, str],
                 hub: MarketDataHub, network: dict[str, str],
                 poll_seconds: float = 3.0):
        super().__init__(account_id, hub, poll_seconds)
        self._credentials = dict(credentials)
        self.client = AngelSmartAPI(
            credentials["api_key"], account_id,
            client_local_ip=network["client_local_ip"],
            client_public_ip=network["client_public_ip"],
            mac_address=network["mac_address"],
            access_token=credentials["jwt_token"],
        )

    async def _authenticate(self):
        profile = await self.client.profile()
        code = str(profile.get("clientcode", self.account_id))
        if code.upper() != self.account_id.upper():
            raise RuntimeError("Authenticated Angel account does not match assigned account")

    async def _quotes(self, instruments):
        tokens: dict[str, list[str]] = {}
        for item in instruments:
            exchange_type = _angel_exchange_type(item.exchange, item.segment)
            tokens.setdefault(str(exchange_type), []).append(item.token)
        payload = await self.client.market_data("FULL", tokens)
        data = payload.get("fetched", []) if isinstance(payload, dict) else []
        by_token = {str(row.get("symbolToken")): row for row in data}
        result = []
        for item in instruments:
            row = by_token.get(item.token, {})
            depth = row.get(" depth") or row.get("depth") or {}
            buy = (depth.get("buy") or [{}])[0]
            sell = (depth.get("sell") or [{}])[0]
            result.append({
                "token": item.token, "ltp": row.get("ltp"),
                "open": row.get("open"), "high": row.get("high"),
                "low": row.get("low"), "close": row.get("close"),
                "volume": row.get("tradeVolume"), "open_interest": row.get("opnInterest"),
                "bid": buy.get("price"), "ask": sell.get("price"),
                "exchange_time": row.get("exchTradeTime"),
            })
        return result

    async def get_historical(self, instrument, start, end, interval):
        payload = await self.client.historical(
            instrument.exchange, instrument.token, _angel_interval(interval),
            start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"),
        )
        return [HistoricalBar(
            provider=self.provider_code, exchange=instrument.exchange,
            symbol=instrument.symbol, interval=interval, start_time=_dt(row[0]),
            open=Decimal(str(row[1])), high=Decimal(str(row[2])),
            low=Decimal(str(row[3])), close=Decimal(str(row[4])),
            volume=int(row[5]) if len(row) > 5 and row[5] is not None else None,
            open_interest=None,
        ) for row in payload]

    async def _close_client(self):
        await self.client.close()


def _upstox_interval(value: str) -> tuple[str, int]:
    normalized = value.lower().replace("minute", "m")
    if normalized in {"day", "1d", "d"}:
        return "days", 1
    if normalized.endswith("m") and normalized[:-1].isdigit():
        return "minutes", int(normalized[:-1])
    if normalized.endswith("h") and normalized[:-1].isdigit():
        return "hours", int(normalized[:-1])
    raise ValueError(f"Unsupported Upstox interval: {value}")


def _fyers_resolution(value: str) -> str:
    normalized = value.lower().replace("minute", "m")
    if normalized in {"day", "1d", "d"}:
        return "D"
    if normalized.endswith("m") and normalized[:-1].isdigit():
        return normalized[:-1]
    if normalized.endswith("h") and normalized[:-1].isdigit():
        return str(int(normalized[:-1]) * 60)
    raise ValueError(f"Unsupported FYERS interval: {value}")


def _angel_interval(value: str) -> str:
    normalized = value.lower().replace("minute", "m")
    mapping = {"1m":"ONE_MINUTE","3m":"THREE_MINUTE","5m":"FIVE_MINUTE",
               "10m":"TEN_MINUTE","15m":"FIFTEEN_MINUTE","30m":"THIRTY_MINUTE",
               "60m":"ONE_HOUR","day":"ONE_DAY","1d":"ONE_DAY","d":"ONE_DAY"}
    if normalized not in mapping:
        raise ValueError(f"Unsupported Angel interval: {value}")
    return mapping[normalized]


def _angel_exchange_type(exchange: str, segment: str) -> int:
    normalized = (segment or exchange).upper()
    mapping = {"NSE_EQ":1,"NSE":1,"NSE_FO":2,"NFO":2,
               "BSE_EQ":3,"BSE":3,"BSE_FO":4,"BFO":4,"MCX_COMM":5,"MCX":5}
    if normalized not in mapping:
        raise ValueError(f"Unsupported Angel exchange segment: {normalized}")
    return mapping[normalized]
