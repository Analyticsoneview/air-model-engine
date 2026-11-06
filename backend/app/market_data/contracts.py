from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

@dataclass(frozen=True)
class MarketInstrument:
    exchange: str
    symbol: str
    token: str
    segment: str
    expiry: str | None = None
    strike: Decimal | None = None
    option_type: str | None = None
    lot_size: int | None = None
    instrument_type: str | None = None
    expiry_code: int | None = None

@dataclass(frozen=True)
class MarketTick:
    provider: str
    account_id: str
    exchange: str
    symbol: str
    token: str
    ltp: Decimal
    exchange_time: datetime | None
    received_at: datetime
    volume: int | None = None
    open_interest: int | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    raw: dict[str, Any] | None = None

@dataclass(frozen=True)
class HistoricalBar:
    provider: str
    exchange: str
    symbol: str
    interval: str
    start_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None = None
    open_interest: int | None = None

class MarketDataAdapter(Protocol):
    provider_code: str
    async def authenticate(self, account_id: str) -> None: ...
    async def search_instruments(self, query: str, limit: int = 100, exchange_segment: str | None = None) -> list[MarketInstrument]: ...
    async def get_historical(self, instrument: MarketInstrument, start: datetime, end: datetime, interval: str) -> list[HistoricalBar]: ...
    async def subscribe(self, instruments: list[MarketInstrument]) -> None: ...
    async def unsubscribe(self, instruments: list[MarketInstrument]) -> None: ...
    async def close(self) -> None: ...
