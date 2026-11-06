import os
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.auth_store import AuthStore
from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount
from app.brokers.catalog import get_broker_catalog, is_supported_broker
from app.brokers.dhan import DhanHQClient, DhanAPIError
from app.credential_vault import CredentialVault
from app.market_data.hub import MarketDataHub
from app.market_data.router import MarketDataRouter
from app.security import create_access_token, hash_password, require_customer, verify_password

app = FastAPI(title="AIR Model Engine API", version="0.3.0",
              description="Self-hosted AIR authentication, broker account and market-data gateway.")
market_data_router = MarketDataRouter()
market_data_hub = MarketDataHub()
auth_store = AuthStore(os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3"))
account_directory = CustomerAccountDirectory(os.getenv("AIR_ACCOUNT_DB_PATH", "data/customer_accounts.sqlite3"))
_credential_vault: CredentialVault | None = None


def require_air_operator(customer_id: str = Depends(require_customer)) -> str:
    allowed = {
        value.strip() for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    }
    if not allowed or customer_id not in allowed:
        raise HTTPException(status_code=403, detail="AIR operator permission is required")
    return customer_id


def get_vault() -> CredentialVault:
    global _credential_vault
    if _credential_vault is None:
        try:
            _credential_vault = CredentialVault(os.getenv("AIR_CREDENTIAL_DB_PATH", "data/air_credentials.sqlite3"))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Credential vault is not configured on the server") from exc
    return _credential_vault


class CustomerRegistration(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class CustomerLogin(BaseModel):
    email: str
    password: str


class TradingAccountCreate(BaseModel):
    broker: str = Field(min_length=2, max_length=40)
    account_id: str = Field(min_length=2, max_length=100)


class OrderPermissionUpdate(BaseModel):
    enabled: bool


class BrokerCredentialInput(BaseModel):
    credentials: dict[str, str]


class MainAccountSelection(BaseModel):
    provider: str
    account_id: str


class DhanMarketFeedRequest(BaseModel):
    mode: str = Field(pattern="^(ltp|ohlc|quote)$")
    instruments: dict[str, list[int]]


class DhanHistoricalRequest(BaseModel):
    security_id: str = Field(min_length=1, max_length=30)
    exchange_segment: str = Field(min_length=2, max_length=30)
    instrument: str = Field(min_length=2, max_length=30)
    from_date: str
    to_date: str
    interval: int | None = Field(default=None, ge=1, le=60)
    expiry_code: int = Field(default=0, ge=0, le=3)
    oi: bool = False


@app.get("/api/v1/brokers/catalog")
async def broker_catalog(customer_id: str = Depends(require_customer)) -> dict:
    return {
        "brokers": get_broker_catalog(),
        "note": "Catalog entries describe supported integration targets; none is live-authorized until its provider handshake is implemented and verified.",
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "air-model-engine-api"}


@app.post("/api/v1/auth/register", status_code=201)
async def register_customer(body: CustomerRegistration) -> dict:
    if os.getenv("AIR_ALLOW_CUSTOMER_SIGNUP", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Customer registration is disabled; contact AIR administrator")
    try:
        customer_id = str(uuid4())
        auth_store.create_customer(customer_id, body.email, hash_password(body.password))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="Email is already registered") from exc
        raise
    return {"customer_id": customer_id, "status": "created"}


@app.post("/api/v1/auth/login")
async def login_customer(body: CustomerLogin) -> dict:
    row = auth_store.get_by_email(body.email)
    if row is None or not row["is_active"] or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(row["customer_id"])
    return {"access_token": token, "token_type": "bearer", "expires_in": 1800,
            "customer_id": row["customer_id"]}


@app.get("/api/v1/customer/accounts")
async def list_customer_accounts(customer_id: str = Depends(require_customer)) -> dict:
    accounts = account_directory.list_for_customer(customer_id)
    try:
        credentials = get_vault().list_for_customer(customer_id)
        credential_keys = {(r["broker"], r["account_id"]) for r in credentials}
        vault_configured = True
    except HTTPException:
        credential_keys = set()
        vault_configured = False
    return {"accounts": [
        {"broker": a.broker, "account_id": a.account_id,
         "order_enabled": a.enabled_for_orders,
         "credentials_saved": (a.broker, a.account_id) in credential_keys}
        for a in accounts
    ], "credential_vault_configured": vault_configured}


@app.post("/api/v1/customer/accounts", status_code=201)
async def add_customer_account(body: TradingAccountCreate,
                               customer_id: str = Depends(require_customer)) -> dict:
    if not is_supported_broker(body.broker):
        raise HTTPException(status_code=422, detail="Unsupported broker. Use the AIR broker catalog.")
    try:
        account_directory.add(CustomerTradingAccount(customer_id, body.broker, body.account_id, False))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"broker": body.broker.lower(), "account_id": body.account_id,
            "order_enabled": False, "status": "registered"}


@app.put("/api/v1/customer/accounts/{broker}/{account_id}/order-permission")
async def set_customer_order_permission(broker: str, account_id: str, body: OrderPermissionUpdate,
                                        customer_id: str = Depends(require_customer)) -> dict:
    try:
        if body.enabled:
            # Permission enablement is intentionally blocked until an adapter and broker
            # authorization verification flow are installed.
            raise HTTPException(status_code=409, detail="Order permission requires verified broker authorization; not enabled yet")
        account_directory.set_order_permission(customer_id, broker, account_id, False)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"broker": broker.lower(), "account_id": account_id, "order_enabled": False}


@app.put("/api/v1/customer/accounts/{broker}/{account_id}/credentials")
async def save_customer_broker_credentials(broker: str, account_id: str, body: BrokerCredentialInput,
                                           customer_id: str = Depends(require_customer)) -> dict:
    try:
        owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(customer_id)}
        if (broker.lower(), account_id) not in owned:
            raise PermissionError("Customer does not own this broker account")
        get_vault().put(customer_id, broker, account_id, body.credentials)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"broker": broker.lower(), "account_id": account_id, "credentials_saved": True}


@app.delete("/api/v1/customer/accounts/{broker}/{account_id}")
async def remove_customer_account(broker: str, account_id: str,
                                  customer_id: str = Depends(require_customer)) -> dict:
    vault = get_vault()
    try:
        vault.delete(customer_id, broker, account_id)
        account_directory.remove(customer_id, broker, account_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "removed", "broker": broker.lower(), "account_id": account_id}



def get_dhan_client(customer_id: str, account_id: str) -> DhanHQClient:
    try:
        credentials = get_vault().get(customer_id, "dhan", account_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Dhan credentials have not been saved") from exc
    client_id = credentials.get("client_id", account_id)
    access_token = credentials.get("access_token")
    if not access_token:
        raise HTTPException(status_code=422, detail="Saved Dhan credentials require client_id and access_token")
    return DhanHQClient(client_id, access_token)


@app.post("/api/v1/customer/accounts/dhan/{account_id}/verify")
async def verify_dhan_account(account_id: str, customer_id: str = Depends(require_air_operator)) -> dict:
    owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(customer_id)}
    if ("dhan", account_id) not in owned:
        raise HTTPException(status_code=404, detail="Dhan account not found")
    client = get_dhan_client(customer_id, account_id)
    try:
        profile = await client.profile()
        return {
            "broker": "dhan", "account_id": account_id, "verified": True,
            "token_validity": profile.get("tokenValidity"),
            "data_plan": profile.get("dataPlan"),
            "data_validity": profile.get("dataValidity"),
            "active_segments": profile.get("activeSegment"),
            "order_permission_enabled": False,
            "note": "Token and client ID verified. Live order permission remains disabled.",
        }
    except DhanAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Dhan verification failed; check token validity and API entitlement") from exc
    finally:
        await client.close()


@app.post("/api/v1/customer/accounts/dhan/{account_id}/market-feed")
async def dhan_market_feed(account_id: str, body: DhanMarketFeedRequest,
                           customer_id: str = Depends(require_air_operator)) -> dict:
    active = market_data_router.status().get("active_data_account")
    if active != {"provider": "dhan", "account_id": account_id}:
        raise HTTPException(status_code=409, detail="Market data requests must use the configured single Main Account")
    client = get_dhan_client(customer_id, account_id)
    try:
        return await client.market_feed(body.mode, body.instruments)
    except DhanAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Dhan market-data request failed; verify Data API entitlement") from exc
    finally:
        await client.close()


@app.post("/api/v1/customer/accounts/dhan/{account_id}/historical")
async def dhan_historical(account_id: str, body: DhanHistoricalRequest,
                          customer_id: str = Depends(require_air_operator)) -> dict:
    active = market_data_router.status().get("active_data_account")
    if active != {"provider": "dhan", "account_id": account_id}:
        raise HTTPException(status_code=409, detail="Historical data must use the configured single Main Account")
    client = get_dhan_client(customer_id, account_id)
    try:
        if body.interval is None:
            return await client.historical_daily(
                security_id=body.security_id, exchange_segment=body.exchange_segment,
                instrument=body.instrument, from_date=body.from_date,
                to_date=body.to_date, expiry_code=body.expiry_code, oi=body.oi,
            )
        return await client.historical_intraday(
            security_id=body.security_id, exchange_segment=body.exchange_segment,
            instrument=body.instrument, interval=body.interval,
            from_date=body.from_date, to_date=body.to_date, oi=body.oi,
        )
    except DhanAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Dhan historical-data request failed; verify Data API entitlement") from exc
    finally:
        await client.close()

@app.get("/api/v1/market-data/status")
async def market_data_status(customer_id: str = Depends(require_air_operator)) -> dict:
    return {
        "routing": market_data_router.status(),
        "stream": market_data_hub.status(),
        "note": "No broker provider is connected until a provider adapter and credentials are configured.",
    }


@app.put("/api/v1/market-data/main-account")
async def select_main_account(selection: MainAccountSelection,
                              customer_id: str = Depends(require_air_operator)) -> dict:
    try:
        owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(customer_id)}
        if (selection.provider.lower(), selection.account_id) not in owned:
            raise HTTPException(status_code=404, detail="Customer does not own this Main Account")
        get_vault().get(customer_id, selection.provider, selection.account_id)
        await market_data_router.set_main_account(selection.provider, selection.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"routing": market_data_router.status()}


@app.delete("/api/v1/market-data/main-account")
async def disconnect_main_account(customer_id: str = Depends(require_air_operator)) -> dict:
    try:
        await market_data_router.clear_main_account()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"routing": market_data_router.status()}


@app.websocket("/ws/market-data")
async def market_data_stream(websocket: WebSocket) -> None:
    authorization = websocket.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        await websocket.close(code=4401)
        return
    try:
        from app.security import _secret
        import jwt
        payload = jwt.decode(authorization[7:], _secret("AIR_JWT_SECRET"),
                             algorithms=["HS256"], issuer="air-model-engine",
                             audience="air-api")
        customer_id = payload.get("sub")
        if not customer_id or not auth_store.is_active(customer_id):
            raise ValueError("Inactive customer")
        allowed_operators = {
            value.strip() for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
            if value.strip()
        }
        if customer_id not in allowed_operators:
            await websocket.close(code=4403)
            return
    except Exception:
        await websocket.close(code=4401)
        return
    await market_data_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await market_data_hub.disconnect(websocket)
