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

    async def _remap_instruments(self, provider: str, account_id: str, adapter: Any,
                                 instruments: list[MarketInstrument]) -> list[MarketInstrument]:
        """Resolve fallback tokens by contract identity; provider tokens are never reused."""
        result = []
        for original in instruments:
            rows = self.instruments.search(provider, account_id, original.symbol, 500) if self.instruments else []
            if not rows:
                try:
                    native = await adapter.search_instruments(original.symbol, limit=500)
                    rows = [{
                        "exchange": item.exchange, "symbol": item.symbol, "token": item.token,
                        "segment": item.segment, "expiry": item.expiry,
                        "strike": str(item.strike) if item.strike is not None else None,
                        "option_type": item.option_type, "lot_size": item.lot_size,
                        "instrument_type": item.instrument_type,
                    } for item in native]
                except Exception:
                    rows = []
            matches = []
            for row in rows:
                if str(row.get("symbol") or "").upper() != original.symbol.upper():
                    continue
                if original.option_type and str(row.get("option_type") or "").upper() != original.option_type.upper():
                    continue
                if original.expiry and str(row.get("expiry") or "")[:10] != str(original.expiry)[:10]:
                    continue
                if original.strike is not None:
                    try:
                        if Decimal(str(row.get("strike"))) != original.strike:
                            continue
                    except Exception:
                        continue
                if original.exchange and str(row.get("exchange") or "").upper() != original.exchange.upper():
                    continue
                matches.append(row)
            if not matches:
                raise RuntimeError(
                    f"Failover provider {provider} has no matching token for "
                    f"{original.symbol} {original.expiry or ''} {original.strike or ''} {original.option_type or ''}"
                )
            row = matches[0]
            result.append(MarketInstrument(
                exchange=row["exchange"], symbol=row["symbol"], token=str(row["token"]),
                segment=row["segment"], expiry=row.get("expiry"),
                strike=Decimal(str(row["strike"])) if row.get("strike") is not None else None,
                option_type=row.get("option_type"), lot_size=row.get("lot_size"),
                instrument_type=row.get("instrument_type")))
        return result

    async def historical(self, instrument: MarketInstrument, start: datetime,
                         end: datetime, interval: str) -> list[HistoricalBar]:
        source = self.router.resolve("historical")
        if not source:
            raise RuntimeError("No connected historical market-data source")
        provider, account_id, adapter = source[0]
        try:
            bars = await adapter.get_historical(instrument, start, end, interval)
            return sorted(bars, key=lambda item: item.start_time)
        except Exception as broker_error:
            await self.router.mark_unhealthy("historical", "historical_request_failed")
            result = await self.router.check_health("historical")
            if result.get("failover") == "switched":
                fallback = self.router.resolve("historical")
                if fallback:
                    fallback_provider, fallback_account, fallback_adapter = fallback[0]
                    mapped = await self._remap_instruments(
                        fallback_provider, fallback_account, fallback_adapter, [instrument])
                    return sorted(
                        await fallback_adapter.get_historical(mapped[0], start, end, interval),
                        key=lambda item: item.start_time,
                    )
            # Never present a failed broker request as broker data. Switch the
            # historical channel to official NSE EOD and remap by contract identity.
            try:
                if not self.router.is_registered("nse_bhavcopy", "official"):
                    raise RuntimeError("No customer NSE fallback is registered")
                await self.router.set_source("historical", "nse_bhavcopy", "official")
                nse_source = self.router.resolve("historical")
                if not nse_source:
                    raise RuntimeError("NSE historical fallback did not connect")
                nse_adapter = nse_source[0][2]
                segment = "NSE_FO" if "FO" in instrument.segment.upper() else "NSE_CM"
                candidates = await nse_adapter.search_instruments(
                    instrument.symbol, limit=200, exchange_segment=segment
                )
                match = next((item for item in candidates
                    if item.symbol.upper() == instrument.symbol.upper()
                    and (not instrument.expiry or str(item.expiry or "")[:10] == str(instrument.expiry)[:10])
                    and (instrument.strike is None or item.strike == instrument.strike)
                    and (not instrument.option_type or item.option_type == instrument.option_type)), None)
                if match is None:
                    raise RuntimeError("Matching NSE EOD instrument is unavailable")
                bars = await nse_adapter.get_historical(match, start, end, interval)
                state = getattr(self, "customer_market_data_status", None)
                if isinstance(state, dict):
                    state.update({
                        "effective_source": "NSE",
                        "connection_status": "unavailable",
                        "fallback_active": True,
                        "fallback_reason": "historical_request_failed",
                    })
                return sorted(bars, key=lambda item: item.start_time)
            except Exception as nse_error:
                raise RuntimeError(
                    "Broker historical data failed and NSE EOD fallback is unavailable"
                ) from nse_error

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
        except Exception as broker_error:
            await self.router.mark_unhealthy("live", "subscription_failed")
            result = await self.router.check_health("live")
            if result.get("failover") == "switched":
                fallback = self.router.resolve("live")
                if fallback:
                    provider, account_id, adapter = fallback[0]
                    all_instruments = list({(item.symbol, item.expiry, str(item.strike), item.option_type): item
                                            for item in [*self._subscriptions.values(), *instruments]}.values())
                    mapped = await self._remap_instruments(provider, account_id, adapter, all_instruments)
                    await adapter.subscribe(mapped)
            else:
                # NSE has no live feed. Clear the failed broker live route and
                # use NSE EOD as the only active strategy source.
                if not self.router.is_registered("nse_bhavcopy", "official"):
                    raise broker_error
                await self.router.clear_source("live")
                try:
                    await self.router.set_source("historical", "nse_bhavcopy", "official")
                except Exception:
                    pass
                state = getattr(self, "customer_market_data_status", None)
                if isinstance(state, dict):
                    state.update({
                        "effective_source": "NSE",
                        "connection_status": "unavailable",
                        "fallback_active": True,
                        "fallback_reason": "live_subscription_failed",
                    })
                raise RuntimeError(
                    "Broker live feed is unavailable; switched to NSE EOD fallback"
                ) from broker_error
        for item in instruments:
            self._subscriptions[item.token] = item
        return {"provider": provider, "account_id": account_id,
                "subscribed": len(instruments)}

    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None:
        source = self.router.resolve("live")
        if source:
            provider, account_id, adapter = source[0]
            mapped = await self._remap_instruments(provider, account_id, adapter, instruments)
            await adapter.unsubscribe(mapped)
        for item in instruments:
            self._subscriptions.pop(item.token, None)

    async def option_chain_snapshot(self, underlying_symbol: str, expiry: str,
                                    *, wait_seconds: float = 3.0) -> dict[str, Any]:
        """Build a provider-neutral option-chain snapshot from normalized live ticks.

        The selected provider must have a valid option instrument master in AIR's
        account-scoped mapping directory or implement native instrument search.
        """
        source = self.router.resolve("live")
        if not source:
            raise RuntimeError("No connected live market-data source")
        provider, account_id, adapter = source[0]
        symbol = underlying_symbol.strip().upper()
        mapped = []
        if self.instruments:
            mapped = [
                item for item in self.instruments.list_all(provider, account_id, limit=50000)
                if str(item.get("underlying_symbol") or item.get("symbol") or "").upper() == symbol
            ]
        if not mapped:
            native = await adapter.search_instruments(
                symbol, limit=500, exchange_segment="NSE_FO"
            )
            mapped = [{
                "exchange": x.exchange, "symbol": x.symbol, "token": x.token,
                "segment": x.segment, "expiry": x.expiry,
                "strike": str(x.strike) if x.strike is not None else None,
                "option_type": x.option_type, "lot_size": x.lot_size,
                "instrument_type": x.instrument_type,
            } for x in native]
        options = []
        underlying = None
        for item in mapped:
            if str(item.get("underlying_symbol") or item.get("symbol") or "").upper() != symbol:
                continue
            side = str(item.get("option_type") or "").upper()
            if side in {"CE", "PE"} and str(item.get("expiry") or "")[:10] == expiry[:10]:
                if item.get("strike") is None:
                    continue
                options.append(MarketInstrument(
                    exchange=item["exchange"], symbol=item["symbol"], token=str(item["token"]),
                    segment=item["segment"], expiry=item.get("expiry"),
                    strike=Decimal(str(item["strike"])), option_type=side,
                    lot_size=item.get("lot_size"), instrument_type=item.get("instrument_type")))
            elif not side and underlying is None:
                underlying = MarketInstrument(
                    exchange=item["exchange"], symbol=item["symbol"], token=str(item["token"]),
                    segment=item["segment"], instrument_type=item.get("instrument_type"))
        if not options:
            raise RuntimeError(f"No mapped CE/PE contracts for {symbol} expiry {expiry}")
        subscriptions = list(options)
        if underlying:
            subscriptions.append(underlying)
        before = {item.token: self.hub.tick_count_for(item.token) for item in subscriptions}
        request_started = datetime.now(timezone.utc)
        await self.subscribe(subscriptions)
        try:
            deadline = asyncio.get_running_loop().time() + max(0.5, wait_seconds)
            while asyncio.get_running_loop().time() < deadline:
                if any(self.hub.tick_count_for(item.token) > before[item.token] for item in options):
                    break
                await asyncio.sleep(0.1)
            chain: dict[str, dict[str, Any]] = {}
            for instrument in options:
                tick = self.hub.latest_for(instrument.token)
                if not tick or self.hub.tick_count_for(instrument.token) <= before[instrument.token]:
                    continue
                strike = str(instrument.strike)
                side = "ce" if instrument.option_type == "CE" else "pe"
                chain.setdefault(strike, {})[side] = {
                    "security_id": instrument.token,
                    "last_price": tick.get("ltp"),
                    "previous_close_price": tick.get("close"),
                    "volume": tick.get("volume"),
                    "oi": tick.get("open_interest"),
                    "top_bid_price": tick.get("bid"),
                    "top_ask_price": tick.get("ask"),
                }
            spot_tick = self.hub.latest_for(underlying.token) if underlying else None
            if spot_tick and datetime.fromisoformat(
                str(spot_tick.get("received_at")).replace("Z", "+00:00")) < request_started:
                spot_tick = None
            if sum(len(sides) for sides in chain.values()) == 0:
                raise RuntimeError(f"No live option quotes received for {symbol} {expiry}")

            return {
                "provider": provider, "account_id": account_id,
                "underlying_symbol": symbol, "expiry": expiry[:10],
                "underlying_price": spot_tick.get("ltp") if spot_tick else None,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "chain": {"oc": chain},
                "contracts_received": sum(len(sides) for sides in chain.values()),
                "contracts_requested": len(options),
            }
        finally:
            await self.unsubscribe(subscriptions)

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
                        if provider == "nse_bhavcopy":
                            native = await adapter.search_instruments(
                                symbol, limit=500,
                                exchange_segment="NSE_FO" if option_type in {"CE", "PE"} else "NSE_CM"
                            )
                        else:
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
                         if str(item.get("underlying_symbol") or item.get("symbol") or "").upper() == symbol
                         and str(item.get("expiry") or "")[:10] == expiry
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
            active_source = self.router.resolve("historical")
            actual_provider, actual_account = (
                active_source[0][0], active_source[0][1]
            ) if active_source else ("unknown", "unknown")
            added_count = ledger.attach_market_data_bars(
                row["signal_id"], payload,
                {"provider": actual_provider, "account_id": actual_account, "interval": "day",
                 "retrieved_at": datetime.now(timezone.utc).isoformat()})
            if added_count:
                updated += 1
                added += added_count
        active_source = self.router.resolve("historical")
        actual_provider, actual_account = (
            active_source[0][0], active_source[0][1]
        ) if active_source else ("unknown", "unknown")
        return {"status": "COMPLETED", "provider": actual_provider, "account_id": actual_account,
                "signals_seen": len(rows), "contracts_matched": matched,
                "strategy_records_updated": updated, "daily_bars_added": added,
                "skipped": skipped}

    def expiry_scan(self, store: Any, *, account_id: str, provider: str = "dhan",
                    max_dte: int = 45, limit: int = 2000,
                    today: date | None = None) -> dict[str, Any]:
        """Run the EXPIRYSCAN liquidity screen over normalized persisted option observations."""
        from app.model_engine_expiryscan import scan_expiries
        return scan_expiries(store, account_id=account_id, provider=provider,
                             max_dte=max_dte, limit=limit, today=today)

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
            expiry = str(row.get("expiry") or "")[:10]
            option_type = str(row.get("option_type") or "").upper()
            strike = row.get("strike")
            mapped = self.instruments.search(provider, account_id, symbol, 200)
            if not mapped:
                try:
                    if provider == "nse_bhavcopy":
                        candidates = await adapter.search_instruments(
                            symbol, limit=200,
                            exchange_segment="NSE_FO" if option_type in {"CE", "PE"} else "NSE_CM"
                        )
                    else:
                        candidates = await adapter.search_instruments(symbol, limit=200)
                    mapped = [item.__dict__ for item in candidates]
                except Exception:
                    return
            chosen = []
            for item in mapped:
                if str(item.get("underlying_symbol") or item.get("symbol") or "").upper() != symbol:
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
            active_source = self.router.resolve("historical")
            actual_provider, actual_account = (
                active_source[0][0], active_source[0][1]
            ) if active_source else ("unknown", "unknown")
            for bar in bars:
                day = bar.start_time.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
                by_date.setdefault(day, {
                    "date": day, "open": float(bar.open), "high": float(bar.high),
                    "low": float(bar.low), "close": float(bar.close),
                    "quantity": bar.volume, "volume": bar.volume,
                    "open_interest": bar.open_interest,
                    "source": actual_provider,
                })
            evidence["daily_option_bars"] = [by_date[key] for key in sorted(by_date)]
            evidence["market_data_source"] = {
                "provider": actual_provider, "account_id": actual_account,
                "normalized_by": "AIR_MARKET_DATA_SERVICE",
            }
            row["evidence"] = evidence

        tasks = [load_one(row) for row in result[:max_contracts]]
        await asyncio.gather(*tasks)
        return result

    async def health(self) -> dict:
        historical = await self.router.check_health("historical")
        live = await self.router.check_health("live")
        failed_states = {
            "error", "outage", "degraded", "stale", "disconnected",
            "reconnecting", "historical_request_failed", "subscription_failed",
        }
        if (historical.get("failover") != "switched"
                and historical.get("state") in failed_states
                and self.router.is_registered("nse_bhavcopy", "official")):
            await self.router.set_source("historical", "nse_bhavcopy", "official")
            state = getattr(self, "customer_market_data_status", None)
            if isinstance(state, dict):
                state.update({
                    "effective_source": "NSE", "connection_status": "unavailable",
                    "fallback_active": True, "fallback_reason": "historical_feed_unhealthy",
                })
        if (live.get("failover") != "switched"
                and live.get("state") in failed_states
                and self.router.is_registered("nse_bhavcopy", "official")):
            await self.router.clear_source("live")
            await self.router.set_source("historical", "nse_bhavcopy", "official")
            state = getattr(self, "customer_market_data_status", None)
            if isinstance(state, dict):
                state.update({
                    "effective_source": "NSE", "connection_status": "unavailable",
                    "fallback_active": True, "fallback_reason": "live_feed_unhealthy",
                })
        if live.get("failover") == "switched" and self._subscriptions:
            source = self.router.resolve("live")
            if source:
                provider, account_id, adapter = source[0]
                mapped = await self._remap_instruments(
                    provider, account_id, adapter, list(self._subscriptions.values()))
                await adapter.subscribe(mapped)
        return {"historical": historical, "live": live,
                "routing": self.router.status(), "stream": self.hub.status()}
