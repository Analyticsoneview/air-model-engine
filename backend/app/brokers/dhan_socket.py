"""DhanHQ v2 live WebSocket transport for normalized feed packets."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlencode
from typing import Any, AsyncIterator

import websockets

from app.brokers.dhan_feed import decode_dhan_message

FEED_URL = "wss://api-feed.dhan.co"
SEGMENT_CODES = {
    "IDX_I": 0, "NSE_EQ": 1, "NSE_FNO": 2, "NSE_CURRENCY": 3,
    "BSE_EQ": 4, "MCX_COMM": 5, "BSE_CURRENCY": 7, "BSE_FNO": 8,
}
REQUEST_CODES = {"ticker": 15, "quote": 17, "full": 21}


class DhanFeedSocket:
    """Single Dhan feed connection; caller owns lifecycle and subscription scope."""

    def __init__(self, client_id: str, access_token: str,
                 *, mode: str = "full", max_instruments: int = 5000):
        if mode not in REQUEST_CODES:
            raise ValueError("mode must be ticker, quote or full")
        if not client_id.strip() or not access_token.strip():
            raise ValueError("client_id and access_token are required")
        if not 1 <= max_instruments <= 5000:
            raise ValueError("Dhan supports at most 5000 instruments per connection")
        self.client_id = client_id.strip()
        self.access_token = access_token.strip()
        self.mode = mode
        self.max_instruments = max_instruments
        self._socket: Any = None

    async def connect(self) -> None:
        if self._socket is not None:
            raise RuntimeError("Dhan feed socket is already connected")
        query = urlencode({
            "version": "2", "token": self.access_token,
            "clientId": self.client_id, "authType": "2",
        })
        self._socket = await websockets.connect(
            f"{FEED_URL}?{query}", ping_interval=20, ping_timeout=20,
            close_timeout=5, max_size=2**20,
        )

    async def subscribe(self, instruments: list[dict[str, str]]) -> None:
        if self._socket is None:
            raise RuntimeError("Connect the Dhan feed before subscribing")
        if not instruments or len(instruments) > self.max_instruments:
            raise ValueError(f"Supply 1 to {self.max_instruments} instruments")
        normalized = []
        seen = set()
        for item in instruments:
            segment = item.get("exchange_segment", "")
            security_id = str(item.get("security_id", "")).strip()
            if segment not in SEGMENT_CODES or not security_id.isdigit():
                raise ValueError("Each instrument needs a supported exchange_segment and numeric security_id")
            key = (segment, security_id)
            if key not in seen:
                normalized.append({"ExchangeSegment": segment, "SecurityId": security_id})
                seen.add(key)
        for start in range(0, len(normalized), 100):
            batch = normalized[start:start + 100]
            await self._socket.send(json.dumps({
                "RequestCode": REQUEST_CODES[self.mode],
                "InstrumentCount": len(batch),
                "InstrumentList": batch,
            }))

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        if self._socket is None:
            raise RuntimeError("Dhan feed is not connected")
        async for message in self._socket:
            if isinstance(message, bytes):
                for packet in decode_dhan_message(message):
                    yield packet
            elif isinstance(message, str):
                # Control messages are surfaced without interpreting them as prices.
                try:
                    yield {"type": "control", "payload": json.loads(message)}
                except json.JSONDecodeError:
                    yield {"type": "control", "payload": message}

    async def close(self) -> None:
        socket, self._socket = self._socket, None
        if socket is not None:
            try:
                await socket.send(json.dumps({"RequestCode": 12}))
            except Exception:
                pass
            await socket.close()
