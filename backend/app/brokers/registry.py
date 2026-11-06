from .base import BrokerAdapter


class BrokerRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, BrokerAdapter] = {}

    def register(self, adapter: BrokerAdapter) -> None:
        code = adapter.broker_code.strip().lower()
        if not code:
            raise ValueError("Broker adapter must declare broker_code")
        if code in self._adapters:
            raise ValueError(f"Broker adapter already registered: {code}")
        self._adapters[code] = adapter

    def get(self, broker_code: str) -> BrokerAdapter:
        code = broker_code.strip().lower()
        try:
            return self._adapters[code]
        except KeyError as exc:
            raise ValueError(f"Unsupported broker: {code}") from exc

    def available(self) -> list[str]:
        return sorted(self._adapters)
