from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class BrokerCredentials:
    account_id: str
    api_key: str
    access_token: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class Instrument:
    broker: str
    exchange: str
    trading_symbol: str
    token: str
    segment: str
    lot_size: int
    tick_size: Decimal


@dataclass(frozen=True)
class Quote:
    broker: str
    exchange: str
    token: str
    ltp: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    volume: int | None = None
    open_interest: int | None = None
    timestamp: str | None = None


@dataclass(frozen=True)
class OrderRequest:
    account_id: str
    exchange: str
    symbol: str
    token: str
    side: str
    order_type: str
    product: str
    quantity: int
    price: Decimal | None
    trigger_price: Decimal | None
    validity: str
    tag: str
    idempotency_key: str


@dataclass(frozen=True)
class BrokerOrder:
    broker: str
    account_id: str
    broker_order_id: str
    status: str
    raw: dict[str, Any]


class BrokerAdapter(ABC):
    """Implement this contract for each broker; never leak broker payloads upstream."""

    broker_code: str

    @abstractmethod
    async def authenticate(self, credentials: BrokerCredentials) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_quotes(self, instruments: list[Instrument]) -> list[Quote]:
        raise NotImplementedError

    @abstractmethod
    async def get_positions(self, account_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def get_holdings(self, account_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def get_order_book(self, account_id: str) -> list[BrokerOrder]:
        raise NotImplementedError

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    async def modify_order(self, account_id: str, broker_order_id: str, changes: dict[str, Any]) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, account_id: str, broker_order_id: str) -> BrokerOrder:
        raise NotImplementedError
