"""DhanHQ market-data adapter wired to AIR's normalized tick hub."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.brokers.dhan import DhanHQClient
from app.brokers.dhan_instruments import DhanInstrumentMaster
from app.brokers.dhan_socket import DhanFeedSocket, SEGMENT_CODES
from app.market_data.contracts import HistoricalBar, MarketInstrument
from app.market_data.hub import MarketDataHub

SEGMENT_NAMES = {value: key for key, value in SEGMENT_CODES.items()}


class DhanMarketDataAdapter:
    provider_code = "dhan"

    def __init__(self, client_id: str, access_token: str, hub: MarketDataHub):
        self.client_id = client_id
        self.access_token = access_token
        self.hub = hub
        self.account_id: str | None = None
        self._rest: DhanHQClient | None = None
        self._master = DhanInstrumentMaster()
        self._feed: DhanFeedSocket | None = None
        self._reader: asyncio.Task | None = None
        self._symbols: dict[tuple[str, str], str] = {}
        self._subscriptions: dict[tuple[str, str], MarketInstrument] = {}
        self._feed_state = "not_connected"
        self._last_feed_error: str | None = None

    async def authenticate(self, account_id: str) -> None:
        self.account_id = account_id
        self._rest = DhanHQClient(self.client_id, self.access_token)
        await self._rest.profile()
        self._feed = DhanFeedSocket(self.client_id, self.access_token, mode="full")
        await self._feed.connect()
        self._feed_state = "connected"
        self._last_feed_error = None
        self._reader = asyncio.create_task(self._read_feed(), name=f"dhan-feed-{account_id}")

    async def _read_feed(self) -> None:
        retry_delay = 1.0
        while self._feed is not None:
            try:
                async for packet in self._feed.messages():
                    kind = packet.get("type")
                    if kind not in {"ticker", "quote", "full"}:
                        continue
                    segment = SEGMENT_NAMES.get(packet.get("exchange_segment_id"), "UNKNOWN")
                    security_id = str(packet.get("security_id", ""))
                    symbol = self._symbols.get((segment, security_id), security_id)
                    tick: dict[str, Any] = {
                        "provider": "dhan", "account_id": self.account_id,
                        "exchange": segment, "symbol": symbol, "token": security_id,
                        "ltp": packet.get("ltp"),
                        "exchange_time": packet.get("exchange_time"),
                        "received_at": datetime.now(timezone.utc).isoformat(),
                        "volume": packet.get("volume"),
                        "open_interest": packet.get("open_interest"),
                        "open": packet.get("open"), "high": packet.get("high"),
                        "low": packet.get("low"), "close": packet.get("close"),
                        "bid": packet.get("depth", [{}])[0].get("bid_price") if packet.get("depth") else None,
                        "ask": packet.get("depth", [{}])[0].get("ask_price") if packet.get("depth") else None,
                        "feed_type": kind,
                    }
                    await self.hub.publish(tick)
                raise RuntimeError("Dhan market feed closed")
            except asyncio.CancelledError:
                self._feed_state = "disconnected"
                raise
            except Exception as exc:
                self._feed_state = "reconnecting"
                self._last_feed_error = type(exc).__name__
                old_feed = self._feed
                try:
                    await old_feed.close()
                except Exception:
                    pass
                await asyncio.sleep(retry_delay)
                try:
                    if self._feed is not old_feed:
                        continue
                    replacement = DhanFeedSocket(self.client_id, self.access_token, mode="full")
                    await replacement.connect()
                    self._feed = replacement
                    if self._subscriptions:
                        requests = [
                            {"exchange_segment": item.segment, "security_id": str(item.token)}
                            for item in self._subscriptions.values()
                        ]
                        for offset in range(0, len(requests), 5000):
                            await replacement.subscribe(requests[offset:offset + 5000])
                    self._feed_state = "connected"
                    self._last_feed_error = None
                    retry_delay = 1.0
                except asyncio.CancelledError:
                    raise
                except Exception as reconnect_error:
                    self._feed_state = "error"
                    self._last_feed_error = type(reconnect_error).__name__
                    retry_delay = min(30.0, retry_delay * 2)

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_code,
            "account_id": self.account_id,
            "feed_state": self._feed_state,
            "reader_running": self._reader is not None and not self._reader.done(),
            "subscribed_instruments": len(self._subscriptions),
            "last_error_type": self._last_feed_error,
        }

    async def search_instruments(self, query: str, limit: int = 100, exchange_segment: str | None = None) -> list[MarketInstrument]:
        rows = await self._master.search(query, limit=limit, exchange_segment=exchange_segment)
        return [
            MarketInstrument(
                exchange=row["exchange"], symbol=row["symbol"], token=row["token"],
                segment=row["segment"], expiry=row["expiry"], strike=row["strike"],
                option_type=row["option_type"], lot_size=row["lot_size"],
                instrument_type=row["instrument_type"], expiry_code=row["expiry_code"],
            )
            for row in rows
        ]

    async def get_historical(self, instrument: MarketInstrument, start: datetime,
                             end: datetime, interval: str) -> list[HistoricalBar]:
        if self._rest is None:
            raise RuntimeError("Dhan REST session is not authenticated")
        if interval in {"day", "1d", "D"}:
            raw = await self._rest.historical_daily(
                security_id=instrument.token, exchange_segment=instrument.segment,
                instrument=instrument.instrument_type or "EQUITY", expiry_code=instrument.expiry_code or 0,
                from_date=start.strftime("%Y-%m-%d"),
                to_date=end.strftime("%Y-%m-%d"),
            )
        else:
            interval_minutes = int(interval.replace("minute", "").replace("m", ""))
            raw = await self._rest.historical_intraday(
                security_id=instrument.token, exchange_segment=instrument.segment,
                instrument=instrument.instrument_type or "EQUITY", interval=interval_minutes,
                from_date=start.strftime("%Y-%m-%d %H:%M:%S"),
                to_date=end.strftime("%Y-%m-%d %H:%M:%S"),
            )
        timestamps = raw.get("timestamp", [])
        opens, highs = raw.get("open", []), raw.get("high", [])
        lows, closes = raw.get("low", []), raw.get("close", [])
        volumes, ois = raw.get("volume", []), raw.get("openInterest", [])
        bars = []
        for i, stamp in enumerate(timestamps):
            bars.append(HistoricalBar(
                provider="dhan", exchange=instrument.exchange, symbol=instrument.symbol,
                interval=interval, start_time=datetime.fromtimestamp(int(stamp), timezone.utc),
                open=Decimal(str(opens[i])), high=Decimal(str(highs[i])),
                low=Decimal(str(lows[i])), close=Decimal(str(closes[i])),
                volume=int(volumes[i]) if i < len(volumes) else None,
                open_interest=int(ois[i]) if i < len(ois) else None,
            ))
        return bars

    async def subscribe(self, instruments: list[MarketInstrument]) -> None:
        if self._feed is None:
            raise RuntimeError("Dhan feed is not connected")
        request = []
        for instrument in instruments:
            segment = instrument.segment
            if segment not in SEGMENT_CODES:
                raise ValueError(f"Unsupported Dhan exchange segment: {segment}")
            self._symbols[(segment, str(instrument.token))] = instrument.symbol
            self._subscriptions[(segment, str(instrument.token))] = instrument
            request.append({"exchange_segment": segment, "security_id": str(instrument.token)})
        await self._feed.subscribe(request)

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        if self._feed is None:
            return
        await self._feed.unsubscribe([
            {"exchange_segment": item.segment, "security_id": str(item.token)}
            for item in instruments
        ])
        for item in instruments:
            key = (item.segment, str(item.token))
            self._subscriptions.pop(key, None)
            self._symbols.pop(key, None)

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
            self._reader = None
        if self._feed is not None:
            await self._feed.close()
            self._feed = None
        self._feed_state = "disconnected"
        self._subscriptions.clear()
        self._symbols.clear()
        if self._rest is not None:
            await self._rest.close()
            self._rest = None
        await self._master.close()
