"""Customer-isolated market-data runtimes for AIR strategy evaluation.

Normal customers always use the official NSE EOD store. Operator and explicitly
entitled paid customers may select one of their own authenticated broker accounts.
Each customer gets a separate router and tick hub; broker feeds are never shared.
"""
from __future__ import annotations

import asyncio
import os
from typing import Callable, Any

from app.market_data.hub import MarketDataHub
from app.market_data.router import MarketDataRouter
from app.market_data.service import MarketDataService
from app.market_data.nse_adapter import NSEBhavcopyMarketDataAdapter
from app.access_control import access_store


class CustomerMarketDataRuntime:
    def __init__(self, accounts, instruments, adapter_factory: Callable[[str, str, str, MarketDataHub], Any]):
        self.accounts = accounts
        self.instruments = instruments
        self.adapter_factory = adapter_factory
        self._services: dict[str, tuple[tuple[str, str], MarketDataService]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._source_status: dict[str, dict] = {}

    def _is_operator(self, customer_id: str) -> bool:
        allowed = {x.strip() for x in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",") if x.strip()}
        identity = customer_id if customer_id in allowed else (access_store.mobile_for_request_id(customer_id) or "")
        return identity in allowed

    async def get_service(self, customer_id: str) -> MarketDataService:
        customer_id = customer_id.strip()
        if not customer_id:
            raise PermissionError("Authenticated customer identity is required")
        customer_id = access_store.mobile_for_request_id(customer_id) or customer_id
        lock = self._locks.setdefault(customer_id, asyncio.Lock())
        async with lock:
            access = self.accounts.get_market_data_access(customer_id)
            eligible = self._is_operator(customer_id) or (
                access.get("tier") == "PAID" and access.get("broker_data_enabled") is True
            )
            selection = self.accounts.get_market_data_selection(customer_id)
            if eligible and selection and selection.get("provider") and selection.get("account_id"):
                provider, account_id = selection["provider"], selection["account_id"]
                owned = {(a.broker, a.account_id) for a in self.accounts.list_for_customer(customer_id)}
                if (provider, account_id) not in owned:
                    raise PermissionError("Selected broker account is not assigned to this customer")
                key = (provider, account_id)
            else:
                key = ("nse_bhavcopy", "official")

            cached = self._services.get(customer_id)
            if cached and cached[0] == key:
                return cached[1]

            if cached:
                old_service = cached[1]
                for channel in ("historical", "live"):
                    try:
                        await old_service.router.clear_source(channel)
                    except Exception:
                        pass

            router = MarketDataRouter()
            hub = MarketDataHub()
            requested = None if key[0] == "nse_bhavcopy" else {
                "provider": key[0], "account_id": key[1]
            }
            source_status = {
                "requested_source": requested,
                "effective_source": "NSE",
                "connection_status": "not_requested" if requested is None else "connecting",
                "fallback_active": False,
                "fallback_reason": None,
            }
            nse_adapter = NSEBhavcopyMarketDataAdapter()
            if key[0] == "nse_bhavcopy":
                router.register(key[1], nse_adapter)
                await router.set_source("historical", key[0], key[1])
            else:
                router.register("official", nse_adapter)
                adapter = self.adapter_factory(customer_id, key[0], key[1], hub)
                router.register(key[1], adapter)
                try:
                    await router.set_source("historical", key[0], key[1])
                    await router.set_source("live", key[0], key[1])
                    source_status.update({
                        "effective_source": "BROKER",
                        "connection_status": "authenticated",
                    })
                except Exception as exc:
                    # A selected/saved broker is not an active source until both
                    # channels authenticate. Fall back to official NSE EOD data.
                    try:
                        await router.clear_main_account()
                    except Exception:
                        pass
                    await router.set_source("historical", "nse_bhavcopy", "official")
                    source_status.update({
                        "effective_source": "NSE",
                        "connection_status": "unavailable",
                        "fallback_active": True,
                        "fallback_reason": type(exc).__name__,
                    })

            service = MarketDataService(router, hub, self.instruments)
            service.customer_market_data_status = source_status
            self._source_status[customer_id] = source_status
            self._services[customer_id] = (key, service)
            return service


    async def close_all(self) -> None:
        customer_ids = list(self._services)
        for customer_id in customer_ids:
            await self.invalidate(customer_id)

    async def invalidate(self, customer_id: str) -> None:
        customer_id = access_store.mobile_for_request_id(customer_id) or customer_id
        lock = self._locks.setdefault(customer_id, asyncio.Lock())
        async with lock:
            cached = self._services.pop(customer_id, None)
            self._source_status.pop(customer_id, None)
            if cached:
                for channel in ("historical", "live"):
                    try:
                        await cached[1].router.clear_source(channel)
                    except Exception:
                        pass


_runtime: CustomerMarketDataRuntime | None = None


def configure_customer_market_data_runtime(accounts, instruments, adapter_factory) -> None:
    global _runtime
    _runtime = CustomerMarketDataRuntime(accounts, instruments, adapter_factory)


async def get_customer_market_data_service(customer_id: str) -> MarketDataService:
    if _runtime is None:
        raise RuntimeError("Customer market-data runtime has not been configured")
    return await _runtime.get_service(customer_id)


async def get_customer_market_data_status(customer_id: str) -> dict:
    if _runtime is None:
        raise RuntimeError("Customer market-data runtime has not been configured")
    service = await _runtime.get_service(customer_id)
    status = dict(getattr(service, "customer_market_data_status", {}))
    status.update(service.router.status())
    historical = status.get("historical_source") or {}
    live = status.get("live_source") or {}
    hist_nse = historical.get("provider") == "nse_bhavcopy"
    live_broker = bool(live) and live.get("provider") != "nse_bhavcopy"
    hist_broker = bool(historical) and not hist_nse
    if hist_nse and live_broker:
        status["effective_source"] = "MIXED"
    elif hist_broker and live_broker:
        status["effective_source"] = "BROKER"
    elif hist_broker:
        status["effective_source"] = "BROKER_HISTORICAL_ONLY"
    else:
        status["effective_source"] = "NSE"
    if status.get("connection_status") == "authenticated" and live_broker:
        feed_state = (status.get("health", {}).get("live") or {}).get("feed_state", "unknown")
        if feed_state not in {"connected", "streaming"}:
            status["connection_status"] = str(feed_state).upper()
    status["source_label"] = (
        f"{status['effective_source']} (NSE FALLBACK)"
        if status.get("fallback_active") else status["effective_source"]
    )
    status["connection_message"] = (
        "Broker unavailable; using NSE EOD data"
        if status.get("fallback_active") else
        "NSE EOD default" if not status.get("requested_source") else
        f"Broker {status.get('connection_status', 'unknown')}"
    )
    return status


async def invalidate_customer_market_data_service(customer_id: str) -> None:
    if _runtime is not None:
        await _runtime.invalidate(customer_id)


async def close_customer_market_data_runtimes() -> None:
    if _runtime is not None:
        await _runtime.close_all()
