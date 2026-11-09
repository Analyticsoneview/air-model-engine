import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
import inspect
from fastapi import WebSocket

def _json_value(value: Any) -> Any:
    if isinstance(value, (Decimal, datetime)):
        return str(value)
    return value

class MarketDataHub:
    """Fan out normalized ticks to connected AIR clients."""
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.last_tick_at: datetime | None = None
        self.tick_count = 0
        self._tick_counts_by_token: dict[str, int] = {}
        self._latest_by_token: dict[str, dict[str, Any]] = {}
        self._listeners: set[Callable[[dict[str, Any]], Any]] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    def add_listener(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        self._listeners.add(callback)

    def remove_listener(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        self._listeners.discard(callback)

    async def publish(self, tick: dict[str, Any]) -> None:
        self.last_tick_at = datetime.now(timezone.utc)
        self.tick_count += 1
        token = str(tick.get("token") or "")
        if token:
            self._tick_counts_by_token[token] = self._tick_counts_by_token.get(token, 0) + 1
            self._latest_by_token[token] = dict(tick)
        for callback in tuple(self._listeners):
            try:
                result = callback(dict(tick))
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # A strategy listener must never interrupt broker tick delivery.
                continue
        payload = json.dumps(tick, default=_json_value)
        async with self._lock:
            clients = list(self._clients)
        stale = []
        for client in clients:
            try:
                await client.send_text(payload)
            except Exception:
                stale.append(client)
        if stale:
            async with self._lock:
                for client in stale:
                    self._clients.discard(client)

    def tick_count_for(self, token: str) -> int:
        return self._tick_counts_by_token.get(str(token), 0)

    def latest_for(self, token: str) -> dict[str, Any] | None:
        return self._latest_by_token.get(str(token))

    def status(self) -> dict[str, Any]:
        return {"connected_clients": len(self._clients), "tick_count": self.tick_count,
                "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None}
