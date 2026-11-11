"""Normalized account-scoped adapters for Kite, Upstox, FYERS and Angel One.

These adapters normalize provider REST payloads to AIR's broker contract. They
are deliberately not registered globally and do not enable live execution.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.brokers.base import BrokerAdapter, BrokerCredentials, BrokerOrder, Instrument, OrderRequest, Quote
from app.brokers.zerodha import KiteConnectClient
from app.brokers.upstox import UpstoxClient
from app.brokers.fyers import FyersClient
from app.brokers.angel import AngelSmartAPI


def _dec(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if value not in (None, "") and result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _rows(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for key in keys:
            nested = value.get(key)
            if isinstance(nested, list):
                return [x for x in nested if isinstance(x, dict)]
    return []


class _NormalizedAdapter(BrokerAdapter):
    broker_code: str

    def __init__(self, client: Any = None) -> None:
        self.client = client
        self.account_id: str | None = None

    def _account(self, account_id: str) -> Any:
        if self.client is None or self.account_id is None:
            raise PermissionError(f"{self.broker_code} account is not authenticated")
        if account_id.strip() != self.account_id:
            raise PermissionError("Broker account ID mismatch")
        return self.client

    async def _profile(self) -> dict[str, Any]:
        profile = await self.client.profile()
        if not isinstance(profile, dict):
            raise PermissionError("Broker returned an invalid profile")
        return profile

    def _normalize_order(self, account_id: str, raw: dict[str, Any]) -> BrokerOrder:
        order_id = next((str(raw[k]) for k in self.order_id_fields if raw.get(k) not in (None, "")), "")
        if not order_id:
            raise RuntimeError(f"{self.broker_code} response omitted broker order ID")
        status = next((str(raw[k]) for k in self.status_fields if raw.get(k) not in (None, "")), "UNKNOWN")
        return BrokerOrder(self.broker_code, account_id, order_id, status.upper(), raw)

    async def get_positions(self, account_id: str) -> list[dict[str, Any]]:
        return _rows(await self._account(account_id).positions(), *self.position_keys)

    async def get_holdings(self, account_id: str) -> list[dict[str, Any]]:
        return _rows(await self._account(account_id).holdings(), *self.holding_keys)

    async def get_order_book(self, account_id: str) -> list[BrokerOrder]:
        rows = _rows(await self._account(account_id).orders() if self.broker_code == "zerodha"
                     else await self._account(account_id).order_book(), *self.order_keys)
        return [self._normalize_order(account_id, row) for row in rows]

    def _validate_order(self, order: OrderRequest) -> None:
        self._account(order.account_id)
        if order.quantity <= 0 or order.side.upper() not in {"BUY", "SELL"}:
            raise ValueError("Order quantity must be positive and side must be BUY or SELL")
        if not order.idempotency_key.strip():
            raise ValueError("An idempotency key is required")
        if order.order_type.upper() in {"LIMIT", "STOPLOSS_LIMIT", "SL"} and (order.price is None or order.price <= 0):
            raise ValueError("A positive limit price is required for this order type")
        if order.order_type.upper() in {"SL", "STOPLOSS_LIMIT", "STOPLOSS_MARKET"} and (order.trigger_price is None or order.trigger_price <= 0):
            raise ValueError("A positive trigger price is required for stop orders")


class ZerodhaBrokerAdapter(_NormalizedAdapter):
    broker_code = "zerodha"
    order_id_fields = ("order_id",)
    status_fields = ("status", "status_message")
    position_keys = ("net", "day")
    holding_keys = ()
    order_keys = ()

    async def authenticate(self, credentials: BrokerCredentials) -> dict[str, Any]:
        if not credentials.account_id.strip() or not credentials.api_key.strip() or not credentials.access_token:
            raise ValueError("Kite account_id, api_key and access_token are required")
        if self.client is None:
            self.client = KiteConnectClient(credentials.api_key, credentials.access_token)
        else:
            self.client.set_access_token(credentials.access_token)
        profile = await self._profile()
        user_id = str(profile.get("user_id") or profile.get("userId") or "")
        if user_id != credentials.account_id.strip():
            raise PermissionError("Kite profile does not match selected account")
        self.account_id = user_id
        return {"broker": self.broker_code, "account_id": user_id, "authenticated": True}

    async def get_quotes(self, instruments: list[Instrument]) -> list[Quote]:
        if not instruments: return []
        if any(i.broker.lower() != self.broker_code for i in instruments): raise ValueError("Mixed broker instruments")
        keys = [f"{i.exchange}:{i.trading_symbol}" for i in instruments]
        data = await self._account(self.account_id or "").quotes(keys)
        result = []
        for i, key in zip(instruments, keys):
            raw = data.get(key, {}) if isinstance(data, dict) else {}
            ltp = _dec(raw.get("last_price"))
            if ltp is None or ltp <= 0: continue
            ohlc = raw.get("ohlc") if isinstance(raw.get("ohlc"), dict) else {}
            result.append(Quote(self.broker_code, i.exchange, i.token, ltp, _dec(ohlc.get("open")),
                _dec(ohlc.get("high")), _dec(ohlc.get("low")), _dec(ohlc.get("close")),
                _int(raw.get("volume")), _int(raw.get("oi")), str(raw.get("timestamp") or "") or None))
        return result

    async def place_order(self, order: OrderRequest) -> BrokerOrder:
        self._validate_order(order)
        if len(order.idempotency_key) > 20: raise ValueError("Kite tag/idempotency key must be at most 20 characters")
        raw = await self.client.place_order({"variety":"regular","exchange":order.exchange,
            "tradingsymbol":order.symbol,"transaction_type":order.side.upper(),"quantity":order.quantity,
            "product":order.product.upper(),"order_type":order.order_type.upper(),
            "validity":order.validity.upper(),"price":float(order.price or 0),
            "trigger_price":float(order.trigger_price or 0),"tag":order.idempotency_key})
        return self._normalize_order(order.account_id, raw if isinstance(raw,dict) else {})

    async def modify_order(self, account_id: str, broker_order_id: str, changes: dict[str, Any]) -> BrokerOrder:
        allowed={"quantity":"quantity","price":"price","trigger_price":"trigger_price","order_type":"order_type","validity":"validity"}
        if not changes or set(changes)-set(allowed): raise ValueError("Unsupported Kite modification fields")
        raw=await self._account(account_id).modify_order("regular",broker_order_id,{allowed[k]:v for k,v in changes.items()})
        return self._normalize_order(account_id,raw)

    async def cancel_order(self, account_id: str, broker_order_id: str) -> BrokerOrder:
        raw=await self._account(account_id).cancel_order("regular",broker_order_id)
        return self._normalize_order(account_id,raw)


class UpstoxBrokerAdapter(_NormalizedAdapter):
    broker_code="upstox"
    order_id_fields=("order_id","orderId")
    status_fields=("status","order_status")
    position_keys=()
    holding_keys=()
    order_keys=()

    async def authenticate(self, credentials: BrokerCredentials) -> dict[str, Any]:
        if not credentials.account_id.strip() or not credentials.api_key.strip() or not credentials.access_token:
            raise ValueError("Upstox account_id, client_id and access_token are required")
        if self.client is None: self.client=UpstoxClient(credentials.access_token)
        else: self.client.set_access_token(credentials.access_token)
        profile=await self._profile()
        account=str(profile.get("user_id") or profile.get("userId") or profile.get("email") or "")
        if account != credentials.account_id.strip(): raise PermissionError("Upstox profile does not match selected account")
        self.account_id=account
        return {"broker":self.broker_code,"account_id":account,"authenticated":True}

    async def get_quotes(self, instruments: list[Instrument]) -> list[Quote]:
        if not instruments:return []
        if any(i.broker.lower()!=self.broker_code for i in instruments):raise ValueError("Mixed broker instruments")
        keys=[i.token for i in instruments]
        data=await self._account(self.account_id or "").quotes(keys)
        result=[]
        for i,key in zip(instruments,keys):
            raw=data.get(key,{}) if isinstance(data,dict) else {}
            ltp=_dec(raw.get("last_price") or raw.get("ltp"))
            if ltp is None or ltp<=0:continue
            o=raw.get("ohlc") if isinstance(raw.get("ohlc"),dict) else {}
            result.append(Quote(self.broker_code,i.exchange,i.token,ltp,_dec(o.get("open")),
                _dec(o.get("high")),_dec(o.get("low")),_dec(o.get("close")),
                _int(raw.get("volume")), _int(raw.get("oi") or raw.get("open_interest")),str(raw.get("timestamp") or "") or None))
        return result

    async def place_order(self, order: OrderRequest) -> BrokerOrder:
        self._validate_order(order)
        if len(order.idempotency_key)>40:raise ValueError("Upstox tag/idempotency key must be at most 40 characters")
        payload={"quantity":order.quantity,"product":order.product.upper(),"validity":order.validity.upper(),
            "price":float(order.price or 0),"tag":order.idempotency_key,"instrument_token":order.token,
            "order_type":order.order_type.upper(),"transaction_type":order.side.upper(),
            "disclosed_quantity":0,"trigger_price":float(order.trigger_price or 0),"is_amo":False}
        raw=await self.client.place_order(payload)
        return self._normalize_order(order.account_id,raw if isinstance(raw,dict) else {})

    async def modify_order(self, account_id: str, broker_order_id: str, changes: dict[str, Any]) -> BrokerOrder:
        allowed={"quantity","price","trigger_price","order_type","validity","disclosed_quantity"}
        if not changes or set(changes)-allowed:raise ValueError("Unsupported Upstox modification fields")
        raw=await self._account(account_id).modify_order(broker_order_id,changes)
        return self._normalize_order(account_id,raw)

    async def cancel_order(self, account_id: str, broker_order_id: str) -> BrokerOrder:
        raw=await self._account(account_id).cancel_order(broker_order_id)
        return self._normalize_order(account_id,raw)


class FyersBrokerAdapter(_NormalizedAdapter):
    broker_code="fyers"
    order_id_fields=("id","orderId")
    status_fields=("status","message")
    position_keys=("netPositions","overall")
    holding_keys=("holdings",)
    order_keys=("orderBook",)

    async def authenticate(self, credentials: BrokerCredentials) -> dict[str, Any]:
        metadata=credentials.metadata or {}
        app_id=credentials.api_key.strip()
        if not credentials.account_id.strip() or not app_id or not credentials.access_token:raise ValueError("FYERS account_id, app_id and access_token are required")
        if self.client is None:self.client=FyersClient(app_id,credentials.access_token)
        else:self.client.set_access_token(credentials.access_token)
        profile=await self._profile()
        account=str(profile.get("fy_id") or profile.get("id") or profile.get("user_id") or "")
        if account!=credentials.account_id.strip():raise PermissionError("FYERS profile does not match selected account")
        self.account_id=account
        return {"broker":self.broker_code,"account_id":account,"authenticated":True}

    async def get_quotes(self,instruments:list[Instrument])->list[Quote]:
        if not instruments:return []
        if any(i.broker.lower()!=self.broker_code for i in instruments):raise ValueError("Mixed broker instruments")
        symbols=[i.trading_symbol if ":" in i.trading_symbol else f"{i.exchange}:{i.trading_symbol}" for i in instruments]
        payload=await self._account(self.account_id or "").quotes(symbols)
        rows=_rows(payload,"d")
        by_symbol={str(r.get("n")):r for r in rows}
        out=[]
        for i,s in zip(instruments,symbols):
            raw=by_symbol.get(s,{})
            ltp=_dec(raw.get("v",{}).get("lp") if isinstance(raw.get("v"),dict) else raw.get("lp"))
            if ltp is None or ltp<=0:continue
            v=raw.get("v") if isinstance(raw.get("v"),dict) else raw
            out.append(Quote(self.broker_code,i.exchange,i.token,ltp,_dec(v.get("open_price")),
                _dec(v.get("high_price")),_dec(v.get("low_price")),_dec(v.get("prev_close_price")),
                _int(v.get("volume")), _int(v.get("oi")),None))
        return out

    async def place_order(self,order:OrderRequest)->BrokerOrder:
        self._validate_order(order)
        payload={"symbol":order.symbol,"qty":order.quantity,"type":{"LIMIT":1,"MARKET":2,"SL":3,"STOPLOSS_LIMIT":3,"STOPLOSS_MARKET":4}.get(order.order_type.upper(),0),
            "side":1 if order.side.upper()=="BUY" else -1,"productType":order.product.upper(),
            "limitPrice":float(order.price or 0),"stopPrice":float(order.trigger_price or 0),
            "validity":order.validity.upper(),"disclosedQty":0,"offlineOrder":False,
            "stopLoss":0,"takeProfit":0,"orderTag":order.idempotency_key[:20]}
        raw=await self.client.place_order(payload)
        return self._normalize_order(order.account_id,raw if isinstance(raw,dict) else {})

    async def modify_order(self,account_id:str,broker_order_id:str,changes:dict[str,Any])->BrokerOrder:
        allowed={"qty":"qty","quantity":"qty","limitPrice":"limitPrice","price":"limitPrice","stopPrice":"stopPrice","trigger_price":"stopPrice","type":"type","order_type":"type"}
        if not changes or set(changes)-set(allowed):raise ValueError("Unsupported FYERS modification fields")
        payload={"id":broker_order_id,**{allowed[k]:v for k,v in changes.items()}}
        raw=await self._account(account_id).modify_order(payload)
        return self._normalize_order(account_id,raw)

    async def cancel_order(self,account_id:str,broker_order_id:str)->BrokerOrder:
        raw=await self._account(account_id).cancel_order(broker_order_id)
        return self._normalize_order(account_id,raw)


class AngelBrokerAdapter(_NormalizedAdapter):
    broker_code="angel"
    order_id_fields=("orderid","orderId")
    status_fields=("status","orderstatus","text")
    position_keys=()
    holding_keys=()
    order_keys=()

    async def authenticate(self,credentials:BrokerCredentials)->dict[str,Any]:
        metadata=credentials.metadata or {}
        required=("client_local_ip","client_public_ip","mac_address")
        if not credentials.account_id.strip() or not credentials.api_key.strip() or not credentials.access_token or not all(metadata.get(k) for k in required):
            raise ValueError("Angel account, API key, authorized JWT and client network metadata are required")
        if self.client is None:
            self.client=AngelSmartAPI(credentials.api_key,credentials.account_id,
                client_local_ip=metadata["client_local_ip"],client_public_ip=metadata["client_public_ip"],
                mac_address=metadata["mac_address"],access_token=credentials.access_token)
        profile=await self._profile()
        account=str(profile.get("clientcode") or profile.get("clientCode") or "")
        if account!=credentials.account_id.strip():raise PermissionError("Angel profile does not match selected account")
        self.account_id=account
        return {"broker":self.broker_code,"account_id":account,"authenticated":True}

    async def get_quotes(self,instruments:list[Instrument])->list[Quote]:
        if not instruments:return []
        if any(i.broker.lower()!=self.broker_code for i in instruments):raise ValueError("Mixed broker instruments")
        grouped={}
        for i in instruments:grouped.setdefault(i.exchange,[]).append(i.token)
        data=await self._account(self.account_id or "").market_data("FULL",grouped)
        rows=_rows(data,"fetched","data")
        by_token={str(r.get("symbolToken")):r for r in rows}
        out=[]
        for i in instruments:
            raw=by_token.get(i.token,{})
            ltp=_dec(raw.get("ltp"))
            if ltp is None or ltp<=0:continue
            out.append(Quote(self.broker_code,i.exchange,i.token,ltp,_dec(raw.get("open")),
                _dec(raw.get("high")), _dec(raw.get("low")), _dec(raw.get("close")),
                _int(raw.get("tradeVolume")), _int(raw.get("opnInterest")),None))
        return out

    async def place_order(self,order:OrderRequest)->BrokerOrder:
        self._validate_order(order)
        if len(order.idempotency_key)>20:raise ValueError("Angel order tag must be at most 20 characters")
        payload={"variety":"NORMAL","tradingsymbol":order.symbol,"symboltoken":order.token,
            "transactiontype":order.side.upper(),"exchange":order.exchange,"ordertype":order.order_type.upper(),
            "producttype":order.product.upper(),"duration":order.validity.upper(),
            "price":str(order.price or 0),"quantity":str(order.quantity),"ordertag":order.idempotency_key}
        raw=await self.client.place_order(payload)
        return self._normalize_order(order.account_id,raw if isinstance(raw,dict) else {})

    async def modify_order(self,account_id:str,broker_order_id:str,changes:dict[str,Any])->BrokerOrder:
        allowed={"quantity":"quantity","price":"price","trigger_price":"triggerprice","order_type":"ordertype","validity":"duration"}
        if not changes or set(changes)-set(allowed):raise ValueError("Unsupported Angel modification fields")
        raw=await self._account(account_id).modify_order({"orderid":broker_order_id,**{allowed[k]:v for k,v in changes.items()}})
        return self._normalize_order(account_id,raw)

    async def cancel_order(self,account_id:str,broker_order_id:str)->BrokerOrder:
        raw=await self._account(account_id).cancel_order("NORMAL",broker_order_id)
        return self._normalize_order(account_id,raw)
