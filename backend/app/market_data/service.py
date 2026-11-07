"""Single normalized data gateway shared by AIR strategy and UI services."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from .contracts import HistoricalBar, MarketInstrument
from .hub import MarketDataHub
from .router import MarketDataRouter


class MarketDataService:
    """Provider-independent access to selected historical and live sources.

    Strategy modules should depend on this service, never on broker SDK clients.
    Provider failover is attempted only when the router has an enabled candidate.
    """

    def __init__(self, router: MarketDataRouter, hub: MarketDataHub):
        self.router = router
        self.hub = hub

    async def historical(self, instrument: MarketInstrument, start: datetime,
                         end: datetime, interval: str) -> list[HistoricalBar]:
        source = self.router.resolve("historical")
        if not source:
            raise RuntimeError("No connected historical market-data source")
        provider, account_id, adapter = source[0]
        try:
            bars = await adapter.get_historical(instrument, start, end, interval)
            return sorted(bars, key=lambda item: item.start_time)
        except Exception:
            await self.router.mark_unhealthy("historical", "historical_request_failed")
            result = await self.router.check_health("historical")
            if result.get("failover") != "switched":
                raise
            fallback = self.router.resolve("historical")
            if not fallback:
                raise RuntimeError("Historical source failover did not establish a connection")
            return sorted(
                await fallback[0][2].get_historical(instrument, start, end, interval),
                key=lambda item: item.start_time,
            )

    async def search_instruments(self, query: str, limit: int = 100,
                                 exchange_segment: str | None = None) -> list[MarketInstrument]:
        source = self.router.resolve("historical")
        if not source:
            source = self.router.resolve("live")
        if not source:
            raise RuntimeError("No connected market-data provider")
        return await source[0][2].search_instruments(query, limit, exchange_segment)

    async def subscribe(self, instruments: list[MarketInstrument]) -> dict:
        source = self.router.resolve("live")
        if not source:
            raise RuntimeError("No connected live market-data source")
        provider, account_id, adapter = source[0]
        try:
            await adapter.subscribe(instruments)
        except Exception:
            await self.router.mark_unhealthy("live", "subscription_failed")
            result = await self.router.check_health("live")
            if result.get("failover") != "switched":
                raise
            fallback = self.router.resolve("live")
            if not fallback:
                raise RuntimeError("Live source failover did not establish a connection")
            provider, account_id, adapter = fallback[0]
            await adapter.subscribe(instruments)
        return {"provider": provider, "account_id": account_id,
                "subscribed": len(instruments)}

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        source = self.router.resolve("live")
        if source:
            await source[0][2].unsubscribe(instruments)

    async def health(self) -> dict:
        historical = await self.router.check_health("historical")
        live = await self.router.check_health("live")
        return {"historical": historical, "live": live,
                "routing": self.router.status(), "stream": self.hub.status()}
