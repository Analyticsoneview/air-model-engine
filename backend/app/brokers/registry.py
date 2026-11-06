from .base import BrokerAdapter


class BrokerRegistry:
    """Registry of isolated broker sessions, one per connected account."""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], BrokerAdapter] = {}

    def register(self, account_id: str, adapter: BrokerAdapter) -> None:
        code = adapter.broker_code.strip().lower()
        account = account_id.strip()
        if not code or not account:
            raise ValueError("Broker code and account_id are required")
        key = (code, account)
        if key in self._adapters:
            raise ValueError(f"Broker account already registered: {code}/{account}")
        self._adapters[key] = adapter

    def get(self, broker_code: str, account_id: str) -> BrokerAdapter:
        key = (broker_code.strip().lower(), account_id.strip())
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise ValueError(f"Broker account is not connected: {key[0]}/{key[1]}") from exc

    def accounts(self, broker_code: str | None = None) -> list[dict[str, str]]:
        rows = [
            {"broker": broker, "account_id": account}
            for broker, account in self._adapters
            if broker_code is None or broker == broker_code.strip().lower()
        ]
        return sorted(rows, key=lambda row: (row["broker"], row["account_id"]))

    def available(self) -> list[str]:
        return sorted({broker for broker, _ in self._adapters})
