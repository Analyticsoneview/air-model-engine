from .base import BrokerAdapter


class BrokerRegistry:
    """Registry of isolated broker sessions, one per connected account."""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], BrokerAdapter] = {}
        self._active: set[tuple[str, str]] = set()

    def register(self, account_id: str, adapter: BrokerAdapter, *, active: bool = True) -> None:
        code = adapter.broker_code.strip().lower()
        account = account_id.strip()
        if not code or not account:
            raise ValueError("Broker code and account_id are required")
        key = (code, account)
        if key in self._adapters:
            raise ValueError(f"Broker account already registered: {code}/{account}")
        self._adapters[key] = adapter
        if active:
            self._active.add(key)

    def set_active(self, broker_code: str, account_id: str, active: bool) -> None:
        key = (broker_code.strip().lower(), account_id.strip())
        if key not in self._adapters:
            raise ValueError(f"Broker account is not connected: {key[0]}/{key[1]}")
        if active:
            self._active.add(key)
        else:
            self._active.discard(key)

    def get(self, broker_code: str, account_id: str) -> BrokerAdapter:
        key = (broker_code.strip().lower(), account_id.strip())
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise ValueError(f"Broker account is not connected: {key[0]}/{key[1]}") from exc

    def accounts(self, broker_code: str | None = None, *, active_only: bool = False) -> list[dict[str, str]]:
        keys = self._active if active_only else self._adapters.keys()
        rows = [
            {"broker": broker, "account_id": account}
            for broker, account in keys
            if broker_code is None or broker == broker_code.strip().lower()
        ]
        return sorted(rows, key=lambda row: (row["broker"], row["account_id"]))

    def active_accounts(self) -> list[dict[str, str]]:
        return self.accounts(active_only=True)

    def available(self) -> list[str]:
        return sorted({broker for broker, _ in self._adapters})

    def unregister(self, broker_code: str, account_id: str) -> BrokerAdapter:
        key = (broker_code.strip().lower(), account_id.strip())
        adapter = self._adapters.pop(key, None)
        self._active.discard(key)
        if adapter is None:
            raise ValueError(f"Broker account is not connected: {key[0]}/{key[1]}")
        return adapter


def build_broker_adapter(broker_code: str, *, client=None) -> BrokerAdapter:
    """Construct a normalized adapter without registering or activating an account.

    Authentication and account registration remain explicit caller operations.
    """
    code = broker_code.strip().lower()
    if code == "dhan":
        from .dhan_adapter import DhanBrokerAdapter
        return DhanBrokerAdapter(client=client)
    if code in {"zerodha", "upstox", "fyers", "angel"}:
        from .normalized_adapters import (
            ZerodhaBrokerAdapter, UpstoxBrokerAdapter, FyersBrokerAdapter, AngelBrokerAdapter,
        )
        adapters = {
            "zerodha": ZerodhaBrokerAdapter,
            "upstox": UpstoxBrokerAdapter,
            "fyers": FyersBrokerAdapter,
            "angel": AngelBrokerAdapter,
        }
        return adapters[code](client=client)
    raise ValueError(f"Unsupported broker adapter: {code}")