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

    def _is_operator(self, customer_id: str) -> bool:
        allowed = {x.strip() for x in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",") if x.strip()}
        identity = customer_id if customer_id in allowed else (access_store.mobile_for_request_id(customer_id) or "")
        return identity in allowed

    async def get_service(self, customer_id: str) -> MarketDataService:
        customer_id = customer_id.strip()
        if not customer_id:
            raise PermissionError("Authenticated customer identity is required")
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
            if key[0] == "nse_bhavcopy":
                adapter = NSEBhavcopyMarketDataAdapter()
                router.register(key[1], adapter)
                await router.set_source("historical", key[0], key[1])
            else:
                adapter = self.adapter_factory(customer_id, key[0], key[1], hub)
                router.register(key[1], adapter)
                await router.set_source("historical", key[0], key[1])
                await router.set_source("live", key[0], key[1])

            service = MarketDataService(router, hub, self.instruments)
            self._services[customer_id] = (key, service)
            return service


    async def close_all(self) -> None:
        customer_ids = list(self._services)
        for customer_id in customer_ids:
            await self.invalidate(customer_id)

    async def invalidate(self, customer_id: str) -> None:
        lock = self._locks.setdefault(customer_id, asyncio.Lock())
        async with lock:
            cached = self._services.pop(customer_id, None)
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


async def invalidate_customer_market_data_service(customer_id: str) -> None:
    if _runtime is not None:
        await _runtime.invalidate(customer_id)


async def close_customer_market_data_runtimes() -> None:
    if _runtime is not None:
        await _runtime.close_all()
