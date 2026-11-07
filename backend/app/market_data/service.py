"""Single normalized data gateway shared by AIR strategy and UI services."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import asyncio
import copy
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from .contracts import HistoricalBar, MarketInstrument
from .hub import MarketDataHub
from .router import MarketDataRouter
from .instrument_registry import MarketInstrumentDirectory


_DEFAULT_MARKET_DATA_SERVICE = None


def set_default_market_data_service(service):
    global _DEFAULT_MARKET_DATA_SERVICE
    _DEFAULT_MARKET_DATA_SERVICE = service


def get_default_market_data_service():
    if _DEFAULT_MARKET_DATA_SERVICE is None:
        raise RuntimeError("AIR market-data service has not been initialized")
    return _DEFAULT_MARKET_DATA_SERVICE


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
        self._subscriptions: dict[str, MarketInstrument] = {}

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
            await adapter.subscribe(list({item.token: item for item in
                [*self._subscriptions.values(), *instruments]}.values()))
        for item in instruments:
            self._subscriptions[item.token] = item
        return {"provider": provider, "account_id": account_id,
                "subscribed": len(instruments)}

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        source = self.router.resolve("live")
        if source:
            await source[0][2].unsubscribe(instruments)
        for item in instruments:
            self._subscriptions.pop(item.token, None)
        for item in instruments:
            self._subscriptions.pop(item.token, None)

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
                if not candidates:
                    try:
                        native = await adapter.search_instruments(symbol, limit=500)
                        candidates = [{
                            "exchange": item.exchange, "symbol": item.symbol, "token": item.token,
                            "segment": item.segment, "expiry": item.expiry,
                            "strike": str(item.strike) if item.strike is not None else None,
                            "option_type": item.option_type, "lot_size": item.lot_size,
                            "instrument_type": item.instrument_type,
                        } for item in native]
                    except Exception:
                        candidates = []
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
                bars = await self.historical(instrument, start, end, "day")
            except Exception:
                skipped += 1
                continue
            if not bars:
                skipped += 1
                continue
            matched += 1
            payload = [{"date": bar.start_time.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat(), "open": str(bar.open),
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

    async def hydrate_strategy_rows(self, rows: list[dict],
                                    *, max_contracts: int = 150) -> list[dict]:
        """Attach normalized provider history to strategy evidence without overwriting it.

        Strategy evaluators remain deterministic and broker-agnostic: they receive
        the same evidence.daily_option_bars shape regardless of the selected vendor.
        Existing verified bars take precedence; missing dates are filled only.
        """
        result = [copy.deepcopy(row) for row in rows]
        source = self.router.resolve("historical")
        if not source:
            return result
        provider, account_id, adapter = source[0]
        semaphore = asyncio.Semaphore(4)
        cache: dict[tuple[str, str, str], list[HistoricalBar]] = {}

        async def load_one(row: dict) -> None:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                return
            if not self.instruments:
                return
            mapped = self.instruments.search(provider, account_id, symbol, 200)
            if not mapped:
                try:
                    candidates = await adapter.search_instruments(symbol, limit=200)
                    mapped = [item.__dict__ for item in candidates]
                except Exception:
                    return
            expiry = str(row.get("expiry") or "")[:10]
            option_type = str(row.get("option_type") or "").upper()
            strike = row.get("strike")
            chosen = []
            for item in mapped:
                if str(item.get("symbol") or "").upper() != symbol:
                    continue
                if not option_type and item.get("option_type"):
                    continue
                if option_type:
                    if str(item.get("option_type") or "").upper() != option_type:
                        continue
                    if expiry and str(item.get("expiry") or "")[:10] != expiry:
                        continue
                    try:
                        if strike is not None and Decimal(str(item.get("strike"))) != Decimal(str(strike)):
                            continue
                    except Exception:
                        continue
                chosen.append(item)
            if not chosen:
                return
            item = chosen[0]
            instrument = MarketInstrument(
                exchange=item["exchange"], symbol=item["symbol"], token=str(item["token"]),
                segment=item["segment"], expiry=item.get("expiry"),
                strike=Decimal(str(item["strike"])) if item.get("strike") is not None else None,
                option_type=item.get("option_type"), lot_size=item.get("lot_size"),
                instrument_type=item.get("instrument_type"),
            )
            start_text = str(row.get("signal_date") or row.get("entry_date") or "")[:10]
            if not start_text:
                return
            try:
                start_day = date.fromisoformat(start_text)
            except ValueError:
                return
            start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
            end = datetime.now(timezone.utc)
            cache_key = (instrument.token, start_text, end.date().isoformat())
            async with semaphore:
                try:
                    bars = cache.get(cache_key)
                    if bars is None:
                        bars = await self.historical(instrument, start, end, "day")
                        cache[cache_key] = bars
                except Exception:
                    return
            evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
            existing = evidence.get("daily_option_bars") or evidence.get("daily_bars") or []
            by_date = {
                str(bar.get("date") or bar.get("trade_date") or "")[:10]: bar
                for bar in existing if isinstance(bar, dict)
                and (bar.get("date") or bar.get("trade_date"))
            }
            for bar in bars:
                day = bar.start_time.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
                by_date.setdefault(day, {
                    "date": day, "open": float(bar.open), "high": float(bar.high),
                    "low": float(bar.low), "close": float(bar.close),
                    "quantity": bar.volume, "volume": bar.volume,
                    "open_interest": bar.open_interest,
                    "source": provider,
                })
            evidence["daily_option_bars"] = [by_date[key] for key in sorted(by_date)]
            evidence["market_data_source"] = {
                "provider": provider, "account_id": account_id,
                "instrument_token": instrument.token,
                "normalized_by": "AIR_MARKET_DATA_SERVICE",
            }
            row["evidence"] = evidence

        tasks = [load_one(row) for row in result[:max_contracts]]
        await asyncio.gather(*tasks)
        return result

    async def health(self) -> dict:
        historical = await self.router.check_health("historical")
        live = await self.router.check_health("live")
        if live.get("failover") == "switched" and self._subscriptions:
            source = self.router.resolve("live")
            if source:
                await source[0][2].subscribe(list(self._subscriptions.values()))
        return {"historical": historical, "live": live,
                "routing": self.router.status(), "stream": self.hub.status()}
