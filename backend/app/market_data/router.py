"""Independent historical/live router with optional health-triggered failover."""
import asyncio
from dataclasses import dataclass
from typing import Literal
from .contracts import MarketDataAdapter

Channel = Literal["historical", "live"]


@dataclass(frozen=True)
class ProviderBinding:
    provider: str
    account_id: str
    enabled: bool = True


class MarketDataRouter:
    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], MarketDataAdapter] = {}
        self._bindings: dict[tuple[str, str], ProviderBinding] = {}
        self._channel_accounts: dict[str, tuple[str, str] | None] = {
            "historical": None, "live": None}
        self._failover_accounts: dict[str, list[tuple[str, str]]] = {
            "historical": [], "live": []}
        self._failover_enabled = {"historical": False, "live": False}
        self._connection_state = {"historical": "not_configured", "live": "not_configured"}
        self._last_error: dict[str, str | None] = {"historical": None, "live": None}
        self._forced_unhealthy: dict[str, str | None] = {"historical": None, "live": None}
        self._failover_events: list[dict] = []
        self._lock = asyncio.Lock()

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

    async def set_source(self, channel: Channel, provider: str, account_id: str) -> None:
        if channel not in ("historical", "live"):
            raise ValueError("Unsupported data channel")
        key = (provider.strip().lower(), account_id.strip())
        async with self._lock:
            if key not in self._adapters or not self._bindings[key].enabled:
                raise ValueError("Provider account is not registered/enabled")
            previous = self._channel_accounts[channel]
            if previous == key and self._connection_state[channel] == "connected":
                return
            self._connection_state[channel] = "switching"
            try:
                shared = key in (v for ch, v in self._channel_accounts.items() if ch != channel)
                if not shared:
                    await self._adapters[key].authenticate(key[1])
            except Exception as exc:
                self._connection_state[channel] = "connected" if previous else "outage"
                self._last_error[channel] = f"Authentication failed: {type(exc).__name__}"
                raise RuntimeError("Provider authentication failed; previous source retained") from exc
            self._channel_accounts[channel] = key
            self._connection_state[channel] = "connected"
            self._last_error[channel] = None
            self._forced_unhealthy[channel] = None
            if previous and previous != key and previous not in self._channel_accounts.values():
                await self._adapters[previous].close()

    async def configure_failover(self, channel: Channel,
                                 candidates: list[tuple[str, str]], enabled: bool) -> None:
        if channel not in ("historical", "live"):
            raise ValueError("Unsupported data channel")
        active = self._channel_accounts[channel]
        unique = list(dict.fromkeys((p.strip().lower(), a.strip()) for p, a in candidates))
        for key in unique:
            if key not in self._adapters or not self._bindings[key].enabled:
                raise ValueError(f"Failover provider account is not registered/enabled: {key}")
            if key == active:
                raise ValueError("Failover candidate cannot duplicate the active source")
            if active and key[0] != active[0]:
                raise ValueError(
                    "Cross-broker failover is blocked until a verified provider-to-provider "
                    "instrument-token mapping is available; use a secondary account on the same broker"
                )
        self._failover_accounts[channel] = unique
        self._failover_enabled[channel] = bool(enabled)

    async def mark_unhealthy(self, channel: Channel, reason: str) -> None:
        if channel not in ("historical", "live"):
            raise ValueError("Unsupported data channel")
        self._forced_unhealthy[channel] = reason[:120]
        self._connection_state[channel] = "degraded"
        self._last_error[channel] = reason[:120]

    async def check_health(self, channel: Channel) -> dict:
        if channel not in ("historical", "live"):
            raise ValueError("Unsupported data channel")
        async with self._lock:
            active = self._channel_accounts[channel]
            if active is None:
                return {"channel": channel, "state": "not_configured", "failover": "not_applicable"}
            adapter = self._adapters[active]
            health = adapter.health() if hasattr(adapter, "health") else {"feed_state": "connected"}
            state = self._forced_unhealthy[channel] or str(health.get("feed_state") or "connected").lower()
            failed = state in {"error", "outage", "degraded", "stale", "disconnected",
                               "reconnecting", "historical_request_failed", "subscription_failed"}
            if not failed:
                self._connection_state[channel] = "connected"
                self._forced_unhealthy[channel] = None
                return {"channel": channel, "state": state, "active": active, "health": health,
                        "failover": "not_needed"}
            self._connection_state[channel] = "degraded"
            self._last_error[channel] = f"Primary feed health: {state}"
            if not self._failover_enabled[channel]:
                return {"channel": channel, "state": state, "active": active, "health": health,
                        "failover": "disabled"}
            for candidate in self._failover_accounts[channel]:
                try:
                    await self._adapters[candidate].authenticate(candidate[1])
                    self._channel_accounts[channel] = candidate
                    self._connection_state[channel] = "connected"
                    self._last_error[channel] = None
                    self._forced_unhealthy[channel] = None
                    event = {"channel": channel, "from": active, "to": candidate,
                             "reason": state, "status": "switched"}
                    self._failover_events.append(event)
                    self._failover_events = self._failover_events[-50:]
                    if active not in self._channel_accounts.values():
                        await adapter.close()
                    return {"channel": channel, "state": "connected", "active": candidate,
                            "health": health, "failover": "switched", "event": event}
                except Exception as exc:
                    self._failover_events.append({"channel": channel, "from": active,
                        "candidate": candidate, "reason": type(exc).__name__,
                        "status": "candidate_failed"})
            return {"channel": channel, "state": "outage", "active": active,
                    "health": health, "failover": "exhausted"}

    def resolve(self, channel: Channel) -> list[tuple[str, str, MarketDataAdapter]]:
        if channel not in ("historical", "live"):
            raise ValueError(f"Unsupported data channel: {channel}")
        key = self._channel_accounts[channel]
        if key is None or self._connection_state[channel] not in {"connected", "degraded"}:
            return []
        return [(key[0], key[1], self._adapters[key])]

    async def set_main_account(self, provider: str, account_id: str) -> None:
        await self.set_source("historical", provider, account_id)
        await self.set_source("live", provider, account_id)

    async def clear_source(self, channel: Channel) -> None:
        if channel not in ("historical", "live"):
            raise ValueError("Unsupported data channel")
        async with self._lock:
            previous = self._channel_accounts[channel]
            self._channel_accounts[channel] = None
            self._connection_state[channel] = "not_configured"
            self._last_error[channel] = None
            self._forced_unhealthy[channel] = None
            self._failover_accounts[channel] = []
            self._failover_enabled[channel] = False
            if previous and previous not in self._channel_accounts.values():
                await self._adapters[previous].close()

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

    def status(self) -> dict:
        sources = {ch: ({"provider": key[0], "account_id": key[1]} if key else None)
                   for ch, key in self._channel_accounts.items()}
        health = {}
        for channel, key in self._channel_accounts.items():
            if key:
                adapter = self._adapters[key]
                health[channel] = adapter.health() if hasattr(adapter, "health") else {
                    "feed_state": self._connection_state[channel]}
            else:
                health[channel] = {"feed_state": "not_configured"}
        return {
            "data_connection_policy": "independent_historical_and_live_sources",
            "connection_state": dict(self._connection_state), "sources": sources,
            "historical_source": sources["historical"], "live_source": sources["live"],
            "active_data_account": sources["historical"] if sources["historical"] == sources["live"] else None,
            "last_error": dict(self._last_error), "health": health,
            "failover": {ch: {"enabled": self._failover_enabled[ch],
                "candidates": [{"provider": p, "account_id": a}
                               for p, a in self._failover_accounts[ch]]}
                for ch in ("historical", "live")},
            "failover_events": self._failover_events[-50:],
            "registered_provider_accounts": [
                {"provider": b.provider, "account_id": b.account_id, "enabled": b.enabled,
                 "channels": [ch for ch, key in self._channel_accounts.items()
                              if key == (b.provider, b.account_id)]}
                for _, b in sorted(self._bindings.items())],
            "automatic_provider_failover": any(self._failover_enabled.values()),
        }
