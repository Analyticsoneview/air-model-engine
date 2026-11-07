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
    """Route historical and live channels independently to verified adapters.

    A single adapter/account may serve both channels, or each channel may use a
    different provider. Switching one channel does not disconnect the other.
    No implicit failover is performed.
    """

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], MarketDataAdapter] = {}
        self._bindings: dict[tuple[str, str], ProviderBinding] = {}
        self._channel_accounts: dict[str, tuple[str, str] | None] = {
            "historical": None, "live": None,
        }
        self._lock = asyncio.Lock()
        self._connection_state = {"historical": "not_configured", "live": "not_configured"}
        self._last_error: dict[str, str | None] = {"historical": None, "live": None}

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

    async def set_source(self, channel: Literal["historical", "live"],
                         provider: str, account_id: str) -> None:
        if channel not in ("historical", "live"):
            raise ValueError("Unsupported market-data channel")
        key = (provider.strip().lower(), account_id.strip())
        async with self._lock:
            if key not in self._adapters:
                raise ValueError("Provider account is not registered")
            if not self._bindings[key].enabled:
                raise ValueError("Provider account is disabled")
            current = self._channel_accounts[channel]
            if current == key and self._connection_state[channel] == "connected":
                return
            previous = current
            self._channel_accounts[channel] = None
            self._connection_state[channel] = "switching"
            self._last_error[channel] = None
            still_used = key in self._channel_accounts.values()
            try:
                if not still_used:
                    await self._adapters[key].authenticate(key[1])
                self._channel_accounts[channel] = key
                self._connection_state[channel] = "connected"
            except Exception as exc:
                self._connection_state[channel] = "outage"
                self._last_error[channel] = f"Authentication failed: {type(exc).__name__}"
                self._channel_accounts[channel] = None
                raise RuntimeError("Provider authentication failed; selected channel remains offline") from exc
            if previous is not None and previous != key and previous not in self._channel_accounts.values():
                try:
                    await self._adapters[previous].close()
                except Exception as exc:
                    self._last_error[channel] = f"Previous provider close failed: {type(exc).__name__}"

    async def set_main_account(self, provider: str, account_id: str) -> None:
        """Backward-compatible selector that assigns the same source to both channels."""
        await self.set_source("historical", provider, account_id)
        await self.set_source("live", provider, account_id)

    async def clear_source(self, channel: Literal["historical", "live"]) -> None:
        if channel not in ("historical", "live"):
            raise ValueError("Unsupported market-data channel")
        async with self._lock:
            previous = self._channel_accounts[channel]
            self._channel_accounts[channel] = None
            self._connection_state[channel] = "not_configured"
            self._last_error[channel] = None
            if previous is not None and previous not in self._channel_accounts.values():
                try:
                    await self._adapters[previous].close()
                except Exception as exc:
                    self._connection_state[channel] = "outage"
                    self._last_error[channel] = f"Disconnect failed: {type(exc).__name__}"
                    raise RuntimeError("Provider disconnect failed") from exc

    async def clear_main_account(self) -> None:
        await self.clear_source("historical")
        await self.clear_source("live")

    async def set_enabled(self, provider: str, account_id: str, enabled: bool) -> None:
        key = (provider.strip().lower(), account_id.strip())
        if key not in self._adapters:
            raise ValueError("Provider account is not registered")
        if not enabled:
            for channel in ("historical", "live"):
                if self._channel_accounts[channel] == key:
                    await self.clear_source(channel)
        self._bindings[key] = ProviderBinding(*key, enabled=enabled)

    def resolve(self, channel: Literal["historical", "live"]) -> list[tuple[str, str, MarketDataAdapter]]:
        if channel not in ("historical", "live"):
            raise ValueError(f"Unsupported market-data channel: {channel}")
        key = self._channel_accounts[channel]
        if key is None or self._connection_state[channel] != "connected":
            return []
        return [(key[0], key[1], self._adapters[key])]

    def status(self) -> dict:
        sources = {}
        for channel, key in self._channel_accounts.items():
            sources[channel] = {
                "provider": key[0], "account_id": key[1]
            } if key else None
        # Preserve old fields for clients that still read Main Account status.
        same_source = sources["historical"] if sources["historical"] == sources["live"] else None
        return {
            "data_connection_policy": "independent_historical_and_live_sources",
            "connection_state": dict(self._connection_state),
            "sources": sources,
            "active_data_account": same_source,
            "historical_source": sources["historical"],
            "live_source": sources["live"],
            "last_error": dict(self._last_error),
            "registered_provider_accounts": [
                {"provider": binding.provider, "account_id": binding.account_id,
                 "enabled": binding.enabled,
                 "channels": [channel for channel, key in self._channel_accounts.items() if key == (binding.provider, binding.account_id)]}
                for key, binding in sorted(self._bindings.items())
            ],
            "simultaneous_data_connections_allowed": len(set(key for key in self._channel_accounts.values() if key)),
            "automatic_provider_failover": False,
        }
