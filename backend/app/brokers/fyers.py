"""FYERS API v3 server-side OAuth and REST client."""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlencode

import httpx

BASE_URL = "https://api-t1.fyers.in"
AUTH_URL = f"{BASE_URL}/api/v3/generate-authcode"


class FyersAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"FYERS API error {status_code}: {message}")
        self.status_code = status_code


def fyers_login_url(app_id: str, redirect_uri: str, state: str) -> str:
    if not all(v.strip() for v in (app_id, redirect_uri, state)):
        raise ValueError("app_id, redirect_uri and state are required")
    return f"{AUTH_URL}?{urlencode({'client_id':app_id,'redirect_uri':redirect_uri,'response_type':'code','state':state})}"


def fyers_app_id_hash(app_id: str, app_secret: str) -> str:
    if not app_id.strip() or not app_secret.strip():
        raise ValueError("app_id and app_secret are required")
    return hashlib.sha256(f"{app_id}:{app_secret}".encode()).hexdigest()


class FyersClient:
    def __init__(self, app_id: str, access_token: str | None = None,
                 *, transport: httpx.AsyncBaseTransport | None = None,
                 base_url: str = BASE_URL, timeout: float = 15.0):
        if not app_id.strip():
            raise ValueError("FYERS app_id is required")
        self.app_id = app_id.strip()
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Accept":"application/json","Content-Type":"application/json"},
            timeout=timeout, transport=transport,
        )
        self.set_access_token(access_token)

    def set_access_token(self, access_token: str | None) -> None:
        self.access_token = access_token.strip() if access_token else None
        if self.access_token:
            self._http.headers["Authorization"] = f"{self.app_id}:{self.access_token}"
        else:
            self._http.headers.pop("Authorization", None)

    async def _request(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> Any:
        if auth and not self.access_token:
            raise ValueError("FYERS access token is required")
        response = await self._http.request(method, path, **kwargs)
        if response.is_error:
            try:
                body = response.json()
                message = body.get("message") or str(body)
            except ValueError:
                message = response.text[:500]
            raise FyersAPIError(response.status_code, str(message))
        payload = response.json()
        if isinstance(payload, dict) and payload.get("s") == "error":
            raise FyersAPIError(response.status_code, str(payload.get("message", payload)))
        return payload

    async def exchange_auth_code(self, code: str, app_secret: str) -> dict[str, Any]:
        payload = {"grant_type":"authorization_code",
                   "appIdHash":fyers_app_id_hash(self.app_id, app_secret),"code":code}
        data = await self._request("POST", "/api/v3/validate-authcode", auth=False, json=payload)
        if not isinstance(data, dict) or not data.get("access_token"):
            raise FyersAPIError(502, "FYERS token exchange returned no access token")
        self.set_access_token(str(data["access_token"]))
        return data

    async def profile(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v3/profile")

    async def quotes(self, symbols: list[str]) -> dict[str, Any]:
        if not symbols or len(symbols) > 50 or any(":" not in s for s in symbols):
            raise ValueError("Provide 1 to 50 valid FYERS symbols")
        return await self._request("GET", "/data/quotes", params={"symbols": ",".join(symbols)})

    async def history(self, symbol: str, resolution: str, date_format: str,
                      range_from: str, range_to: str, *, cont_flag: str = "1") -> dict[str, Any]:
        if not symbol.strip() or not resolution.strip() or date_format not in {"0","1"}:
            raise ValueError("Invalid FYERS history request")
        payload = {"symbol":symbol,"resolution":resolution,"date_format":date_format,
                   "range_from":range_from,"range_to":range_to,"cont_flag":cont_flag}
        return await self._request("GET", "/data/history", params=payload)

    async def order_book(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v3/orders")

    async def positions(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v3/positions")

    async def holdings(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v3/holdings")

    async def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = {"symbol","qty","type","side","productType","limitPrice","stopPrice",
                    "validity","disclosedQty","offlineOrder","stopLoss","takeProfit"}
        if required - set(payload):
            raise ValueError(f"Missing FYERS order fields: {sorted(required - set(payload))}")
        if int(payload["qty"]) <= 0:
            raise ValueError("Order quantity must be positive")
        return await self._request("POST", "/api/v3/orders/sync", json=payload)

    async def modify_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload.get("id"):
            raise ValueError("FYERS order id is required")
        return await self._request("PATCH", "/api/v3/orders/sync", json=payload)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        if not order_id.strip():
            raise ValueError("FYERS order id is required")
        return await self._request("DELETE", "/api/v3/orders/sync", json={"id":order_id})

    async def close(self) -> None:
        await self._http.aclose()
