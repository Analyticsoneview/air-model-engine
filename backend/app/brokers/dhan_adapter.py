"""Normalized DhanHQ implementation of AIR's broker execution contract.

This adapter only routes orders when explicitly invoked by ExecutionService.
It does not enable live execution or create/renew credentials.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.brokers.base import (
    BrokerAdapter, BrokerCredentials, BrokerOrder, Instrument, OrderRequest, Quote,
)
from app.brokers.dhan import DhanHQClient


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (ValueError, TypeError):
        return None


class DhanBrokerAdapter(BrokerAdapter):
    broker_code = "dhan"

    def __init__(self, *, client: DhanHQClient | None = None) -> None:
        self.client = client
        self.account_id: str | None = None

    async def authenticate(self, credentials: BrokerCredentials) -> dict[str, Any]:
        account_id = credentials.account_id.strip()
        client_id = credentials.api_key.strip()
        if not account_id or not client_id or not credentials.access_token:
            raise ValueError("Dhan account_id, client_id and authorized access_token are required")
        if account_id != client_id:
            raise ValueError("Dhan account_id must match the Dhan client ID")
        if self.client is None:
            self.client = DhanHQClient(client_id, credentials.access_token)
        else:
            if getattr(self.client, "client_id", client_id) != client_id:
                raise PermissionError("Injected Dhan client belongs to another account")
            self.client.set_access_token(credentials.access_token)
        profile = await self.client.profile()
        if str(profile.get("dhanClientId", "")) != account_id:
            raise PermissionError("Authenticated Dhan profile does not match the selected account")
        self.account_id = account_id
        return {"broker": self.broker_code, "account_id": account_id, "authenticated": True}

    def _require_account(self, account_id: str) -> DhanHQClient:
        if self.client is None or self.account_id is None:
            raise PermissionError("Dhan account is not authenticated")
        if account_id.strip() != self.account_id:
            raise PermissionError("Dhan account ID mismatch")
        return self.client

    async def get_quotes(self, instruments: list[Instrument]) -> list[Quote]:
        if not instruments:
            return []
        if any(item.broker.lower() != self.broker_code for item in instruments):
            raise ValueError("All instruments must belong to Dhan")
        client = self._require_account(self.account_id or "")
        grouped: dict[str, list[int]] = {}
        by_key: dict[tuple[str, str], Instrument] = {}
        for item in instruments:
            security_id = _integer(item.token)
            if security_id is None or security_id <= 0:
                raise ValueError(f"Invalid Dhan security ID for {item.trading_symbol}")
            grouped.setdefault(item.segment, []).append(security_id)
            by_key[(item.segment, str(security_id))] = item
        payload = await client.market_feed("quote", grouped)
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected Dhan market-feed response")
        output: list[Quote] = []
        for segment, rows in data.items():
            if not isinstance(rows, dict):
                continue
            for security_id, raw in rows.items():
                if not isinstance(raw, dict):
                    continue
                instrument = by_key.get((segment, str(security_id)))
                if instrument is None:
                    continue
                ltp = _decimal(raw.get("last_price") or raw.get("ltp"))
                # Never manufacture a zero-price quote: downstream risk and valuation
                # checks must treat a missing/invalid provider price as unavailable.
                if ltp is None or ltp <= 0:
                    continue
                output.append(Quote(
                    broker=self.broker_code, exchange=instrument.exchange,
                    token=instrument.token,
                    ltp=ltp,
                    open=_decimal(raw.get("ohlc", {}).get("open") if isinstance(raw.get("ohlc"), dict) else raw.get("open")),
                    high=_decimal(raw.get("ohlc", {}).get("high") if isinstance(raw.get("ohlc"), dict) else raw.get("high")),
                    low=_decimal(raw.get("ohlc", {}).get("low") if isinstance(raw.get("ohlc"), dict) else raw.get("low")),
                    close=_decimal(raw.get("ohlc", {}).get("close") if isinstance(raw.get("ohlc"), dict) else raw.get("close")),
                    volume=_integer(raw.get("volume")), open_interest=_integer(raw.get("oi") or raw.get("open_interest")),
                    timestamp=str(raw.get("last_trade_time") or raw.get("timestamp") or "") or None,
                ))
        return output

    async def get_positions(self, account_id: str) -> list[dict[str, Any]]:
        data = await self._require_account(account_id).positions()
        return data

    async def get_holdings(self, account_id: str) -> list[dict[str, Any]]:
        return await self._require_account(account_id).holdings()

    async def get_order_book(self, account_id: str) -> list[BrokerOrder]:
        rows = await self._require_account(account_id).order_book()
        return [self._normalize_order(account_id, row) for row in rows]

    def _normalize_order(self, account_id: str, raw: dict[str, Any]) -> BrokerOrder:
        order_id = str(raw.get("orderId") or raw.get("order_id") or "")
        if not order_id:
            raise RuntimeError("Dhan response omitted broker order ID")
        return BrokerOrder(
            broker=self.broker_code, account_id=account_id,
            broker_order_id=order_id,
            status=str(raw.get("orderStatus") or raw.get("status") or "UNKNOWN").upper(),
            raw=raw,
        )

    async def place_order(self, order: OrderRequest) -> BrokerOrder:
        client = self._require_account(order.account_id)
        correlation_id = order.idempotency_key.strip()
        if not correlation_id or len(correlation_id) > 30:
            raise ValueError("Dhan idempotency_key must contain 1 to 30 characters")
        if order.quantity <= 0:
            raise ValueError("Order quantity must be positive")
        if order.side.upper() not in {"BUY", "SELL"}:
            raise ValueError("Order side must be BUY or SELL")
        response = await client.place_order(
            security_id=order.token, exchange_segment=order.exchange,
            transaction_type=order.side.upper(), product_type=order.product.upper(),
            order_type=order.order_type.upper(), quantity=order.quantity,
            validity=order.validity.upper(), price=order.price,
            trigger_price=order.trigger_price,
            correlation_id=correlation_id,
        )
        if not isinstance(response, dict):
            raise RuntimeError("Unexpected Dhan order response")
        return self._normalize_order(order.account_id, response)

    async def modify_order(self, account_id: str, broker_order_id: str,
                           changes: dict[str, Any]) -> BrokerOrder:
        mapping = {"order_type": "orderType", "quantity": "quantity",
                   "price": "price", "trigger_price": "triggerPrice",
                   "validity": "validity", "disclosed_quantity": "disclosedQuantity"}
        if not changes or set(changes) - set(mapping):
            raise ValueError("Unsupported Dhan order modification fields")
        payload = {mapping[key]: (value.upper() if key in {"order_type", "validity"} and isinstance(value, str) else value)
                   for key, value in changes.items()}
        raw = await self._require_account(account_id).modify_order(broker_order_id, payload)
        return self._normalize_order(account_id, raw)

    async def cancel_order(self, account_id: str, broker_order_id: str) -> BrokerOrder:
        raw = await self._require_account(account_id).cancel_order(broker_order_id)
        return self._normalize_order(account_id, raw)
