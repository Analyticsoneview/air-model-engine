from dataclasses import dataclass
from typing import Literal
from .contracts import MarketDataAdapter

@dataclass(frozen=True)
class ProviderBinding:
    provider: str
    account_id: str
    priority: int = 100
    enabled: bool = True

class MarketDataRouter:
    """Provider-independent routing; historical and live sources are independent."""
    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], MarketDataAdapter] = {}
        self._bindings: list[ProviderBinding] = []
        self.historical_mode: Literal["manual", "priority", "automatic"] = "priority"
        self.live_mode: Literal["manual", "priority", "automatic"] = "priority"
        self.historical_source: tuple[str, str] | None = None
        self.live_source: tuple[str, str] | None = None

    def register(self, account_id: str, adapter: MarketDataAdapter, *, priority: int = 100) -> None:
        key = (adapter.provider_code.lower(), account_id)
        if key in self._adapters:
            raise ValueError(f"Provider account already registered: {key}")
        self._adapters[key] = adapter
        self._bindings.append(ProviderBinding(key[0], account_id, priority))

    def set_enabled(self, provider: str, account_id: str, enabled: bool) -> None:
        key = (provider.lower(), account_id)
        if key not in self._adapters:
            raise ValueError("Provider account is not registered")
        self._bindings = [ProviderBinding(b.provider, b.account_id, b.priority, enabled)
                          if (b.provider, b.account_id) == key else b for b in self._bindings]

    def set_source(self, channel: Literal["historical", "live"], provider: str, account_id: str) -> None:
        key = (provider.lower(), account_id)
        if key not in self._adapters:
            raise ValueError("Provider account is not registered")
        if not any((b.provider, b.account_id) == key and b.enabled for b in self._bindings):
            raise ValueError("Provider account is disabled")
        if channel == "historical":
            self.historical_source = key
        else:
            self.live_source = key

    def resolve(self, channel: Literal["historical", "live"]) -> list[tuple[str, str, MarketDataAdapter]]:
        selected = self.historical_source if channel == "historical" else self.live_source
        if selected:
            return [(selected[0], selected[1], self._adapters[selected])]
        enabled = sorted((b for b in self._bindings if b.enabled),
                         key=lambda b: (b.priority, b.provider, b.account_id))
        return [(b.provider, b.account_id, self._adapters[(b.provider, b.account_id)]) for b in enabled]

    def status(self) -> dict:
        return {
            "historical_mode": self.historical_mode, "live_mode": self.live_mode,
            "historical_source": self.historical_source, "live_source": self.live_source,
            "providers": [{"provider": b.provider, "account_id": b.account_id,
                           "priority": b.priority, "enabled": b.enabled}
                          for b in sorted(self._bindings, key=lambda x: (x.priority, x.provider, x.account_id))]
        }
