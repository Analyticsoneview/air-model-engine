import os
from uuid import uuid4
import secrets

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.auth_store import AuthStore
from app.access_control import access_store
from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount
from app.brokers.catalog import get_broker_catalog, is_supported_broker
from app.brokers.dhan import DhanHQClient, DhanAPIError
from app.brokers.zerodha import KiteConnectClient, KiteAPIError, kite_login_url
from app.brokers.upstox import UpstoxClient, UpstoxAPIError, upstox_login_url
from app.brokers.fyers import FyersClient, FyersAPIError, fyers_login_url
from app.brokers.angel import AngelSmartAPI, AngelAPIError
from app.credential_vault import CredentialVault
from app.market_data.hub import MarketDataHub
from app.market_data.router import MarketDataRouter
from app.market_data.dhan_adapter import DhanMarketDataAdapter
from app.market_data.contracts import MarketInstrument
from app.air_qoc_dhan import router as air_qoc_dhan_router
from app.model_engine_api import router as model_engine_router
from app.air_qoc_scheduler import start_qoc_scheduler, stop_qoc_scheduler, capture_dhan_eod_snapshots
from app.air_telegram_scheduler import start_telegram_scheduler, stop_telegram_scheduler
from app.security import create_access_token, hash_password, require_customer, verify_password

app = FastAPI(title="AIR Model Engine API", version="0.3.0",
              description="Self-hosted AIR authentication, broker account and market-data gateway.")
app.include_router(air_qoc_dhan_router)
app.include_router(model_engine_router)
_cors_origins = [
    origin.strip() for origin in os.getenv("AIR_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-AIR-ADMIN-KEY"],
)
market_data_router = MarketDataRouter()
market_data_hub = MarketDataHub()
auth_store = AuthStore(os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3"))
account_directory = CustomerAccountDirectory(os.getenv("AIR_ACCOUNT_DB_PATH", "data/customer_accounts.sqlite3"))
_credential_vault: CredentialVault | None = None
_upstox_oauth_states: dict[tuple[str, str], str] = {}
_fyers_oauth_states: dict[tuple[str, str], str] = {}


def require_air_operator(customer_id: str = Depends(require_customer)) -> str:
    allowed = {
        value.strip() for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    }
    # New mobile tokens use the stable E.164 subject. Accept older beta
    # tokens whose subject was the device request UUID by resolving it safely.
    operator_identity = customer_id
    if customer_id not in allowed:
        operator_identity = access_store.mobile_for_request_id(customer_id) or ""
    if not allowed or operator_identity not in allowed:
        raise HTTPException(status_code=403, detail="AIR operator permission is required")
    return customer_id


@app.on_event("startup")
async def start_air_qoc_jobs() -> None:
    start_qoc_scheduler()
    start_telegram_scheduler()


@app.on_event("shutdown")
async def stop_air_qoc_jobs() -> None:
    stop_telegram_scheduler()
    stop_qoc_scheduler()


@app.post("/api/v1/air-qoc/run-eod-capture", dependencies=[Depends(require_air_admin)])
async def run_air_qoc_eod_capture() -> dict:
    try:
        return await capture_dhan_eod_snapshots(force=True)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AIR QOC data capture failed: {type(exc).__name__}") from exc


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


class MobileAccessRequest(BaseModel):
    mobile_e164: str = Field(min_length=9, max_length=16)
    device_id: str = Field(min_length=8, max_length=128)


class AccessReview(BaseModel):
    status: str = Field(pattern="^(APPROVED|REJECTED|BLOCKED)$")
    note: str = Field(default="", max_length=500)


def require_air_admin(x_air_admin_key: str | None = Header(default=None)) -> None:
    key_file = os.getenv("AIR_ADMIN_API_KEY_FILE")
    configured = open(key_file, encoding="utf-8").read().strip() if key_file else os.getenv("AIR_ADMIN_API_KEY", "")
    if len(configured) < 32 or not x_air_admin_key or not secrets.compare_digest(x_air_admin_key, configured):
        raise HTTPException(status_code=403, detail="AIR administrator approval is required")


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


class ZerodhaTokenExchangeRequest(BaseModel):
    request_token: str = Field(min_length=8, max_length=256)


class UpstoxTokenExchangeRequest(BaseModel):
    code: str = Field(min_length=4, max_length=512)
    state: str = Field(min_length=8, max_length=256)


class FyersTokenExchangeRequest(BaseModel):
    auth_code: str = Field(min_length=8, max_length=2048)
    state: str = Field(min_length=8, max_length=256)


class AngelLoginRequest(BaseModel):
    totp: str = Field(min_length=6, max_length=8)


class DhanMarketFeedRequest(BaseModel):
    mode: str = Field(pattern="^(ltp|ohlc|quote)$")
    instruments: dict[str, list[int]]


class MarketSubscriptionInstrument(BaseModel):
    exchange: str = Field(min_length=2, max_length=20)
    symbol: str = Field(min_length=1, max_length=100)
    token: str = Field(min_length=1, max_length=30)
    segment: str = Field(min_length=2, max_length=30)


class MarketSubscriptionRequest(BaseModel):
    instruments: list[MarketSubscriptionInstrument] = Field(min_length=1, max_length=5000)


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


@app.post("/api/v1/auth/mobile-login")
async def mobile_login(body: MobileAccessRequest) -> dict:
    try:
        request = access_store.request_access(body.mobile_e164, body.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request["status"] == "PENDING":
        return {"status": "PENDING", "message": "Your AIR access request is awaiting administrator approval."}
    if request["status"] != "APPROVED":
        return {"status": request["status"], "message": "AIR access is not currently available for this request."}
    session_id = access_store.create_session(request["request_id"])
    # Use the approved E.164 identity as the stable customer/operator subject.
    # Each device still has its own revocable session (jti) in AccessStore.
    token = create_access_token(body.mobile_e164, expires_minutes=525600, session_id=session_id)
    return {"status": "APPROVED", "access_token": token, "token_type": "bearer",
            "expires_in": 31536000, "customer_id": body.mobile_e164}


@app.get("/api/v1/auth/mobile-status")
async def mobile_access_status(mobile_e164: str = Query(min_length=9, max_length=16),
                               device_id: str = Query(min_length=8, max_length=128)) -> dict:
    try:
        request = access_store.get_request(access_store.validate_mobile(mobile_e164), device_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request is None:
        return {"status": "NOT_SUBMITTED"}
    return {"status": request["status"], "message": (
        "Your AIR access request is awaiting administrator approval."
        if request["status"] == "PENDING" else "AIR access request status: " + request["status"]
    )}


@app.get("/api/v1/auth/me")
async def current_customer(customer_id: str = Depends(require_customer)) -> dict:
    return {"customer_id": customer_id, "status": "APPROVED"}


@app.get("/api/v1/admin/access-requests", dependencies=[Depends(require_air_admin)])
async def list_access_requests(status: str | None = Query(default=None, pattern="^(PENDING|APPROVED|REJECTED|BLOCKED)$")) -> dict:
    return {"requests": [dict(row) for row in access_store.list_requests(status)]}


@app.put("/api/v1/admin/access-requests/{request_id}", dependencies=[Depends(require_air_admin)])
async def review_access_request(request_id: str, body: AccessReview) -> dict:
    if not access_store.review(request_id, body.status, body.note):
        raise HTTPException(status_code=404, detail="Access request not found")
    return {"request_id": request_id, "status": body.status, "updated": True}


@app.get("/api/v1/operator/access-requests")
async def operator_list_access_requests(
    status: str | None = Query(default=None, pattern="^(PENDING|APPROVED|REJECTED|BLOCKED)$"),
    customer_id: str = Depends(require_air_operator),
) -> dict:
    return {"requests": [dict(row) for row in access_store.list_requests(status)]}


@app.put("/api/v1/operator/access-requests/{request_id}")
async def operator_review_access_request(
    request_id: str,
    body: AccessReview,
    customer_id: str = Depends(require_air_operator),
) -> dict:
    if not access_store.review(request_id, body.status, body.note):
        raise HTTPException(status_code=404, detail="Access request not found")
    return {"request_id": request_id, "status": body.status, "updated": True}


@app.post("/api/v1/auth/register", status_code=410)
async def register_customer() -> dict:
    raise HTTPException(status_code=410, detail="Email/password registration is disabled. Use mobile access request.")


@app.post("/api/v1/auth/login")
async def login_customer(body: CustomerLogin) -> dict:
    # Legacy operator login only. End customers must use the admin-approved mobile flow.
    row = auth_store.get_by_email(body.email)
    allowed = {
        value.strip() for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    }
    if (row is None or not row["is_active"] or not verify_password(body.password, row["password_hash"])
            or row["customer_id"] not in allowed):
        raise HTTPException(status_code=401, detail="Invalid operator credentials")
    token = create_access_token(row["customer_id"])
    return {"access_token": token, "token_type": "bearer", "expires_in": 1800,
            "customer_id": row["customer_id"], "role": "operator"}


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




def get_owned_account(customer_id: str, broker: str, account_id: str) -> None:
    owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(customer_id)}
    if (broker.lower(), account_id) not in owned:
        raise HTTPException(status_code=404, detail="Broker account not found")




@app.post("/api/v1/customer/accounts/angel-one/{account_id}/login")
async def angel_login(account_id: str, body: AngelLoginRequest,
                      customer_id: str = Depends(require_customer)) -> dict:
    get_owned_account(customer_id, "angelone", account_id)
    try:
        credentials = get_vault().get(customer_id, "angelone", account_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Save Angel API key and PIN first") from exc
    api_key, pin = credentials.get("api_key"), credentials.get("pin")
    network = {
        "client_local_ip": os.getenv("AIR_CLIENT_LOCAL_IP", ""),
        "client_public_ip": os.getenv("AIR_CLIENT_PUBLIC_IP", ""),
        "mac_address": os.getenv("AIR_CLIENT_MAC_ADDRESS", ""),
    }
    if not api_key or not pin or not all(network.values()):
        raise HTTPException(status_code=503, detail="Angel API credentials or required server network identity headers are not configured")
    client = AngelSmartAPI(api_key, account_id, **network)
    try:
        session = await client.login(pin, body.totp)
        profile = await client.profile()
        if str(profile.get("clientcode", "")).upper() != account_id.upper():
            raise HTTPException(status_code=409, detail="Angel profile client code does not match registered account")
        credentials["jwt_token"] = session["jwtToken"]
        credentials["refresh_token"] = session.get("refreshToken", "")
        credentials["feed_token"] = session.get("feedToken", "")
        get_vault().put(customer_id, "angelone", account_id, credentials)
        return {"broker": "angelone", "account_id": account_id, "verified": True,
                "feed_token_saved": bool(session.get("feedToken")),
                "note": "Angel session verified and tokens stored encrypted. Session normally expires at midnight; TOTP was not stored. Live order permission remains disabled."}
    except AngelAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Angel SmartAPI login or profile verification failed") from exc
    finally:
        await client.close()


@app.get("/api/v1/customer/accounts/fyers/{account_id}/login-url")
async def fyers_login(account_id: str, customer_id: str = Depends(require_customer)) -> dict:
    get_owned_account(customer_id, "fyers", account_id)
    try:
        credentials = get_vault().get(customer_id, "fyers", account_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Save FYERS app_id, app_secret and redirect_uri first") from exc
    app_id, redirect_uri = credentials.get("app_id"), credentials.get("redirect_uri")
    if not app_id or not credentials.get("app_secret") or not redirect_uri:
        raise HTTPException(status_code=422, detail="FYERS app credentials are incomplete")
    state = secrets.token_urlsafe(24)
    _fyers_oauth_states[(customer_id, account_id)] = state
    return {"login_url": fyers_login_url(app_id, redirect_uri, state), "state": state,
            "note": "Complete FYERS login and submit auth_code with the returned state. State is one-time and process-local."}


@app.post("/api/v1/customer/accounts/fyers/{account_id}/exchange")
async def fyers_exchange(account_id: str, body: FyersTokenExchangeRequest,
                         customer_id: str = Depends(require_customer)) -> dict:
    get_owned_account(customer_id, "fyers", account_id)
    expected_state = _fyers_oauth_states.pop((customer_id, account_id), None)
    if not expected_state or not secrets.compare_digest(expected_state, body.state):
        raise HTTPException(status_code=400, detail="Invalid or expired FYERS OAuth state")
    try:
        credentials = get_vault().get(customer_id, "fyers", account_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="FYERS app credentials are not saved") from exc
    app_id, app_secret = credentials.get("app_id"), credentials.get("app_secret")
    if not app_id or not app_secret:
        raise HTTPException(status_code=422, detail="FYERS app_id and app_secret are required")
    client = FyersClient(app_id)
    try:
        session = await client.exchange_auth_code(body.auth_code, app_secret)
        profile = await client.profile()
        credentials["access_token"] = session["access_token"]
        get_vault().put(customer_id, "fyers", account_id, credentials)
        return {"broker": "fyers", "account_id": account_id, "verified": True,
                "profile": profile.get("data", profile), "access_token_saved": True,
                "note": "FYERS profile verified and token stored encrypted. Standard access tokens expire daily at 6:30 AM. Trading-app static IP eligibility is separate; AIR order permission remains disabled."}
    except FyersAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="FYERS authorization-code exchange or profile verification failed") from exc
    finally:
        await client.close()


@app.get("/api/v1/customer/accounts/zerodha/{account_id}/login-url")
async def zerodha_login_url(account_id: str, customer_id: str = Depends(require_customer)) -> dict:
    get_owned_account(customer_id, "zerodha", account_id)
    try:
        credentials = get_vault().get(customer_id, "zerodha", account_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Save Zerodha api_key and api_secret first") from exc
    api_key = credentials.get("api_key")
    if not api_key or not credentials.get("api_secret"):
        raise HTTPException(status_code=422, detail="Zerodha api_key and api_secret are required")
    return {"login_url": kite_login_url(api_key), "redirect_uri_must_be_registered": True,
            "note": "Complete login in the broker page and submit the short-lived request_token to the exchange endpoint immediately."}


@app.post("/api/v1/customer/accounts/zerodha/{account_id}/exchange")
async def zerodha_exchange_token(account_id: str, body: ZerodhaTokenExchangeRequest,
                                 customer_id: str = Depends(require_customer)) -> dict:
    get_owned_account(customer_id, "zerodha", account_id)
    try:
        credentials = get_vault().get(customer_id, "zerodha", account_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Save Zerodha api_key and api_secret first") from exc
    api_key, api_secret = credentials.get("api_key"), credentials.get("api_secret")
    if not api_key or not api_secret:
        raise HTTPException(status_code=422, detail="Zerodha api_key and api_secret are required")
    client = KiteConnectClient(api_key)
    try:
        session = await client.exchange_request_token(body.request_token, api_secret)
        profile = await client.profile()
        broker_user_id = str(profile.get("user_id", ""))
        if broker_user_id and broker_user_id != account_id:
            raise HTTPException(status_code=409, detail="Authenticated Zerodha user does not match registered account ID")
        credentials["access_token"] = session["access_token"]
        get_vault().put(customer_id, "zerodha", account_id, credentials)
        return {"broker": "zerodha", "account_id": account_id, "verified": True,
                "user_id": broker_user_id, "access_token_saved": True,
                "note": "Token is stored encrypted. Kite access tokens expire at the next daily session boundary; repeat the login flow when expired. Order permission remains disabled."}
    except KiteAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Zerodha token exchange or profile verification failed") from exc
    finally:
        await client.close()


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



@app.get("/api/v1/customer/accounts/upstox/{account_id}/login-url")
async def upstox_login(account_id: str, customer_id: str = Depends(require_customer)) -> dict:
    get_owned_account(customer_id, "upstox", account_id)
    try:
        credentials = get_vault().get(customer_id, "upstox", account_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Save Upstox client_id, client_secret and redirect_uri first") from exc
    client_id, redirect_uri = credentials.get("client_id"), credentials.get("redirect_uri")
    if not client_id or not credentials.get("client_secret") or not redirect_uri:
        raise HTTPException(status_code=422, detail="Upstox OAuth app credentials are incomplete")
    state = secrets.token_urlsafe(24)
    _upstox_oauth_states[(customer_id, account_id)] = state
    return {"login_url": upstox_login_url(client_id, redirect_uri, state), "state": state,
            "note": "Complete login at Upstox and submit the returned single-use code and state. State expires when replaced or the server restarts."}


@app.post("/api/v1/customer/accounts/upstox/{account_id}/exchange")
async def upstox_exchange(account_id: str, body: UpstoxTokenExchangeRequest,
                          customer_id: str = Depends(require_customer)) -> dict:
    get_owned_account(customer_id, "upstox", account_id)
    expected_state = _upstox_oauth_states.pop((customer_id, account_id), None)
    if not expected_state or not secrets.compare_digest(expected_state, body.state):
        raise HTTPException(status_code=400, detail="Invalid or expired Upstox OAuth state")
    try:
        credentials = get_vault().get(customer_id, "upstox", account_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Upstox app credentials are not saved") from exc
    client_id, client_secret, redirect_uri = (
        credentials.get("client_id"), credentials.get("client_secret"), credentials.get("redirect_uri")
    )
    if not all((client_id, client_secret, redirect_uri)):
        raise HTTPException(status_code=422, detail="Upstox OAuth app credentials are incomplete")
    client = UpstoxClient()
    try:
        session = await client.exchange_code(body.code, client_id, client_secret, redirect_uri)
        profile_data = await client.profile()
        profile = profile_data.get("user_id") or profile_data.get("user_name")
        credentials["access_token"] = session["access_token"]
        get_vault().put(customer_id, "upstox", account_id, credentials)
        return {"broker": "upstox", "account_id": account_id, "verified": True,
                "broker_user": profile, "access_token_saved": True,
                "note": "Authorization code exchanged and token stored encrypted. Standard access tokens expire at 3:30 AM the following day; order permission remains disabled."}
    except UpstoxAPIError as exc:
        raise HTTPException(status_code=502 if exc.status_code >= 500 else 401,
                            detail="Upstox authorization-code exchange failed") from exc
    finally:
        await client.close()


@app.post("/api/v1/customer/accounts/dhan/{account_id}/verify")
async def verify_dhan_account(account_id: str, customer_id: str = Depends(require_customer)) -> dict:
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



@app.get("/api/v1/market-data/instruments/search")
async def search_market_instruments(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=500),
    segment: str | None = Query(default=None, max_length=30),
    customer_id: str = Depends(require_air_operator),
) -> dict:
    resolved = market_data_router.resolve("historical")
    if not resolved:
        raise HTTPException(status_code=409, detail="No connected Main Account market-data adapter")
    provider, account_id, adapter = resolved[0]
    if provider != "dhan":
        raise HTTPException(status_code=409, detail="Instrument search is not yet implemented for this Main Account provider")
    try:
        rows = await adapter.search_instruments(q, limit=limit, exchange_segment=segment)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Instrument master lookup failed: {type(exc).__name__}") from exc
    return {"provider": provider, "account_id": account_id, "count": len(rows), "instruments": rows}


@app.post("/api/v1/market-data/subscribe")
async def subscribe_market_data(body: MarketSubscriptionRequest,
                                 customer_id: str = Depends(require_air_operator)) -> dict:
    resolved = market_data_router.resolve("live")
    if not resolved:
        raise HTTPException(status_code=409, detail="No connected Main Account market-data adapter")
    provider, account_id, adapter = resolved[0]
    if provider != "dhan":
        raise HTTPException(status_code=409, detail="Instrument subscription route is not yet implemented for this Main Account provider")
    try:
        instruments = [
            MarketInstrument(
                exchange=item.exchange, symbol=item.symbol, token=item.token,
                segment=item.segment,
            )
            for item in body.instruments
        ]
        await adapter.subscribe(instruments)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"provider": provider, "account_id": account_id,
            "subscribed_count": len(instruments), "status": "subscription_sent"}


@app.get("/api/v1/market-data/status")
async def market_data_status(customer_id: str = Depends(require_air_operator)) -> dict:
    resolved = market_data_router.resolve("live")
    provider_health = resolved[0][2].health() if resolved and hasattr(resolved[0][2], "health") else None
    return {
        "routing": market_data_router.status(),
        "provider_health": provider_health,
        "stream": market_data_hub.status(),
        "note": "Feed state reflects the selected Main Account adapter. Instrument subscriptions and fresh ticks must still be checked.",
    }


@app.put("/api/v1/market-data/main-account")
async def select_main_account(selection: MainAccountSelection,
                              customer_id: str = Depends(require_air_operator)) -> dict:
    try:
        owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(customer_id)}
        if (selection.provider.lower(), selection.account_id) not in owned:
            raise HTTPException(status_code=404, detail="Customer does not own this Main Account")
        credentials = get_vault().get(customer_id, selection.provider, selection.account_id)
        provider = selection.provider.strip().lower()
        if not market_data_router.is_registered(provider, selection.account_id):
            if provider == "dhan":
                client_id = credentials.get("client_id", selection.account_id)
                access_token = credentials.get("access_token")
                if not access_token:
                    raise HTTPException(status_code=422, detail="Dhan access_token is required")
                market_data_router.register(
                    selection.account_id,
                    DhanMarketDataAdapter(client_id, access_token, market_data_hub),
                )
            else:
                raise HTTPException(
                    status_code=409,
                    detail=f"{provider} credentials are saved, but its live Main Account adapter is not yet connected",
                )
        await market_data_router.set_main_account(provider, selection.account_id)
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
