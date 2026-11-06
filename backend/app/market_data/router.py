from dataclasses import dataclass
from typing import Literal

from .contracts import MarketDataAdapter


@dataclass(frozen=True)
class ProviderBinding:
    provider: str
    account_id: str
    enabled: bool = True


class MarketDataRouter:
    """Exactly one active broker account supplies AIR historical and live data.

    Other registered providers are configuration choices only. They are not
    connected or queried concurrently. Switching providers is explicit.
    """

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], MarketDataAdapter] = {}
        self._bindings: dict[tuple[str, str], ProviderBinding] = {}
        self._main_account: tuple[str, str] | None = None

    def register(self, account_id: str, adapter: MarketDataAdapter) -> None:
        key = (adapter.provider_code.strip().lower(), account_id.strip())
        if not all(key):
            raise ValueError("Provider and account identifiers are required")
        if key in self._adapters:
            raise ValueError(f"Provider account already registered: {key}")
        self._adapters[key] = adapter
        self._bindings[key] = ProviderBinding(*key)

    def set_main_account(self, provider: str, account_id: str) -> None:
        """Select the one account used for both historical and live data."""
        key = (provider.strip().lower(), account_id.strip())
        if key not in self._adapters:
            raise ValueError("Main data account is not registered")
        if not self._bindings[key].enabled:
            raise ValueError("Main data account is disabled")
        self._main_account = key

    def clear_main_account(self) -> None:
        self._main_account = None

    def set_enabled(self, provider: str, account_id: str, enabled: bool) -> None:
        key = (provider.strip().lower(), account_id.strip())
        if key not in self._adapters:
            raise ValueError("Provider account is not registered")
        self._bindings[key] = ProviderBinding(*key, enabled=enabled)
        if not enabled and self._main_account == key:
            self._main_account = None

    def resolve(self, channel: Literal["historical", "live"]) -> list[tuple[str, str, MarketDataAdapter]]:
        # Both channels always resolve to the same single Main Account.
        if self._main_account is None:
            return []
        provider, account_id = self._main_account
        return [(provider, account_id, self._adapters[self._main_account])]

    def status(self) -> dict:
        active = self._main_account
        return {
            "data_connection_policy": "single_active_main_account",
            "active_data_account": (
                {"provider": active[0], "account_id": active[1]} if active else None
            ),
            "historical_source": (
                {"provider": active[0], "account_id": active[1]} if active else None
            ),
            "live_source": (
                {"provider": active[0], "account_id": active[1]} if active else None
            ),
            "registered_provider_accounts": [
                {"provider": binding.provider, "account_id": binding.account_id,
                 "enabled": binding.enabled, "is_main": key == active}
                for key, binding in sorted(self._bindings.items())
            ],
            "simultaneous_data_connections_allowed": 1,
        }
