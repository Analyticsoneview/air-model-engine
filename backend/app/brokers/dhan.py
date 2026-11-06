"""DhanHQ v2 REST client.

This module implements documented REST calls. It deliberately does not create
access tokens from PIN/TOTP or silently enable trading. Store the user-authorized
access token in CredentialVault, verify it with profile(), and keep order routing
disabled until static-IP and risk checks are independently satisfied.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

BASE_URL = "https://api.dhan.co/v2"


class DhanAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"DhanHQ API error {status_code}: {message}")
        self.status_code = status_code


class DhanHQClient:
    def __init__(self, client_id: str, access_token: str,
                 *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 15.0):
        if not client_id.strip() or not access_token.strip():
            raise ValueError("Dhan client_id and access_token are required")
        self.client_id = client_id.strip()
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "access-token": access_token.strip(),
                "client-id": self.client_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._http.request(method, path, **kwargs)
        if response.is_error:
            try:
                body = response.json()
                message = body.get("errorMessage") or body.get("message") or str(body)
            except ValueError:
                message = response.text[:500]
            raise DhanAPIError(response.status_code, message)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    async def profile(self) -> dict[str, Any]:
        """Validate token and return Dhan account/data entitlement metadata."""
        data = await self._request("GET", "/profile")
        if not isinstance(data, dict) or str(data.get("dhanClientId", "")) != self.client_id:
            raise DhanAPIError(401, "Profile response did not match configured Dhan client ID")
        return data

    async def market_feed(self, mode: str, instruments: dict[str, list[int]]) -> dict[str, Any]:
        if mode not in {"ltp", "ohlc", "quote"}:
            raise ValueError("mode must be ltp, ohlc or quote")
        if not instruments or sum(len(v) for v in instruments.values()) > 1000:
            raise ValueError("Supply between 1 and 1000 instruments")
        if any(not isinstance(ids, list) or not ids or any(int(x) <= 0 for x in ids)
               for ids in instruments.values()):
            raise ValueError("Each exchange segment must contain positive security IDs")
        return await self._request("POST", f"/marketfeed/{mode}", json=instruments)

    async def historical_daily(self, *, security_id: str, exchange_segment: str,
                               instrument: str, from_date: str, to_date: str,
                               expiry_code: int = 0, oi: bool = False) -> dict[str, Any]:
        payload = {
            "securityId": str(security_id), "exchangeSegment": exchange_segment,
            "instrument": instrument, "expiryCode": expiry_code, "oi": oi,
            "fromDate": from_date, "toDate": to_date,
        }
        return await self._request("POST", "/charts/historical", json=payload)

    async def historical_intraday(self, *, security_id: str, exchange_segment: str,
                                  instrument: str, interval: int, from_date: str,
                                  to_date: str, oi: bool = False) -> dict[str, Any]:
        if interval not in {1, 5, 15, 25, 60}:
            raise ValueError("Dhan intraday interval must be 1, 5, 15, 25 or 60 minutes")
        payload = {
            "securityId": str(security_id), "exchangeSegment": exchange_segment,
            "instrument": instrument, "interval": str(interval), "oi": oi,
            "fromDate": from_date, "toDate": to_date,
        }
        return await self._request("POST", "/charts/intraday", json=payload)

    async def order_book(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/orders")
        if not isinstance(data, list):
            raise DhanAPIError(502, "Unexpected order-book response")
        return data

    async def place_order(self, *, security_id: str, exchange_segment: str,
                          transaction_type: str, product_type: str, order_type: str,
                          quantity: int, validity: str = "DAY",
                          price: Decimal | None = None,
                          trigger_price: Decimal | None = None,
                          correlation_id: str) -> dict[str, Any]:
        """Place one Dhan order; caller must enforce AIR live-risk and confirmation gates."""
        if transaction_type not in {"BUY", "SELL"}:
            raise ValueError("transaction_type must be BUY or SELL")
        if product_type not in {"CNC", "INTRADAY", "MARGIN", "MTF", "CO", "BO"}:
            raise ValueError("Unsupported Dhan product_type")
        order_types = {"LIMIT", "MARKET", "SL": "STOP_LOSS", "SL-M": "STOP_LOSS_MARKET"}
        mapped_order_type = order_types.get(order_type, order_type)
        if mapped_order_type not in {"LIMIT", "MARKET", "STOP_LOSS", "STOP_LOSS_MARKET"}:
            raise ValueError("Unsupported Dhan order_type")
        if quantity <= 0 or not correlation_id or len(correlation_id) > 30:
            raise ValueError("Positive quantity and correlation_id (max 30 chars) are required")
        if mapped_order_type == "LIMIT" and (price is None or price <= 0):
            raise ValueError("A positive limit price is required")
        if mapped_order_type in {"STOP_LOSS", "STOP_LOSS_MARKET"} and (trigger_price is None or trigger_price <= 0):
            raise ValueError("A positive trigger price is required")
        payload = {
            "dhanClientId": self.client_id,
            "correlationId": correlation_id,
            "transactionType": transaction_type,
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": mapped_order_type,
            "validity": validity,
            "securityId": str(security_id),
            "quantity": quantity,
            "price": float(price) if price is not None else 0,
            "triggerPrice": float(trigger_price) if trigger_price is not None else 0,
        }
        return await self._request("POST", "/orders", json=payload)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        if not order_id.strip():
            raise ValueError("order_id is required")
        return await self._request("DELETE", f"/orders/{order_id}")

    async def modify_order(self, order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {"orderType", "quantity", "price", "triggerPrice", "validity", "disclosedQuantity"}
        if not order_id.strip() or not changes or set(changes) - allowed:
            raise ValueError("Valid order_id and supported modification fields are required")
        payload = {"dhanClientId": self.client_id, "orderId": order_id, **changes}
        return await self._request("PUT", f"/orders/{order_id}", json=payload)

    async def close(self) -> None:
        await self._http.aclose()
