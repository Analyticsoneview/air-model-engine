import asyncio
from dataclasses import dataclass
from typing import Literal

from .contracts import MarketDataAdapter


@dataclass(frozen=True)
class ProviderBinding:
    provider: str
    account_id: str
    enabled: bool = True


class MarketDataRouter:
    """Exactly one broker account supplies both historical and live AIR data.

    Provider registrations are dormant until explicitly selected as Main Account.
    Switching always closes the old adapter before authenticating the new one.
    If authentication fails, the router remains disconnected; it never fails over.
    """

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], MarketDataAdapter] = {}
        self._bindings: dict[tuple[str, str], ProviderBinding] = {}
        self._main_account: tuple[str, str] | None = None
        self._lock = asyncio.Lock()
        self._connection_state = "not_configured"
        self._last_error: str | None = None

    def register(self, account_id: str, adapter: MarketDataAdapter) -> None:
        key = (adapter.provider_code.strip().lower(), account_id.strip())
        if not all(key):
            raise ValueError("Provider and account identifiers are required")
        if key in self._adapters:
            raise ValueError(f"Provider account already registered: {key}")
        self._adapters[key] = adapter
        self._bindings[key] = ProviderBinding(*key)

    def is_registered(self, provider: str, account_id: str) -> bool:
        return (provider.strip().lower(), account_id.strip()) in self._adapters

    async def set_main_account(self, provider: str, account_id: str) -> None:
        """Explicitly switch the sole historical + live data account."""
        key = (provider.strip().lower(), account_id.strip())
        async with self._lock:
            if key not in self._adapters:
                raise ValueError("Main data account is not registered")
            if not self._bindings[key].enabled:
                raise ValueError("Main data account is disabled")
            if self._main_account == key and self._connection_state == "connected":
                return

            previous = self._main_account
            self._main_account = None
            self._connection_state = "switching"
            self._last_error = None
            if previous is not None:
                try:
                    await self._adapters[previous].close()
                except Exception as exc:
                    self._connection_state = "outage"
                    self._last_error = f"Previous connection close failed: {type(exc).__name__}"
                    raise RuntimeError("Could not close the previous Main Account connection") from exc

            try:
                await self._adapters[key].authenticate(key[1])
            except Exception as exc:
                self._connection_state = "outage"
                self._last_error = f"Authentication failed: {type(exc).__name__}"
                raise RuntimeError("New Main Account authentication failed; data feed remains offline") from exc

            self._main_account = key
            self._connection_state = "connected"

    async def clear_main_account(self) -> None:
        async with self._lock:
            previous = self._main_account
            self._main_account = None
            self._connection_state = "not_configured"
            self._last_error = None
            if previous is not None:
                try:
                    await self._adapters[previous].close()
                except Exception as exc:
                    self._connection_state = "outage"
                    self._last_error = f"Disconnect failed: {type(exc).__name__}"
                    raise RuntimeError("Main Account disconnect failed") from exc

    async def set_enabled(self, provider: str, account_id: str, enabled: bool) -> None:
        key = (provider.strip().lower(), account_id.strip())
        if key not in self._adapters:
            raise ValueError("Provider account is not registered")
        if not enabled and self._main_account == key:
            await self.clear_main_account()
        self._bindings[key] = ProviderBinding(*key, enabled=enabled)

    def resolve(self, channel: Literal["historical", "live"]) -> list[tuple[str, str, MarketDataAdapter]]:
        if channel not in ("historical", "live"):
            raise ValueError(f"Unsupported market-data channel: {channel}")
        if self._main_account is None or self._connection_state != "connected":
            return []
        provider, account_id = self._main_account
        return [(provider, account_id, self._adapters[self._main_account])]

    def status(self) -> dict:
        active = self._main_account
        source = {"provider": active[0], "account_id": active[1]} if active else None
        return {
            "data_connection_policy": "single_active_main_account",
            "connection_state": self._connection_state,
            "active_data_account": source,
            "historical_source": source,
            "live_source": source,
            "last_error": self._last_error,
            "registered_provider_accounts": [
                {"provider": binding.provider, "account_id": binding.account_id,
                 "enabled": binding.enabled, "is_main": key == active}
                for key, binding in sorted(self._bindings.items())
            ],
            "simultaneous_data_connections_allowed": 1,
            "automatic_provider_failover": False,
        }
