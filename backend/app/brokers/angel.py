"""Angel One SmartAPI REST client. Secrets and TOTP remain server-side."""
from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://apiconnect.angelone.in"
AUTH_LOGIN = "/rest/auth/angelbroking/user/v1/loginByPassword"
PROFILE = "/rest/secure/angelbroking/user/v1/getProfile"


class AngelAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"Angel SmartAPI error {status_code}: {message}")
        self.status_code = status_code


class AngelSmartAPI:
    def __init__(self, api_key: str, client_code: str, *,
                 client_local_ip: str, client_public_ip: str, mac_address: str,
                 access_token: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 15.0):
        values = (api_key, client_code, client_local_ip, client_public_ip, mac_address)
        if not all(v.strip() for v in values):
            raise ValueError("API key, client code and SmartAPI client network headers are required")
        self.api_key, self.client_code = api_key.strip(), client_code.strip()
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "X-PrivateKey": self.api_key, "X-SourceID": "WEB",
                "X-ClientLocalIP": client_local_ip, "X-ClientPublicIP": client_public_ip,
                "X-MACAddress": mac_address, "X-UserType": "USER",
                "Accept": "application/json", "Content-Type": "application/json",
            },
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
            raise ValueError("Angel SmartAPI JWT is required")
        response = await self._http.request(method, path, **kwargs)
        if response.is_error:
            try:
                body = response.json()
                message = body.get("message") or body.get("errorcode") or str(body)
            except ValueError:
                message = response.text[:500]
            raise AngelAPIError(response.status_code, str(message))
        payload = response.json()
        if isinstance(payload, dict) and payload.get("status") is False:
            raise AngelAPIError(response.status_code, str(payload.get("message", payload.get("errorcode", payload))))
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    async def login(self, pin: str, totp: str, state: str | None = None) -> dict[str, Any]:
        if not pin.strip() or not totp.strip():
            raise ValueError("Angel PIN and current TOTP are required")
        payload = {"clientcode": self.client_code, "password": pin, "totp": totp}
        if state:
            payload["state"] = state
        data = await self._request("POST", AUTH_LOGIN, auth=False, json=payload)
        if not isinstance(data, dict) or not data.get("jwtToken"):
            raise AngelAPIError(502, "Angel login returned no JWT token")
        self.set_access_token(str(data["jwtToken"]))
        return data

    async def profile(self) -> dict[str, Any]:
        return await self._request("GET", PROFILE)

    async def historical(self, exchange: str, symbol_token: str, interval: str,
                         from_date: str, to_date: str) -> list[list[Any]]:
        allowed = {"ONE_MINUTE","THREE_MINUTE","FIVE_MINUTE","TEN_MINUTE",
                   "FIFTEEN_MINUTE","THIRTY_MINUTE","ONE_HOUR","ONE_DAY"}
        if exchange not in {"NSE","NFO","BSE","BFO","MCX"} or interval not in allowed:
            raise ValueError("Unsupported Angel exchange or candle interval")
        data = await self._request(
            "POST", "/rest/secure/angelbroking/historical/v1/getCandleData",
            json={"exchange":exchange,"symboltoken":str(symbol_token),"interval":interval,
                  "fromdate":from_date,"todate":to_date},
        )
        return data if isinstance(data, list) else []

    async def order_book(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/rest/secure/angelbroking/order/v1/getOrderBook")
        return data if isinstance(data, list) else []

    async def positions(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/rest/secure/angelbroking/order/v1/getPosition")
        return data if isinstance(data, list) else []

    async def holdings(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/rest/secure/angelbroking/portfolio/v1/getHolding")
        return data if isinstance(data, list) else []

    async def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = {"variety","tradingsymbol","symboltoken","transactiontype","exchange",
                    "ordertype","producttype","duration","price","quantity"}
        if required - set(payload):
            raise ValueError(f"Missing Angel order fields: {sorted(required - set(payload))}")
        if int(payload["quantity"]) <= 0:
            raise ValueError("Order quantity must be positive")
        return await self._request("POST", "/rest/secure/angelbroking/order/v1/placeOrder", json=payload)

    async def modify_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload.get("orderid"):
            raise ValueError("Angel orderid is required")
        return await self._request("POST", "/rest/secure/angelbroking/order/v1/modifyOrder", json=payload)

    async def cancel_order(self, variety: str, order_id: str) -> dict[str, Any]:
        if not variety or not order_id:
            raise ValueError("Angel variety and orderid are required")
        return await self._request(
            "POST", "/rest/secure/angelbroking/order/v1/cancelOrder",
            json={"variety":variety,"orderid":order_id},
        )

    async def close(self) -> None:
        await self._http.aclose()
