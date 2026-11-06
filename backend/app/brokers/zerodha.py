"""Zerodha Kite Connect v3 server-side REST client."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx

BASE_URL = "https://api.kite.trade"
LOGIN_URL = "https://kite.zerodha.com/connect/login"


class KiteAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"Kite Connect error {status_code}: {message}")
        self.status_code = status_code


def kite_login_url(api_key: str) -> str:
    if not api_key.strip():
        raise ValueError("Kite API key is required")
    return f"{LOGIN_URL}?{urlencode({'v': '3', 'api_key': api_key.strip()})}"


def kite_session_checksum(api_key: str, request_token: str, api_secret: str) -> str:
    if not all(value.strip() for value in (api_key, request_token, api_secret)):
        raise ValueError("api_key, request_token and api_secret are required")
    return hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()


class KiteConnectClient:
    def __init__(self, api_key: str, access_token: str | None = None,
                 *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 10.0):
        if not api_key.strip():
            raise ValueError("Kite API key is required")
        self.api_key = api_key.strip()
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"X-Kite-Version": "3", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )
        self.set_access_token(access_token)

    def set_access_token(self, access_token: str | None) -> None:
        self.access_token = access_token.strip() if access_token else None
        if self.access_token:
            self._http.headers["Authorization"] = f"token {self.api_key}:{self.access_token}"
        else:
            self._http.headers.pop("Authorization", None)

    async def _request(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> Any:
        if auth and not self.access_token:
            raise ValueError("Kite access token is required")
        response = await self._http.request(method, path, **kwargs)
        if response.is_error:
            try:
                payload = response.json()
                message = payload.get("message") or payload.get("error_type") or str(payload)
            except ValueError:
                message = response.text[:500]
            raise KiteAPIError(response.status_code, message)
        payload = response.json()
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise KiteAPIError(response.status_code, payload.get("message", "Kite API error"))
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    async def exchange_request_token(self, request_token: str, api_secret: str) -> dict[str, Any]:
        checksum = kite_session_checksum(self.api_key, request_token, api_secret)
        data = await self._request(
            "POST", "/session/token", auth=False,
            data={"api_key": self.api_key, "request_token": request_token, "checksum": checksum},
        )
        if not isinstance(data, dict) or not data.get("access_token"):
            raise KiteAPIError(502, "Kite token exchange returned no access token")
        self.set_access_token(str(data["access_token"]))
        return data

    async def profile(self) -> dict[str, Any]:
        return await self._request("GET", "/user/profile")

    async def quotes(self, instruments: list[str], mode: str = "quote") -> dict[str, Any]:
        endpoints = {"quote": "/quote", "ohlc": "/quote/ohlc", "ltp": "/quote/ltp"}
        if mode not in endpoints or not instruments or len(instruments) > (500 if mode == "quote" else 1000):
            raise ValueError("Invalid quote mode or instrument count")
        if any(":" not in item for item in instruments):
            raise ValueError("Instruments must use EXCHANGE:TRADINGSYMBOL format")
        return await self._request("GET", endpoints[mode], params=[("i", item) for item in instruments])

    async def historical(self, instrument_token: int, interval: str,
                         from_date: datetime, to_date: datetime,
                         *, continuous: bool = False, oi: bool = False) -> list[list[Any]]:
        allowed = {"minute", "3minute", "5minute", "10minute", "15minute",
                    "30minute", "60minute", "day"}
        if instrument_token <= 0 or interval not in allowed or from_date >= to_date:
            raise ValueError("Invalid token, interval or historical date range")
        data = await self._request(
            "GET", f"/instruments/historical/{instrument_token}/{interval}",
            params={"from": from_date.isoformat(sep=" "), "to": to_date.isoformat(sep=" "),
                    "continuous": 1 if continuous else 0, "oi": 1 if oi else 0},
        )
        return data.get("candles", []) if isinstance(data, dict) else data

    async def orders(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/orders")
        return data if isinstance(data, list) else []

    async def positions(self) -> dict[str, Any]:
        return await self._request("GET", "/portfolio/positions")

    async def holdings(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/portfolio/holdings")
        return data if isinstance(data, list) else []

    async def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        required = {"variety", "exchange", "tradingsymbol", "transaction_type",
                    "quantity", "product", "order_type"}
        if required - set(params):
            raise ValueError(f"Missing Kite order fields: {sorted(required - set(params))}")
        if int(params["quantity"]) <= 0:
            raise ValueError("Order quantity must be positive")
        return await self._request("POST", f"/orders/{params['variety']}", data=params)

    async def modify_order(self, variety: str, order_id: str, params: dict[str, Any]) -> dict[str, Any]:
        if not variety or not order_id or not params:
            raise ValueError("variety, order_id and modifications are required")
        return await self._request("PUT", f"/orders/{variety}/{order_id}", data=params)

    async def cancel_order(self, variety: str, order_id: str) -> dict[str, Any]:
        if not variety or not order_id:
            raise ValueError("variety and order_id are required")
        return await self._request("DELETE", f"/orders/{variety}/{order_id}")

    async def close(self) -> None:
        await self._http.aclose()
