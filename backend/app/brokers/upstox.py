"""Upstox API v2/v3 OAuth and REST client."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

BASE_URL = "https://api.upstox.com"
LOGIN_URL = f"{BASE_URL}/v2/login/authorization/dialog"


class UpstoxAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"Upstox API error {status_code}: {message}")
        self.status_code = status_code


def upstox_login_url(client_id: str, redirect_uri: str, state: str) -> str:
    if not client_id.strip() or not redirect_uri.strip() or not state.strip():
        raise ValueError("client_id, redirect_uri and non-empty state are required")
    return f"{LOGIN_URL}?{urlencode({'response_type':'code','client_id':client_id,'redirect_uri':redirect_uri,'state':state})}"


class UpstoxClient:
    def __init__(self, access_token: str | None = None,
                 *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 15.0):
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=timeout, transport=transport,
        )
        self.set_access_token(access_token)

    def set_access_token(self, access_token: str | None) -> None:
        self.access_token = access_token.strip() if access_token else None
        if self.access_token:
            self._http.headers["Authorization"] = f"Bearer {self.access_token}"
        else:
            self._http.headers.pop("Authorization", None)

    async def _request(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> Any:
        if auth and not self.access_token:
            raise ValueError("Upstox access token is required")
        response = await self._http.request(method, path, **kwargs)
        if response.is_error:
            try:
                payload = response.json()
                message = payload.get("errors") or payload.get("message") or str(payload)
            except ValueError:
                message = response.text[:500]
            raise UpstoxAPIError(response.status_code, str(message))
        payload = response.json()
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise UpstoxAPIError(response.status_code, str(payload.get("errors", payload)))
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    async def exchange_code(self, code: str, client_id: str, client_secret: str,
                            redirect_uri: str) -> dict[str, Any]:
        if not all(v.strip() for v in (code, client_id, client_secret, redirect_uri)):
            raise ValueError("Authorization code and OAuth app credentials are required")
        data = await self._request(
            "POST", "/v2/login/authorization/token", auth=False,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"code": code, "client_id": client_id, "client_secret": client_secret,
                  "redirect_uri": redirect_uri, "grant_type": "authorization_code"},
        )
        if not isinstance(data, dict) or not data.get("access_token"):
            raise UpstoxAPIError(502, "Token exchange returned no access token")
        self.set_access_token(str(data["access_token"]))
        return data

    async def profile(self) -> dict[str, Any]:
        return await self._request("GET", "/v2/user/profile")

    async def quotes(self, instrument_keys: list[str], mode: str = "full") -> dict[str, Any]:
        paths = {"full": "/v2/market-quote/quotes", "ohlc": "/v3/market-quote/ohlc",
                 "ltp": "/v3/market-quote/ltp"}
        if mode not in paths or not instrument_keys or len(instrument_keys) > 500:
            raise ValueError("Invalid quote mode or instrument count")
        params = {"instrument_key": ",".join(instrument_keys)}
        if mode != "full" and mode == "ohlc":
            params["interval"] = "1d"
        return await self._request("GET", paths[mode], params=params)

    async def historical(self, instrument_key: str, unit: str, interval: int,
                         to_date: str, from_date: str | None = None) -> dict[str, Any]:
        if not instrument_key.strip() or unit not in {"minutes", "hours", "days", "weeks", "months"} or interval <= 0:
            raise ValueError("Invalid instrument key, candle unit or interval")
        if from_date:
            path = f"/v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}"
        else:
            path = f"/v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}"
        return await self._request("GET", path)

    async def intraday(self, instrument_key: str, unit: str, interval: int) -> dict[str, Any]:
        if not instrument_key.strip() or unit not in {"minutes", "hours"} or interval <= 0:
            raise ValueError("Invalid intraday candle parameters")
        return await self._request(
            "GET", f"/v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}"
        )

    async def order_book(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v2/order/retrieve-all")
        return data if isinstance(data, list) else []

    async def positions(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v2/portfolio/short-term-positions")
        return data if isinstance(data, list) else []

    async def holdings(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v2/portfolio/long-term-holdings")
        return data if isinstance(data, list) else []

    async def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = {"quantity", "product", "validity", "price", "tag",
                    "instrument_token", "order_type", "transaction_type", "disclosed_quantity", "trigger_price", "is_amo"}
        if required - set(payload):
            raise ValueError(f"Missing Upstox order fields: {sorted(required - set(payload))}")
        if int(payload["quantity"]) <= 0:
            raise ValueError("Order quantity must be positive")
        return await self._request("POST", "/v2/order/place", json=payload)

    async def modify_order(self, order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        if not order_id.strip() or not changes:
            raise ValueError("order_id and modifications are required")
        return await self._request("PUT", "/v2/order/modify", params={"order_id": order_id}, json=changes)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        if not order_id.strip():
            raise ValueError("order_id is required")
        return await self._request("DELETE", "/v2/order/cancel", params={"order_id": order_id})

    async def close(self) -> None:
        await self._http.aclose()
