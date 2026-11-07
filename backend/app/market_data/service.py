"""Single normalized data gateway shared by AIR strategy and UI services."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from .contracts import HistoricalBar, MarketInstrument
from .hub import MarketDataHub
from .router import MarketDataRouter
from .instrument_registry import MarketInstrumentDirectory


class MarketDataService:
    """Provider-independent access to selected historical and live sources.

    Strategy modules should depend on this service, never on broker SDK clients.
    Provider failover is attempted only when the router has an enabled candidate.
    """

    def __init__(self, router: MarketDataRouter, hub: MarketDataHub,
                 instruments: MarketInstrumentDirectory | None = None):
        self.router = router
        self.hub = hub
        self.instruments = instruments

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

    async def hydrate_strategy_ledger(self, ledger: Any, customer_id: str,
                                      as_of: str) -> dict[str, Any]:
        """Hydrate missing option EOD evidence through the selected normalized provider."""
        if self.instruments is None:
            return {"status": "SKIPPED", "reason": "instrument_directory_not_configured"}
        source = self.router.resolve("historical")
        if not source:
            return {"status": "SKIPPED", "reason": "no_historical_source"}
        provider, account_id, adapter = source[0]
        cutoff = date.fromisoformat(as_of)
        rows = ledger.list_signals(customer_id, 2000)
        cache: dict[tuple[str, str, str, str], MarketInstrument | None] = {}
        matched = updated = added = skipped = 0
        for row in rows:
            option_type = str(row.get("option_type") or "").upper()
            if option_type not in {"CE", "PE"} or row.get("strike") is None or not row.get("expiry"):
                skipped += 1
                continue
            symbol, expiry = str(row.get("symbol") or "").upper(), str(row["expiry"])[:10]
            strike = Decimal(str(row["strike"]))
            key = (symbol, expiry, str(strike), option_type)
            if key not in cache:
                candidates = self.instruments.search(provider, account_id, symbol, 500)
                found = [item for item in candidates
                         if str(item.get("expiry") or "")[:10] == expiry
                         and str(item.get("option_type") or "").upper() == option_type
                         and item.get("strike") is not None
                         and Decimal(str(item["strike"])) == strike]
                if found:
                    item = found[0]
                    cache[key] = MarketInstrument(
                        exchange=item["exchange"], symbol=item["symbol"], token=item["token"],
                        segment=item["segment"], expiry=item.get("expiry"), strike=strike,
                        option_type=option_type, lot_size=item.get("lot_size"),
                        instrument_type=item.get("instrument_type"))
                else:
                    cache[key] = None
            instrument = cache[key]
            if instrument is None:
                skipped += 1
                continue
            start = datetime.combine(date.fromisoformat(str(row["signal_date"])[:10]),
                                     time.min, tzinfo=timezone.utc)
            end = datetime.combine(cutoff + timedelta(days=1), time.min, tzinfo=timezone.utc)
            try:
                bars = await adapter.get_historical(instrument, start, end, "day")
            except Exception:
                skipped += 1
                continue
            if not bars:
                skipped += 1
                continue
            matched += 1
            payload = [{"date": bar.start_time.date().isoformat(), "open": str(bar.open),
                        "high": str(bar.high), "low": str(bar.low), "close": str(bar.close),
                        "volume": bar.volume, "open_interest": bar.open_interest}
                       for bar in bars]
            added_count = ledger.attach_market_data_bars(
                row["signal_id"], payload,
                {"provider": provider, "account_id": account_id, "interval": "day",
                 "retrieved_at": datetime.now(timezone.utc).isoformat()})
            if added_count:
                updated += 1
                added += added_count
        return {"status": "COMPLETED", "provider": provider, "account_id": account_id,
                "signals_seen": len(rows), "contracts_matched": matched,
                "strategy_records_updated": updated, "daily_bars_added": added,
                "skipped": skipped}

    async def health(self) -> dict:
        historical = await self.router.check_health("historical")
        live = await self.router.check_health("live")
        return {"historical": historical, "live": live,
                "routing": self.router.status(), "stream": self.hub.status()}
