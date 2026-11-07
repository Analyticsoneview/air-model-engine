"""Native broker market-data WebSocket adapters.

Each SDK is imported lazily so the AIR API can still start when an optional broker
SDK is not installed. Callback threads publish only normalized ticks to MarketDataHub.
REST historical candle methods are inherited from broker_adapters.py.
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from app.market_data.broker_adapters import (
    AngelOneMarketDataAdapter, FyersMarketDataAdapter,
    UpstoxMarketDataAdapter, ZerodhaMarketDataAdapter,
)
from app.market_data.contracts import MarketInstrument


def _price(value: Any, *, scale: Decimal = Decimal("1")) -> str | None:
    if value is None or value == "":
        return None
    try:
        return str(Decimal(str(value)) / scale)
    except Exception:
        return None


class _NativeStreamMixin:
    _stream: Any = None
    _stream_thread: threading.Thread | None = None
    _loop: asyncio.AbstractEventLoop | None = None
    _opened: asyncio.Event | None = None
    _last_stream_error: str | None = None
    _stream_open = False

    def _init_stream(self) -> None:
        self._stream = None
        self._stream_thread = None
        self._loop = None
        self._opened = None
        self._last_stream_error = None
        self._stream_open = False
        self._stream_ready = False

    def _schedule_tick(self, tick: dict[str, Any]) -> None:
        if not self._loop or not tick.get("ltp"):
            return
        tick.setdefault("provider", self.provider_code)
        tick.setdefault("account_id", self.account_id)
        tick.setdefault("received_at", datetime.now(timezone.utc).isoformat())
        tick["feed_type"] = "websocket"
        future = asyncio.run_coroutine_threadsafe(self.hub.publish(tick), self._loop)
        def done(result):
            try:
                result.result()
                self._last_tick_at = tick["received_at"]
            except Exception as exc:
                self._last_stream_error = type(exc).__name__
        future.add_done_callback(done)

    def _set_open(self) -> None:
        self._stream_open = True
        self._state = "connected"
        self._last_stream_error = None
        self._stream_ready = True
        self._state = "connected"
        self._last_stream_error = None
        if self._loop and self._opened:
            self._loop.call_soon_threadsafe(self._opened.set)

    def _set_error(self, error: Any) -> None:
        self._last_stream_error = type(error).__name__ if not isinstance(error, str) else error
        self._stream_open = False
        self._state = "degraded"

    async def _wait_open(self, timeout: float = 20.0) -> None:
        try:
            await asyncio.wait_for(self._opened.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._state = "outage"
            raise RuntimeError(f"{self.provider_code} WebSocket did not open within {timeout:g}s") from exc
        self._state = "connected"
        self._stream_ready = True

    def health(self) -> dict[str, Any]:
        base = super().health()
        base.update({
            "feed_mode": "native_websocket",
            "websocket_open": self._stream_open,
            "reader_running": bool(self._stream_thread and self._stream_thread.is_alive()),
            "last_error_type": self._last_stream_error or base.get("last_error_type"),
        })
        return base

    async def close(self) -> None:
        stream = self._stream
        self._stream = None
        self._stream_open = False
        if stream is not None:
            try:
                await asyncio.to_thread(self._stop_stream, stream)
            except Exception:
                pass
        await super().close()

    def _stop_stream(self, stream: Any) -> None:
        raise NotImplementedError


class ZerodhaWebSocketAdapter(_NativeStreamMixin, ZerodhaMarketDataAdapter):
    async def authenticate(self, account_id: str) -> None:
        await super().authenticate(account_id)
        self._init_stream()
        self._loop = asyncio.get_running_loop()
        self._opened = asyncio.Event()
        try:
            from kiteconnect import KiteTicker
        except ImportError as exc:
            raise RuntimeError("Install kiteconnect to enable Zerodha WebSocket streaming") from exc

        ticker = KiteTicker(self.client.api_key, self.client.access_token,
                            reconnect=True, reconnect_max_tries=50,
                            reconnect_max_delay=30)

        def on_connect(ws, response):
            self._set_open()
            tokens = [int(item.token) for item in self._symbols.values()]
            if tokens:
                ws.subscribe(tokens)
                ws.set_mode(ws.MODE_FULL, tokens)

        def on_ticks(ws, ticks):
            for item in ticks:
                token = str(item.get("instrument_token", ""))
                instrument = self._symbols.get(token)
                if not instrument:
                    continue
                ohlc = item.get("ohlc") or {}
                depth = item.get("depth") or {}
                buy = (depth.get("buy") or [{}])[0]
                sell = (depth.get("sell") or [{}])[0]
                self._schedule_tick({
                    "exchange": instrument.exchange, "symbol": instrument.symbol,
                    "token": token, "ltp": _price(item.get("last_price")),
                    "open": _price(ohlc.get("open")), "high": _price(ohlc.get("high")),
                    "low": _price(ohlc.get("low")), "close": _price(ohlc.get("close")),
                    "volume": item.get("volume"), "open_interest": item.get("oi"),
                    "bid": _price(buy.get("price")), "ask": _price(sell.get("price")),
                    "exchange_time": str(item.get("exchange_timestamp") or ""),
                })

        ticker.on_connect = on_connect
        ticker.on_ticks = on_ticks
        ticker.on_close = lambda ws, code, reason: self._set_error("Kite WebSocket closed")
        ticker.on_error = lambda ws, code, reason: self._set_error(reason)
        self._stream = ticker
        self._stream_thread = threading.Thread(
            target=lambda: ticker.connect(threaded=False), daemon=True,
            name=f"air-kite-ws-{account_id}",
        )
        self._stream_thread.start()
        await self._wait_open()

    async def subscribe(self, instruments: list[MarketInstrument]) -> None:
        for item in instruments:
            self._symbols[str(item.token)] = item
        if not self._stream_ready:
            raise RuntimeError("Zerodha WebSocket is not ready")
        tokens = [int(item.token) for item in instruments]
        await asyncio.to_thread(self._stream.subscribe, tokens)
        await asyncio.to_thread(self._stream.set_mode, self._stream.MODE_FULL, tokens)

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        tokens = [int(item.token) for item in instruments]
        if self._stream:
            await asyncio.to_thread(self._stream.unsubscribe, tokens)
        for item in instruments:
            self._symbols.pop(str(item.token), None)

    def _stop_stream(self, stream: Any) -> None:
        stream.close()


class UpstoxWebSocketAdapter(_NativeStreamMixin, UpstoxMarketDataAdapter):
    async def authenticate(self, account_id: str) -> None:
        await super().authenticate(account_id)
        self._init_stream()
        self._loop = asyncio.get_running_loop()
        self._opened = asyncio.Event()
        try:
            import upstox_client
        except ImportError as exc:
            raise RuntimeError("Install upstox-python-sdk to enable Upstox WebSocket streaming") from exc

        configuration = upstox_client.Configuration()
        configuration.access_token = self.client.access_token
        api_client = upstox_client.ApiClient(configuration)
        streamer = upstox_client.MarketDataStreamerV3(api_client, [], "full")
        streamer.auto_reconnect(True, 2, 50)

        def on_message(message):
            try:
                payload = message if isinstance(message, dict) else json.loads(message)
                feeds = payload.get("feeds") or {}
                for key, data in feeds.items():
                    instrument = self._symbols.get(key)
                    if not instrument:
                        continue
                    node = data.get("fullFeed", {}).get("marketFF", data.get("fullFeed", {}))
                    ltpc = node.get("ltpc") or data.get("ltpc") or {}
                    market = node.get("marketOHLC") or {}
                    candles = market.get("ohlc") or []
                    day = next((x for x in candles if str(x.get("interval", "")).lower() in {"1d", "day"}), {})
                    depth = node.get("marketLevel", {}).get("bidAskQuote", [])
                    bid = depth[0].get("bidP") if depth else None
                    ask = depth[0].get("askP") if depth else None
                    self._schedule_tick({
                        "exchange": instrument.exchange, "symbol": instrument.symbol,
                        "token": instrument.token, "ltp": _price(ltpc.get("ltp")),
                        "open": _price(day.get("open")), "high": _price(day.get("high")),
                        "low": _price(day.get("low")), "close": _price(ltpc.get("cp")),
                        "volume": node.get("vtt") or node.get("volume"),
                        "open_interest": node.get("oi"), "bid": _price(bid), "ask": _price(ask),
                        "exchange_time": ltpc.get("ltt"),
                    })
            except Exception as exc:
                self._set_error(exc)

        def on_open():
            self._set_open()
            keys = [item.token for item in self._symbols.values()]
            if keys:
                streamer.subscribe(keys, "full")

        streamer.on("open", on_open)
        streamer.on("message", on_message)
        streamer.on("error", self._set_error)
        streamer.on("close", lambda *args: self._set_error("Upstox WebSocket closed"))
        self._stream = streamer
        self._stream_api_client = api_client
        self._stream_thread = threading.Thread(
            target=streamer.connect, daemon=True, name=f"air-upstox-ws-{account_id}"
        )
        self._stream_thread.start()
        await self._wait_open()

    async def subscribe(self, instruments: list[MarketInstrument]) -> None:
        for item in instruments:
            self._symbols[item.token] = item
        if not self._stream_ready:
            raise RuntimeError("Upstox WebSocket is not ready")
        keys = [item.token for item in instruments]
        await asyncio.to_thread(self._stream.subscribe, keys, "full")

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        keys = [item.token for item in instruments]
        if self._stream:
            await asyncio.to_thread(self._stream.unsubscribe, keys)
        for item in instruments:
            self._symbols.pop(item.token, None)

    def _stop_stream(self, stream: Any) -> None:
        stream.disconnect()
        if hasattr(self, "_stream_api_client"):
            self._stream_api_client.close()


class FyersWebSocketAdapter(_NativeStreamMixin, FyersMarketDataAdapter):
    async def authenticate(self, account_id: str) -> None:
        await super().authenticate(account_id)
        self._init_stream()
        self._loop = asyncio.get_running_loop()
        self._opened = asyncio.Event()
        try:
            from fyers_apiv3.FyersWebsocket import data_ws
        except ImportError as exc:
            raise RuntimeError("Install fyers-apiv3 to enable FYERS WebSocket streaming") from exc

        access = f"{self.client.app_id}:{self.client.access_token}"

        def on_connect():
            self._set_open()
            symbols = [item.symbol for item in self._symbols.values()]
            if symbols:
                self._stream.subscribe(symbols=symbols, data_type="SymbolUpdate")

        def on_message(message):
            try:
                payload = message if isinstance(message, dict) else json.loads(message)
                symbol = payload.get("symbol") or payload.get("n")
                values = payload.get("v") or payload
                instrument = next((x for x in self._symbols.values()
                    if x.symbol == symbol or f"{x.exchange}:{x.symbol}" == symbol), None)
                if not instrument:
                    return
                self._schedule_tick({
                    "exchange": instrument.exchange, "symbol": instrument.symbol,
                    "token": instrument.token, "ltp": _price(values.get("lp")),
                    "open": _price(values.get("open_price")),
                    "high": _price(values.get("high_price")),
                    "low": _price(values.get("low_price")),
                    "close": _price(values.get("prev_close_price")),
                    "volume": values.get("volume"), "open_interest": values.get("oi"),
                    "bid": _price(values.get("bid")), "ask": _price(values.get("ask")),
                    "exchange_time": values.get("tt"),
                })
            except Exception as exc:
                self._set_error(exc)

        socket = data_ws.FyersDataSocket(
            access_token=access, log_path="", litemode=False, write_to_file=False,
            reconnect=True, reconnect_retry=50, on_connect=on_connect,
            on_close=lambda *args: self._set_error("FYERS WebSocket closed"),
            on_error=self._set_error, on_message=on_message,
        )
        self._stream = socket
        self._stream_thread = threading.Thread(
            target=socket.connect, daemon=True, name=f"air-fyers-ws-{account_id}"
        )
        self._stream_thread.start()
        await self._wait_open()

    async def subscribe(self, instruments: list[MarketInstrument]) -> None:
        for item in instruments:
            self._symbols[item.token] = item
        if not self._stream_ready:
            raise RuntimeError("FYERS WebSocket is not ready")
        await asyncio.to_thread(
            self._stream.subscribe,
            symbols=[item.symbol for item in instruments], data_type="SymbolUpdate",
        )

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        symbols = [item.symbol for item in instruments]
        if self._stream:
            await asyncio.to_thread(
                self._stream.unsubscribe, symbols=symbols, data_type="SymbolUpdate"
            )
        for item in instruments:
            self._symbols.pop(item.token, None)

    def _stop_stream(self, stream: Any) -> None:
        if hasattr(stream, "close_connection"):
            stream.close_connection()


class AngelOneWebSocketAdapter(_NativeStreamMixin, AngelOneMarketDataAdapter):
    async def authenticate(self, account_id: str) -> None:
        await super().authenticate(account_id)
        self._init_stream()
        self._loop = asyncio.get_running_loop()
        self._opened = asyncio.Event()
        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        except ImportError as exc:
            raise RuntimeError("Install smartapi-python to enable Angel One WebSocket streaming") from exc
        credentials = self._credentials
        if not credentials.get("feed_token"):
            raise RuntimeError("Angel feed_token is required for SmartAPI WebSocket")
        socket = SmartWebSocketV2(
            credentials["jwt_token"], credentials["api_key"], account_id,
            credentials["feed_token"], max_retry_attempt=50,
            retry_strategy=1, retry_delay=2, retry_multiplier=2, retry_duration=60,
        )

        def on_open(ws):
            self._set_open()
            self._subscribe_angel(list(self._symbols.values()))

        def on_data(ws, message):
            try:
                payload = message if isinstance(message, dict) else json.loads(message)
                token = str(payload.get("token") or payload.get("symbolToken") or "")
                instrument = self._symbols.get(token)
                if not instrument:
                    return
                self._schedule_tick({
                    "exchange": instrument.exchange, "symbol": instrument.symbol,
                    "token": token,
                    "ltp": _price(payload.get("last_traded_price"), scale=Decimal("100")),
                    "open": _price(payload.get("open_price_of_the_day"), scale=Decimal("100")),
                    "high": _price(payload.get("high_price_of_the_day"), scale=Decimal("100")),
                    "low": _price(payload.get("low_price_of_the_day"), scale=Decimal("100")),
                    "close": _price(payload.get("closed_price"), scale=Decimal("100")),
                    "volume": payload.get("volume_trade_for_the_day"),
                    "open_interest": payload.get("open_interest"),
                    "exchange_time": payload.get("exchange_timestamp"),
                })
            except Exception as exc:
                self._set_error(exc)

        socket.on_open = on_open
        socket.on_data = on_data
        socket.on_error = lambda ws, error: self._set_error(error)
        socket.on_close = lambda ws: self._set_error("Angel One WebSocket closed")
        self._stream = socket
        self._stream_thread = threading.Thread(
            target=socket.connect, daemon=True, name=f"air-angel-ws-{account_id}"
        )
        self._stream_thread.start()
        await self._wait_open()

    def _subscribe_angel(self, instruments: list[MarketInstrument]) -> None:
        if not instruments:
            return
        groups: dict[int, list[str]] = {}
        for item in instruments:
            exchange_type = self._angel_exchange_type(item)
            groups.setdefault(exchange_type, []).append(item.token)
        token_list = [{"exchangeType": exchange, "tokens": tokens}
                      for exchange, tokens in groups.items()]
        self._stream.subscribe("AIRMDATA01", self._stream.SNAP_QUOTE, token_list)

    def _angel_exchange_type(self, item: MarketInstrument) -> int:
        segment = (item.segment or item.exchange).upper()
        mapping = {"NSE_EQ":1,"NSE":1,"NSE_FO":2,"NFO":2,
                   "BSE_EQ":3,"BSE":3,"BSE_FO":4,"BFO":4,"MCX_COMM":5,"MCX":5}
        if segment not in mapping:
            raise ValueError(f"Unsupported Angel exchange segment: {segment}")
        return mapping[segment]

    async def subscribe(self, instruments: list[MarketInstrument]) -> None:
        for item in instruments:
            self._symbols[item.token] = item
        if not self._stream_open:
            raise RuntimeError("Angel One WebSocket is not ready")
        await asyncio.to_thread(self._subscribe_angel, instruments)

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        if self._stream:
            groups: dict[int, list[str]] = {}
            for item in instruments:
                groups.setdefault(self._angel_exchange_type(item), []).append(item.token)
            tokens = [{"exchangeType": exchange, "tokens": values}
                      for exchange, values in groups.items()]
            await asyncio.to_thread(
                self._stream.unsubscribe, "AIRMDATA01", self._stream.SNAP_QUOTE, tokens
            )
        for item in instruments:
            self._symbols.pop(item.token, None)

    def _stop_stream(self, stream: Any) -> None:
        stream.close_connection()
