"""Lifecycle manager for authenticated customer broker sessions.

Sessions are in-memory, account-scoped and inactive until provider profile
verification succeeds. No credentials are returned from this module.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from app.brokers.base import BrokerCredentials
from app.brokers.registry import BrokerRegistry, build_broker_adapter


_PROVIDER_ALIASES = {"angelone": "angel", "angel_one": "angel"}


class BrokerSessionRuntime:
    def __init__(self, account_directory: Any, credential_vault: Any,
                 registry: BrokerRegistry | None = None,
                 adapter_factory=build_broker_adapter) -> None:
        self.account_directory = account_directory
        self.credential_vault = credential_vault
        self.registry = registry or BrokerRegistry()
        self.adapter_factory = adapter_factory
        self._owners: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _provider(broker: str) -> str:
        return _PROVIDER_ALIASES.get(broker.strip().lower(), broker.strip().lower())

    async def activate(self, customer_id: str, broker: str, account_id: str) -> dict[str, Any]:
        customer, provider, account = customer_id.strip(), self._provider(broker), account_id.strip()
        if not customer or not provider or not account:
            raise ValueError("Customer, broker and account are required")
        owned = {(a.broker, a.account_id) for a in self.account_directory.list_for_customer(customer)}
        directory_broker = broker.strip().lower()
        if (directory_broker, account) not in owned and (provider, account) not in owned:
            raise PermissionError("Customer does not own this broker account")
        key = (provider, account)
        async with self._lock:
            existing_owner = self._owners.get(key)
            if existing_owner and existing_owner != customer:
                raise PermissionError("Broker account is already active for another customer")
            if existing_owner == customer:
                return {"broker": provider, "account_id": account, "active": True, "already_active": True}
            try:
                stored = self.credential_vault.get(customer, directory_broker, account)
            except KeyError:
                stored = self.credential_vault.get(customer, provider, account)
            api_key = stored.get("api_key") or stored.get("client_id") or stored.get("app_id") or ""
            token = stored.get("access_token") or stored.get("jwt_token") or ""
            metadata = {
                "client_local_ip": stored.get("client_local_ip") or os.getenv("AIR_CLIENT_LOCAL_IP"),
                "client_public_ip": stored.get("client_public_ip") or os.getenv("AIR_CLIENT_PUBLIC_IP"),
                "mac_address": stored.get("mac_address") or os.getenv("AIR_CLIENT_MAC_ADDRESS"),
            }
            if provider == "angel":
                # Older AIR credential records store only API key/PIN; these are
                # insufficient for a normalized session until the user logs in.
                token = stored.get("jwt_token") or stored.get("access_token") or ""
            adapter = self.adapter_factory(provider)
            credentials = BrokerCredentials(
                account_id=account, api_key=api_key, access_token=token,
                metadata=metadata,
            )
            try:
                verified = await adapter.authenticate(credentials)
                if not verified.get("authenticated") or verified.get("account_id") != account:
                    raise PermissionError("Broker profile verification did not confirm the selected account")
                self.registry.register(account, adapter, active=False)
                try:
                    self.registry.set_active(provider, account, True)
                except Exception:
                    self.registry.unregister(provider, account)
                    raise
                self._owners[key] = customer
                return {"broker": provider, "account_id": account, "active": True}
            except Exception:
                await self._close_adapter(adapter)
                raise

    async def deactivate(self, customer_id: str, broker: str, account_id: str) -> dict[str, Any]:
        customer, provider, account = customer_id.strip(), self._provider(broker), account_id.strip()
        key = (provider, account)
        async with self._lock:
            owner = self._owners.get(key)
            if owner is None:
                return {"broker": provider, "account_id": account, "active": False, "already_inactive": True}
            if owner != customer:
                raise PermissionError("Customer does not own this active broker session")
            adapter = self.registry.unregister(provider, account)
            self._owners.pop(key, None)
            await self._close_adapter(adapter)
            return {"broker": provider, "account_id": account, "active": False}

    async def deactivate_customer(self, customer_id: str) -> int:
        customer = customer_id.strip()
        keys = [key for key, owner in self._owners.items() if owner == customer]
        closed = 0
        for broker, account in keys:
            await self.deactivate(customer, broker, account)
            closed += 1
        return closed

    async def close(self) -> None:
        async with self._lock:
            keys = list(self._owners)
            adapters = []
            for broker, account in keys:
                try:
                    adapters.append(self.registry.unregister(broker, account))
                except ValueError:
                    # Keep cleanup progressing if the registry was externally reset.
                    continue
            self._owners.clear()
            errors = []
            for adapter in adapters:
                try:
                    await self._close_adapter(adapter)
                except Exception as exc:
                    errors.append(exc)
            if errors:
                raise RuntimeError(f"Failed to close {len(errors)} broker client resource(s)") from errors[0]

    async def _close_adapter(self, adapter: Any) -> None:
        client = getattr(adapter, "client", None)
        close = getattr(client, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result

    def status_for_customer(self, customer_id: str) -> list[dict[str, str]]:
        customer = customer_id.strip()
        return sorted(
            [{"broker": b, "account_id": a, "status": "ACTIVE"}
             for (b, a), owner in self._owners.items() if owner == customer],
            key=lambda row: (row["broker"], row["account_id"]),
        )
