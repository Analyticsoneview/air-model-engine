import os
import asyncio
from decimal import Decimal
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
from app.market_data.dhan_adapter import DhanMarketDataAdapter
from app.market_data.broker_streams import (ZerodhaWebSocketAdapter, UpstoxWebSocketAdapter, FyersWebSocketAdapter, AngelOneWebSocketAdapter)
from app.market_data.nse_adapter import NSEBhavcopyMarketDataAdapter
from app.market_data.hub import MarketDataHub
from app.market_data.vendor_adapter import GenericVendorMarketDataAdapter
from app.market_data.contracts import MarketInstrument
from app.market_data.runtime import (market_data_router, market_data_hub, market_data_sources, market_data_instruments, market_data_service, execution_policy)
from app.market_data.service import set_default_market_data_service
from app.market_data.master_refresh import BrokerMasterRefresher
from app.market_data.customer_runtime import (configure_customer_market_data_runtime, invalidate_customer_market_data_service, close_customer_market_data_runtimes)
from app.air_qoc_dhan import router as air_qoc_dhan_router
from app.model_engine_api import router as model_engine_router
from app.air_qoc_scheduler import start_qoc_scheduler, stop_qoc_scheduler, capture_dhan_eod_snapshots, capture_selected_provider_option_chains
from app.air_telegram_scheduler import start_telegram_scheduler, stop_telegram_scheduler
from app.telegram_notifications import send_telegram_message
from app import telegram_destinations
from app.nse_bhavcopy import (nse_data_status, nse_data_rows, start_nse_data_jobs, stop_nse_data_jobs, trigger_nse_bootstrap)
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
_market_health_task: asyncio.Task | None = None
_master_refresh_task: asyncio.Task | None = None
set_default_market_data_service(market_data_service)
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


def require_air_admin(x_air_admin_key: str | None = Header(default=None)) -> None:
    key_file = os.getenv("AIR_ADMIN_API_KEY_FILE")
    configured = open(key_file, encoding="utf-8").read().strip() if key_file else os.getenv("AIR_ADMIN_API_KEY", "")
    if len(configured) < 32 or not x_air_admin_key or not secrets.compare_digest(x_air_admin_key, configured):
        raise HTTPException(status_code=403, detail="AIR administrator approval is required")


def _market_adapter_for(operator_id: str, provider: str, account_id: str, hub=None):
    """Build a verified broker adapter from operator-owned encrypted credentials."""
    credentials = get_vault().get(operator_id, provider, account_id)
    poll_seconds = max(2.0, float(os.getenv("AIR_MARKET_DATA_POLL_SECONDS", "3")))
    hub = hub or market_data_hub
    if provider == "custom_vendor":
        required = ("base_url", "websocket_url", "api_key")
        if any(not credentials.get(key) for key in required):
            raise ValueError("Custom vendor requires base_url, websocket_url and api_key")
        return GenericVendorMarketDataAdapter(account_id, credentials, hub)
    if provider == "dhan":
        access_token = credentials.get("access_token")
        if not access_token:
            raise ValueError("Dhan access token is missing")
        return DhanMarketDataAdapter(credentials.get("client_id", account_id), access_token, hub)
    if provider == "zerodha":
        if not credentials.get("api_key") or not credentials.get("access_token"):
            raise ValueError("Zerodha api_key and access_token are required")
        return ZerodhaWebSocketAdapter(account_id, credentials["api_key"], credentials["access_token"], hub, poll_seconds)
    if provider == "upstox":
        if not credentials.get("access_token"):
            raise ValueError("Upstox access_token is required")
        return UpstoxWebSocketAdapter(account_id, credentials["access_token"], hub, poll_seconds)
    if provider == "fyers":
        if not credentials.get("app_id") or not credentials.get("access_token"):
            raise ValueError("FYERS app_id and access_token are required")
        return FyersWebSocketAdapter(account_id, credentials["app_id"], credentials["access_token"], hub, poll_seconds)
    if provider == "angelone":
        required = ("api_key", "jwt_token", "feed_token")
        if any(not credentials.get(key) for key in required):
            raise ValueError("Angel api_key, jwt_token and feed_token are required")
        network = {
            "client_local_ip": os.getenv("AIR_CLIENT_LOCAL_IP", ""),
            "client_public_ip": os.getenv("AIR_CLIENT_PUBLIC_IP", ""),
            "mac_address": os.getenv("AIR_CLIENT_MAC_ADDRESS", ""),
        }
        if not all(network.values()):
            raise ValueError("Angel SmartAPI server network identity headers are not configured")
        return AngelOneWebSocketAdapter(account_id, credentials, hub, network, poll_seconds)
    raise ValueError("No market-data adapter is registered for this provider")


@app.on_event("startup")
async def start_air_qoc_jobs() -> None:
    global _market_health_task, _master_refresh_task
    configure_customer_market_data_runtime(
        account_directory, market_data_instruments,
        lambda customer_id, provider, account_id, hub: _market_adapter_for(
            customer_id, provider, account_id, hub=hub
        ),
    )
    start_nse_data_jobs()
    await _restore_market_data_source_connections()
    _market_health_task = asyncio.create_task(_market_data_health_loop(), name="air-market-data-health")
    _master_refresh_task = asyncio.create_task(_broker_master_refresh_loop(), name="air-broker-master-refresh")
    # Safe by default: the scheduler captures data only for selected, authenticated operator/PAID accounts.
    start_qoc_scheduler(force=_has_enabled_customer_broker_sources())
    start_telegram_scheduler()


async def _market_data_health_loop() -> None:
    while True:
        try:
            await market_data_service.health()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Health monitoring must never take down the API process.
            pass
        await asyncio.sleep(max(3.0, float(os.getenv("AIR_MARKET_HEALTH_INTERVAL_SECONDS", "5"))))


def _has_enabled_customer_broker_sources() -> bool:
    operator_ids = {
        value.strip() for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    }
    for account in account_directory.list_all():
        access = account_directory.get_market_data_access(account.customer_id)
        eligible = account.customer_id in operator_ids or (
            access.get("tier") == "PAID" and access.get("broker_data_enabled") is True
        )
        selection = account_directory.get_market_data_selection(account.customer_id)
        if (eligible and selection
                and selection.get("provider") == account.broker
                and selection.get("account_id") == account.account_id):
            return True
    return False


def _broker_master_headers(operator_id: str, provider: str, account_id: str) -> dict[str, str] | None:
    if provider != "zerodha":
        return None
    credentials = get_vault().get(operator_id, provider, account_id)
    api_key, access_token = credentials.get("api_key"), credentials.get("access_token")
    if not api_key or not access_token:
        raise ValueError("Zerodha API key/access token required to download the authenticated instrument master")
    return {"Authorization": f"token {api_key}:{access_token}", "X-Kite-Version": "3"}


async def _broker_master_refresh_loop() -> None:
    """Refresh configured broker masters once per NSE trading date at 07:00 IST."""
    from zoneinfo import ZoneInfo
    from datetime import datetime
    ist = ZoneInfo("Asia/Kolkata")
    last_run = None
    while True:
        now = datetime.now(ist)
        if now.weekday() < 5 and now.hour >= 7 and last_run != now.date():
            refresher = BrokerMasterRefresher(market_data_instruments)
            try:
                # Refresh every assigned customer's broker-specific master, not only
                # the operator's account. Tokens and master snapshots remain account-scoped.
                for account in account_directory.list_all():
                    if account.broker not in {"dhan", "zerodha", "upstox", "fyers", "angelone"}:
                        continue
                    try:
                        headers = _broker_master_headers(
                            account.customer_id, account.broker, account.account_id
                        )
                        await refresher.refresh(account.broker, account.account_id, headers=headers)
                    except Exception:
                        # Preserve the previous known-good master and report failure in status.
                        continue
            finally:
                await refresher.close()
            last_run = now.date()
        await asyncio.sleep(60)


async def _restore_market_data_source_connections() -> None:
    """Restore enabled broker feeds after process restart; NSE EOD is disk-backed."""
    selections = market_data_sources.selections()
    operator_ids = [
        value.strip() for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    ]
    for channel in ("historical", "live"):
        selection = selections.get(channel)
        if not selection or not selection.get("enabled"):
            continue
        provider = selection.get("provider")
        account_id = selection.get("account_id")
        if provider == "nse_bhavcopy" and channel == "historical":
            try:
                if not market_data_router.is_registered(provider, "official"):
                    market_data_router.register("official", NSEBhavcopyMarketDataAdapter())
                await market_data_router.set_source(channel, provider, "official")
            except Exception:
                continue
            continue
        if not provider or not account_id:
            continue
        for operator_id in operator_ids:
            owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(operator_id)}
            if (provider, account_id) not in owned:
                continue
            try:
                if not market_data_router.is_registered(provider, account_id):
                    adapter = _market_adapter_for(operator_id, provider, account_id)
                    market_data_router.register(account_id, adapter)
                await market_data_router.set_source(channel, provider, account_id)
                break
            except Exception:
                # Keep API startup available if a provider token expired or a
                # vendor endpoint is temporarily unreachable. Admin status shows
                # the persisted selection separately from runtime connection.
                continue

    failover = market_data_sources.failover()
    for channel in ("historical", "live"):
        config = failover.get(channel) or {}
        candidates = []
        for item in config.get("candidates", []):
            provider, account_id = item.get("provider"), item.get("account_id")
            if provider == "nse_bhavcopy" and channel == "historical":
                account_id = "official"
                if not market_data_router.is_registered(provider, account_id):
                    market_data_router.register(account_id, NSEBhavcopyMarketDataAdapter())
            else:
                if (provider, account_id) not in {
                    (a.broker, a.account_id)
                    for operator_id in operator_ids
                    for a in account_directory.list_for_customer(operator_id)
                }:
                    continue
                owner = next((oid for oid in operator_ids if (provider, account_id) in {
                    (a.broker, a.account_id) for a in account_directory.list_for_customer(oid)
                }), None)
                if owner and not market_data_router.is_registered(provider, account_id):
                    try:
                        market_data_router.register(account_id, _market_adapter_for(owner, provider, account_id))
                    except Exception:
                        continue
            candidates.append((provider, account_id))
        try:
            await market_data_router.configure_failover(
                channel, candidates, bool(config.get("enabled")) and bool(candidates)
            )
        except Exception:
            continue


@app.on_event("shutdown")
async def stop_air_qoc_jobs() -> None:
    global _market_health_task, _master_refresh_task
    await close_customer_market_data_runtimes()
    if _master_refresh_task is not None:
        _master_refresh_task.cancel()
        try:
            await _master_refresh_task
        except asyncio.CancelledError:
            pass
        _master_refresh_task = None
    if _market_health_task is not None:
        _market_health_task.cancel()
        try:
            await _market_health_task
        except asyncio.CancelledError:
            pass
        _market_health_task = None
    for channel in ("historical", "live"):
        try:
            await market_data_router.clear_source(channel)
        except Exception:
            pass
    stop_telegram_scheduler()
    stop_qoc_scheduler()
    stop_nse_data_jobs()


@app.post("/api/v1/air-qoc/run-eod-capture", dependencies=[Depends(require_air_admin)])
async def run_air_qoc_eod_capture() -> dict:
    try:
        return await capture_selected_provider_option_chains(force=True)
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


class TradingAccountCreate(BaseModel):
    broker: str = Field(min_length=2, max_length=40)
    account_id: str = Field(min_length=2, max_length=100)


class AdminTradingAccountAssignment(TradingAccountCreate):
    customer_id: str = Field(min_length=3, max_length=100)


class ExecutionPolicyUpdate(BaseModel):
    master_auto_enabled: bool = False
    strategies: dict[str, bool] = Field(default_factory=dict)


class OrderPermissionUpdate(BaseModel):
    enabled: bool


class CustomerMarketDataAccessUpdate(BaseModel):
    tier: str = Field(pattern="^(STANDARD|PAID)$")
    broker_data_enabled: bool = False


class BrokerCredentialInput(BaseModel):
    credentials: dict[str, str]


class MainAccountSelection(BaseModel):
    provider: str
    account_id: str


class MarketDataFailoverSelection(BaseModel):
    enabled: bool = False
    candidates: list[dict[str, str]] = Field(default_factory=list, max_length=5)


class MarketDataSourceSelection(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    account_id: str | None = Field(default=None, max_length=100)
    enabled: bool = True


class TelegramDestinationInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    chat_id: str = Field(min_length=1, max_length=24)
    destination_type: str = Field(pattern="^(PRIVATE|GROUP)$")
    strategies: list[str] = Field(min_length=1, max_length=3)
    enabled: bool = True



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


class MarketInstrumentMapping(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    account_id: str = Field(min_length=2, max_length=100)
    exchange: str = Field(min_length=2, max_length=20)
    symbol: str = Field(min_length=1, max_length=100)
    token: str = Field(min_length=1, max_length=100)
    segment: str = Field(min_length=2, max_length=30)
    expiry: str | None = None
    strike: str | None = None
    option_type: str | None = None
    lot_size: int | None = Field(default=None, ge=1)
    instrument_type: str | None = None
    tick_size: str | None = None
    underlying_symbol: str | None = None


class MarketInstrumentMappingItem(BaseModel):
    exchange: str = Field(min_length=2, max_length=20)
    symbol: str = Field(min_length=1, max_length=100)
    token: str = Field(min_length=1, max_length=100)
    segment: str = Field(min_length=2, max_length=30)
    expiry: str | None = None
    strike: str | None = None
    option_type: str | None = None
    lot_size: int | None = Field(default=None, ge=1)
    instrument_type: str | None = None
    tick_size: str | None = None


class MarketInstrumentMappingBatch(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    account_id: str = Field(min_length=2, max_length=100)
    instruments: list[MarketInstrumentMappingItem] = Field(min_length=1, max_length=5000)


class MarketHistoricalRequest(BaseModel):
    exchange: str = Field(min_length=2, max_length=20)
    symbol: str = Field(min_length=1, max_length=100)
    token: str = Field(min_length=1, max_length=100)
    segment: str = Field(min_length=2, max_length=30)
    start: str = Field(min_length=10, max_length=40)
    end: str = Field(min_length=10, max_length=40)
    interval: str = Field(min_length=1, max_length=12)


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

@app.get("/api/v1/nse-data/status")
async def nse_bhavcopy_status(customer_id: str = Depends(require_customer)) -> dict:
    return nse_data_status()


@app.get("/api/v1/nse-data/rows")
async def nse_bhavcopy_rows(
    market: str = Query(pattern="^(CM|FO)$"),
    symbol: str | None = Query(default=None, max_length=40),
    start_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    instrument_type: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
    customer_id: str = Depends(require_customer),
) -> dict:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be before or equal to end_date")
    rows = nse_data_rows(
        market, symbol=symbol, start_date=start_date, end_date=end_date,
        instrument_type=instrument_type, limit=limit,
    )
    return {"market": market, "count": len(rows), "rows": rows,
            "source": "NSE official UDiFF bhavcopy", "data_type": "EOD"}


@app.post("/api/v1/nse-data/bootstrap")
async def trigger_nse_bhavcopy_bootstrap(
    customer_id: str = Depends(require_air_operator),
) -> dict:
    return trigger_nse_bootstrap()



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


async def _verify_customer_market_data_connection(
    customer_id: str, provider: str, account_id: str
) -> None:
    """Require a real provider handshake before a broker becomes the strategy source."""
    adapter = _market_adapter_for(customer_id, provider, account_id, hub=MarketDataHub())
    try:
        await adapter.authenticate(account_id)
    finally:
        try:
            await adapter.close()
        except Exception:
            pass


@app.get("/api/v1/customer/market-data/access")
async def customer_market_data_access(customer_id: str = Depends(require_customer)) -> dict:
    access = account_directory.get_market_data_access(customer_id)
    selection = account_directory.get_market_data_selection(customer_id)
    operator_ids = {
        value.strip() for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    }
    operator_identity = customer_id if customer_id in operator_ids else (
        access_store.mobile_for_request_id(customer_id) or ""
    )
    operator = operator_identity in operator_ids
    return {
        "access": access,
        "selection": selection,
        "effective_source": "BROKER" if (operator or (
            access["tier"] == "PAID" and access["broker_data_enabled"]
        )) and selection else "NSE",
        "note": "STANDARD customers use NSE EOD data. Broker data requires a verified assigned broker account and an enabled PAID entitlement.",
    }


@app.put("/api/v1/customer/market-data/selection")
async def customer_select_market_data_account(
    selection: MainAccountSelection,
    customer_id: str = Depends(require_customer),
) -> dict:
    try:
        access = account_directory.get_market_data_access(customer_id)
        if access["tier"] != "PAID" or not access["broker_data_enabled"]:
            raise PermissionError("Broker market data requires an enabled paid entitlement")
        get_vault().get(customer_id, selection.provider.lower(), selection.account_id)
        await _verify_customer_market_data_connection(
            customer_id, selection.provider.lower(), selection.account_id
        )
        row = account_directory.set_market_data_selection(
            customer_id, selection.provider, selection.account_id
        )
        await invalidate_customer_market_data_service(customer_id)
        start_qoc_scheduler(force=True)
        return {"selection": row, "effective_source": "BROKER"}
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Broker credentials have not been saved") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Broker market-data authentication failed") from exc


@app.delete("/api/v1/customer/market-data/selection")
async def customer_clear_market_data_selection(
    customer_id: str = Depends(require_customer),
) -> dict:
    account_directory.clear_market_data_selection(customer_id)
    await invalidate_customer_market_data_service(customer_id)
    return {"selection": None, "effective_source": "NSE"}


@app.put("/api/v1/operator/customers/{target_customer_id}/market-data-access")
async def operator_set_customer_market_data_access(
    target_customer_id: str,
    body: CustomerMarketDataAccessUpdate,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    try:
        access = account_directory.set_market_data_access(
            target_customer_id, body.tier, body.broker_data_enabled
        )
        await invalidate_customer_market_data_service(target_customer_id)
        return {"access": access, "updated": True}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/v1/operator/customers/{target_customer_id}/market-data-selection")
async def operator_set_customer_market_data_selection(
    target_customer_id: str,
    selection: MainAccountSelection,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(target_customer_id)}
    if (selection.provider.lower(), selection.account_id) not in owned:
        raise HTTPException(status_code=404, detail="Broker account is not assigned to this customer")
    try:
        get_vault().get(target_customer_id, selection.provider.lower(), selection.account_id)
        await _verify_customer_market_data_connection(
            target_customer_id, selection.provider.lower(), selection.account_id
        )
        account_directory.set_market_data_access(target_customer_id, "PAID", True)
        row = account_directory.set_market_data_selection(
            target_customer_id, selection.provider, selection.account_id
        )
        await invalidate_customer_market_data_service(target_customer_id)
        start_qoc_scheduler(force=True)
        return {"selection": row, "access": account_directory.get_market_data_access(target_customer_id)}
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Broker credentials have not been saved") from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Broker market-data authentication failed") from exc


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
                               customer_id: str = Depends(require_air_operator)) -> dict:
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
                                           customer_id: str = Depends(require_air_operator)) -> dict:
    try:
        owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(customer_id)}
        if (broker.lower(), account_id) not in owned:
            raise PermissionError("Customer does not own this broker account")
        get_vault().put(customer_id, broker, account_id, body.credentials)
        await invalidate_customer_market_data_service(customer_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"broker": broker.lower(), "account_id": account_id, "credentials_saved": True}


@app.delete("/api/v1/customer/accounts/{broker}/{account_id}")
async def remove_customer_account(broker: str, account_id: str,
                                  customer_id: str = Depends(require_air_operator)) -> dict:
    vault = get_vault()
    try:
        vault.delete(customer_id, broker, account_id)
        account_directory.remove(customer_id, broker, account_id)
        await invalidate_customer_market_data_service(customer_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "removed", "broker": broker.lower(), "account_id": account_id}



# Broker account ownership and credential mutations are operator-only.
# Customers can only read the accounts assigned to their own stable identity.
@app.get("/api/v1/operator/broker-accounts")
async def operator_list_broker_accounts(
    customer_id: str = Depends(require_air_operator),
) -> dict:
    accounts = account_directory.list_all()
    try:
        credentials = get_vault().list_for_all_customers()
        credential_keys = {(r["customer_id"], r["broker"], r["account_id"]) for r in credentials}
        vault_configured = True
    except HTTPException:
        credential_keys = set()
        vault_configured = False
    return {"accounts": [
        {
            "customer_id": a.customer_id, "broker": a.broker, "account_id": a.account_id,
            "order_enabled": a.enabled_for_orders,
            "credentials_saved": (a.customer_id, a.broker, a.account_id) in credential_keys,
            "market_data_access": account_directory.get_market_data_access(a.customer_id),
            "market_data_selection": account_directory.get_market_data_selection(a.customer_id),
        }
        for a in accounts
    ], "credential_vault_configured": vault_configured}


@app.post("/api/v1/operator/broker-accounts", status_code=201)
async def operator_assign_broker_account(
    body: AdminTradingAccountAssignment,
    customer_id: str = Depends(require_air_operator),
) -> dict:
    if not is_supported_broker(body.broker):
        raise HTTPException(status_code=422, detail="Unsupported broker. Use the AIR broker catalog.")
    try:
        account_directory.add(CustomerTradingAccount(
            body.customer_id.strip(), body.broker, body.account_id, False
        ))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"customer_id": body.customer_id.strip(), "broker": body.broker.lower(),
            "account_id": body.account_id.strip(), "order_enabled": False, "status": "assigned"}


@app.put("/api/v1/operator/broker-accounts/{customer_id}/{broker}/{account_id}/credentials")
async def operator_save_broker_credentials(
    customer_id: str, broker: str, account_id: str, body: BrokerCredentialInput,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(customer_id)}
    if (broker.lower(), account_id) not in owned:
        raise HTTPException(status_code=404, detail="Assigned broker account not found")
    try:
        get_vault().put(customer_id, broker, account_id, body.credentials)
        await invalidate_customer_market_data_service(customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"customer_id": customer_id, "broker": broker.lower(),
            "account_id": account_id, "credentials_saved": True}


@app.delete("/api/v1/operator/broker-accounts/{customer_id}/{broker}/{account_id}")
async def operator_remove_broker_account(
    customer_id: str, broker: str, account_id: str,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    try:
        get_vault().delete(customer_id, broker, account_id)
        account_directory.remove(customer_id, broker, account_id)
        await invalidate_customer_market_data_service(customer_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Assigned broker account not found") from exc
    return {"status": "removed", "customer_id": customer_id,
            "broker": broker.lower(), "account_id": account_id}



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
        await invalidate_customer_market_data_service(customer_id)
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
        await invalidate_customer_market_data_service(customer_id)
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
        await invalidate_customer_market_data_service(customer_id)
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
        await invalidate_customer_market_data_service(customer_id)
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
    active = market_data_router.status().get("live_source")
    if active != {"provider": "dhan", "account_id": account_id}:
        raise HTTPException(status_code=409, detail="Dhan is not the selected live data source")
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
    active = market_data_router.status().get("historical_source")
    if active != {"provider": "dhan", "account_id": account_id}:
        raise HTTPException(status_code=409, detail="Dhan is not the selected historical data source")
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
        resolved = market_data_router.resolve("live")
    if not resolved:
        raise HTTPException(status_code=409, detail="No connected market-data adapter")
    provider, account_id, adapter = resolved[0]
    mapped = market_data_instruments.search(provider, account_id, q, limit)
    if mapped:
        instruments = [
            MarketInstrument(
                exchange=row["exchange"], symbol=row["symbol"], token=row["token"],
                segment=row["segment"], expiry=row.get("expiry"),
                strike=Decimal(row["strike"]) if row.get("strike") else None,
                option_type=row.get("option_type"),
                lot_size=row.get("lot_size"), instrument_type=row.get("instrument_type"),
                tick_size=Decimal(str(row["tick_size"])) if row.get("tick_size") else None,
            )
            for row in mapped
            if not segment or row["segment"].upper() == segment.upper()
        ]
        return {"provider": provider, "account_id": account_id,
                "count": len(instruments), "instruments": instruments,
                "source": "admin_instrument_directory"}
    try:
        rows = await market_data_service.search_instruments(q, limit=limit, exchange_segment=segment)
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
    try:
        instruments = [
            MarketInstrument(
                exchange=item.exchange, symbol=item.symbol, token=item.token,
                segment=item.segment,
            )
            for item in body.instruments
        ]
        result = await market_data_service.subscribe(instruments)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"provider": result["provider"], "account_id": result["account_id"],
            "subscribed_count": len(instruments), "status": "subscription_sent"}




@app.get("/api/v1/operator/market-data/instruments")
async def operator_list_market_instruments(
    provider: str | None = None,
    account_id: str | None = None,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    rows = market_data_instruments.list_all(provider, account_id)
    return {"instruments": rows, "count": len(rows)}


@app.post("/api/v1/operator/market-data/instruments", status_code=201)
async def operator_save_market_instrument(
    body: MarketInstrumentMapping,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(operator_id)}
    if (body.provider.lower(), body.account_id) not in owned:
        raise HTTPException(status_code=404, detail="Provider account is not assigned to this operator")
    try:
        row = market_data_instruments.upsert(
            body.provider, body.account_id, exchange=body.exchange, symbol=body.symbol,
            token=body.token, segment=body.segment, expiry=body.expiry,
            strike=body.strike, option_type=body.option_type, lot_size=body.lot_size,
            instrument_type=body.instrument_type, tick_size=body.tick_size,
            underlying_symbol=body.underlying_symbol,
        )
        return {"instrument": row, "status": "saved"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/operator/market-data/instruments/bulk", status_code=201)
async def operator_bulk_save_market_instruments(
    body: MarketInstrumentMappingBatch,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(operator_id)}
    if (body.provider.lower(), body.account_id) not in owned:
        raise HTTPException(status_code=404, detail="Provider account is not assigned to this operator")
    saved = 0
    try:
        for item in body.instruments:
            market_data_instruments.upsert(
                body.provider, body.account_id, exchange=item.exchange,
                symbol=item.symbol, token=item.token, segment=item.segment,
                expiry=item.expiry, strike=item.strike, option_type=item.option_type,
                lot_size=item.lot_size, instrument_type=item.instrument_type,
                tick_size=item.tick_size, underlying_symbol=item.underlying_symbol,
            )
            saved += 1
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"provider": body.provider, "account_id": body.account_id,
            "saved_count": saved, "status": "saved"}


@app.delete("/api/v1/operator/market-data/instruments/{provider}/{account_id}/{token}")
async def operator_delete_market_instrument(
    provider: str, account_id: str, token: str,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(operator_id)}
    if (provider.lower(), account_id) not in owned:
        raise HTTPException(status_code=404, detail="Provider account is not assigned to this operator")
    if not market_data_instruments.delete(provider, account_id, token):
        raise HTTPException(status_code=404, detail="Instrument mapping not found")
    return {"status": "removed", "provider": provider, "account_id": account_id, "token": token}


@app.post("/api/v1/market-data/historical")
async def market_data_historical(
    body: MarketHistoricalRequest,
    customer_id: str = Depends(require_air_operator),
) -> dict:
    resolved = market_data_router.resolve("historical")
    if not resolved:
        raise HTTPException(status_code=409, detail="No connected historical market-data source")
    provider, account_id, adapter = resolved[0]
    from datetime import datetime
    try:
        instrument = MarketInstrument(
            exchange=body.exchange, symbol=body.symbol, token=body.token,
            segment=body.segment,
        )
        start = datetime.fromisoformat(body.start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(body.end.replace("Z", "+00:00"))
        if start >= end:
            raise ValueError("Historical start must be before end")
        bars = await market_data_service.historical(instrument, start, end, body.interval)
        return {
            "provider": provider, "account_id": account_id,
            "symbol": body.symbol, "interval": body.interval,
            "count": len(bars),
            "bars": [{
                "time": bar.start_time.isoformat(), "open": str(bar.open),
                "high": str(bar.high), "low": str(bar.low), "close": str(bar.close),
                "volume": bar.volume, "open_interest": bar.open_interest,
            } for bar in bars],
        }
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Historical data request failed: {type(exc).__name__}") from exc


@app.post("/api/v1/operator/market-data/verify/{channel}")
async def operator_verify_market_data_source(
    channel: str,
    wait_seconds: int = Query(default=12, ge=1, le=30),
    operator_id: str = Depends(require_air_operator),
) -> dict:
    if channel not in ("historical", "live"):
        raise HTTPException(status_code=422, detail="Channel must be historical or live")
    resolved = market_data_router.resolve(channel)
    if not resolved:
        raise HTTPException(status_code=409, detail=f"No connected {channel} source")
    provider, account_id, adapter = resolved[0]
    mappings = market_data_instruments.list_all(provider, account_id, limit=1)
    if not mappings:
        return {"provider": provider, "account_id": account_id,
                "status": "AUTHENTICATED_MAPPING_REQUIRED", "verified": False,
                "note": "Provider authentication succeeded, but add an official instrument-token mapping to test data delivery."}
    item = mappings[0]
    instrument = MarketInstrument(
        exchange=item["exchange"], symbol=item["symbol"], token=item["token"],
        segment=item["segment"], expiry=item.get("expiry"),
        strike=Decimal(str(item["strike"])) if item.get("strike") else None,
        option_type=item.get("option_type"), lot_size=item.get("lot_size"),
        instrument_type=item.get("instrument_type"))
    if channel == "historical":
        from datetime import datetime, timedelta, timezone
        end = datetime.now(timezone.utc)
        try:
            bars = await market_data_service.historical(instrument, end - timedelta(days=7), end, "day")
        except Exception as exc:
            return {"provider": provider, "account_id": account_id,
                    "status": "HISTORICAL_FAILED", "verified": False,
                    "error_type": type(exc).__name__}
        return {"provider": provider, "account_id": account_id,
                "status": "HISTORICAL_VERIFIED" if bars else "NO_HISTORICAL_BARS",
                "verified": bool(bars), "instrument": instrument.symbol,
                "bars_received": len(bars), "interval": "day"}
    before = market_data_hub.tick_count_for(instrument.token)
    try:
        await market_data_service.subscribe([instrument])
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while asyncio.get_running_loop().time() < deadline:
            if market_data_hub.tick_count_for(instrument.token) > before:
                return {"provider": provider, "account_id": account_id,
                        "status": "LIVE_TICK_VERIFIED", "verified": True,
                        "instrument": instrument.symbol,
                        "ticks_received": market_data_hub.tick_count_for(instrument.token) - before}
            await asyncio.sleep(0.25)
        health = adapter.health() if hasattr(adapter, "health") else {}
        return {"provider": provider, "account_id": account_id,
                "status": "SUBSCRIBED_WAITING_FOR_TICK", "verified": False,
                "instrument": instrument.symbol, "wait_seconds": wait_seconds,
                "provider_health": health,
                "note": "No tick arrived during this check. Retry during market hours and verify provider entitlements."}
    except Exception as exc:
        await market_data_router.mark_unhealthy("live", "subscription_failed")
        return {"provider": provider, "account_id": account_id,
                "status": "LIVE_SUBSCRIPTION_FAILED", "verified": False,
                "error_type": type(exc).__name__}


@app.get("/api/v1/market-data/status")
async def market_data_status(customer_id: str = Depends(require_air_operator)) -> dict:
    health = await market_data_service.health()
    return {
        "routing": market_data_router.status(),
        "provider_health": health,
        "stream": market_data_hub.status(),
        "note": "Historical and live channels can use different providers. Instrument subscriptions and fresh ticks must still be checked.",
    }


@app.put("/api/v1/market-data/main-account")
async def select_main_account(selection: MainAccountSelection,
                              customer_id: str = Depends(require_air_operator)) -> dict:
    try:
        owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(customer_id)}
        if (selection.provider.lower(), selection.account_id) not in owned:
            raise HTTPException(status_code=404, detail="Customer does not own this Main Account")
        provider = selection.provider.strip().lower()
        if not market_data_router.is_registered(provider, selection.account_id):
            adapter = _market_adapter_for(customer_id, provider, selection.account_id)
            market_data_router.register(selection.account_id, adapter)
        await market_data_router.set_main_account(provider, selection.account_id)
        market_data_sources.set_source("historical", provider, selection.account_id, True)
        market_data_sources.set_source("live", provider, selection.account_id, True)
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



@app.get("/api/v1/operator/execution-policy")
async def get_execution_policy(operator_id: str = Depends(require_air_operator)) -> dict:
    return execution_policy.get()


@app.put("/api/v1/operator/execution-policy")
async def update_execution_policy(
    body: ExecutionPolicyUpdate,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    try:
        return execution_policy.update(body.master_auto_enabled, body.strategies)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/operator/market-data/master-status")
async def get_broker_master_status(operator_id: str = Depends(require_air_operator)) -> dict:
    refresher = BrokerMasterRefresher(market_data_instruments)
    try:
        urls = {provider: bool(refresher.url_for(provider))
                for provider in ("dhan", "zerodha", "upstox", "fyers", "angelone")}
    finally:
        await refresher.close()
    return {"masters": market_data_instruments.master_status(),
            "refresh_time_ist": "07:00 weekdays", "configured_urls": urls}


@app.post("/api/v1/operator/market-data/masters/refresh")
async def refresh_broker_masters(operator_id: str = Depends(require_air_operator)) -> dict:
    refresher = BrokerMasterRefresher(market_data_instruments)
    results = []
    try:
        for account in account_directory.list_all():
            if account.broker not in {"dhan", "zerodha", "upstox", "fyers", "angelone"}:
                continue
            try:
                headers = _broker_master_headers(account.customer_id, account.broker, account.account_id)
                results.append(await refresher.refresh(account.broker, account.account_id, headers=headers))
            except Exception as exc:
                results.append({"customer_id": account.customer_id, "provider": account.broker,
                                "account_id": account.account_id,
                                "status": "FAILED", "error_type": type(exc).__name__})
    finally:
        await refresher.close()
    return {"results": results, "masters": market_data_instruments.master_status()}


@app.get("/api/v1/operator/market-data/sources")
async def operator_market_data_sources(
    operator_id: str = Depends(require_air_operator),
) -> dict:
    return {
        "providers": market_data_sources.catalog(),
        "selections": market_data_sources.selections(),
        "runtime": market_data_router.status(),
        "failover": market_data_sources.failover(),
        "channels": ["historical", "live"],
        "note": "Historical and live sources are selected independently. Only providers with verified adapters can be enabled; catalog entries are not a claim of a working adapter.",
    }


@app.put("/api/v1/operator/market-data/sources/{channel}")
async def operator_select_market_data_source(
    channel: str,
    body: MarketDataSourceSelection,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    if channel not in ("historical", "live"):
        raise HTTPException(status_code=422, detail="Channel must be historical or live")
    provider = body.provider.strip().lower()
    account_id = (body.account_id or "").strip() or None
    if not body.enabled:
        if channel in ("historical", "live"):
            await market_data_router.clear_source(channel)
        selected = market_data_sources.set_source(channel, provider, account_id, False)
        return {"selection": selected, "runtime": market_data_router.status()}

    if provider == "nse_bhavcopy":
        if channel != "historical":
            raise HTTPException(status_code=422, detail="NSE Bhavcopy is an EOD historical source only")
        await market_data_router.clear_source("historical")
        if not market_data_router.is_registered("nse_bhavcopy", "official"):
            market_data_router.register("official", NSEBhavcopyMarketDataAdapter())
        try:
            await market_data_router.set_source("historical", "nse_bhavcopy", "official")
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=f"NSE historical source is not ready: {str(exc)}") from exc
        selected = market_data_sources.set_source(channel, provider, None, True)
        return {"selection": selected, "runtime": market_data_router.status(),
                "status": "CONNECTED", "note": "NSE official EOD CM/FO store is the selected historical source."}

    if not account_id:
        raise HTTPException(status_code=422, detail=f"{provider} account ID is required")
    owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(operator_id)}
    if (provider, account_id) not in owned:
        raise HTTPException(status_code=404, detail=f"{provider} account is not assigned to this operator")
    try:
        if not market_data_router.is_registered(provider, account_id):
            adapter = _market_adapter_for(operator_id, provider, account_id)
            market_data_router.register(account_id, adapter)
        await market_data_router.set_source(channel, provider, account_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Provider credentials have not been saved") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Could not enable {channel} source: {str(exc)}") from exc
    selected = market_data_sources.set_source(channel, provider, account_id, True)
    return {"selection": selected, "runtime": market_data_router.status(),
            "status": "CONNECTED",
            "note": f"{provider} {channel} adapter authenticated successfully. Live quote mode: native WebSocket for supported brokers."}


@app.put("/api/v1/operator/market-data/sources/{channel}/failover")
async def operator_configure_market_data_failover(
    channel: str,
    body: MarketDataFailoverSelection,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    if channel not in ("historical", "live"):
        raise HTTPException(status_code=422, detail="Channel must be historical or live")
    owned = {(a.broker, a.account_id) for a in account_directory.list_for_customer(operator_id)}
    candidates: list[tuple[str, str]] = []
    try:
        for item in body.candidates:
            provider = str(item.get("provider", "")).strip().lower()
            account_id = str(item.get("account_id", "")).strip()
            if provider == "nse_bhavcopy" and channel == "historical":
                account_id = "official"
                if not market_data_router.is_registered(provider, account_id):
                    market_data_router.register(account_id, NSEBhavcopyMarketDataAdapter())
            else:
                if (provider, account_id) not in owned:
                    raise HTTPException(status_code=404, detail=f"{provider} account is not assigned to this operator")
                if not market_data_router.is_registered(provider, account_id):
                    market_data_router.register(account_id, _market_adapter_for(operator_id, provider, account_id))
            candidates.append((provider, account_id))
        await market_data_router.configure_failover(channel, candidates, body.enabled)
        persisted = [
            {"provider": provider, "account_id": account_id}
            for provider, account_id in candidates
        ]
        saved = market_data_sources.set_failover(channel, persisted, body.enabled)
        return {"failover": saved, "runtime": market_data_router.status()}
    except HTTPException:
        raise
    except (ValueError, RuntimeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc



@app.get("/api/v1/operator/telegram/destinations")
async def operator_list_telegram_destinations(
    operator_id: str = Depends(require_air_operator),
) -> dict:
    rows = telegram_destinations.list_destinations()
    from app.telegram_notifications import _settings
    token, _ = _settings()
    return {
        "destinations": rows,
        "bot_configured": bool(token),
        "legacy_env_fallback": not telegram_destinations.has_managed_destinations(),
        "supported_strategies": ["RECOVERED", "EXPIRY78", "EXPIRYSCAN"],
    }


@app.post("/api/v1/operator/telegram/destinations", status_code=201)
async def operator_add_telegram_destination(
    body: TelegramDestinationInput,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    try:
        row = telegram_destinations.upsert_destination(
            body.name, body.chat_id, body.destination_type, body.strategies, body.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="Telegram destination already exists") from exc
        raise
    return {"destination": row, "status": "saved"}


@app.put("/api/v1/operator/telegram/destinations/{destination_id}")
async def operator_update_telegram_destination(
    destination_id: int, body: TelegramDestinationInput,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    try:
        row = telegram_destinations.update_destination(
            destination_id, name=body.name, chat_id=body.chat_id,
            destination_type=body.destination_type, strategies=body.strategies,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="Telegram destination already exists") from exc
        raise
    if row is None:
        raise HTTPException(status_code=404, detail="Telegram destination not found")
    return {"destination": row, "status": "updated"}


@app.delete("/api/v1/operator/telegram/destinations/{destination_id}")
async def operator_delete_telegram_destination(
    destination_id: int, operator_id: str = Depends(require_air_operator),
) -> dict:
    if not telegram_destinations.delete_destination(destination_id):
        raise HTTPException(status_code=404, detail="Telegram destination not found")
    return {"destination_id": destination_id, "status": "deleted"}


@app.post("/api/v1/operator/telegram/test")
async def operator_test_telegram_destination(
    destination_id: int | None = None,
    operator_id: str = Depends(require_air_operator),
) -> dict:
    rows = telegram_destinations.list_destinations()
    selected = [row for row in rows if row["id"] == destination_id] if destination_id is not None else [
        row for row in rows if row["enabled"]
    ]
    if destination_id is not None and not selected:
        raise HTTPException(status_code=404, detail="Telegram destination not found")
    if any(not row["enabled"] for row in selected):
        raise HTTPException(status_code=409, detail="Enable the destination before testing it")
    if not selected:
        raise HTTPException(status_code=409, detail="Add and enable at least one Telegram destination first")
    result = await send_telegram_message(
        "✅ <b>AIR Telegram connection test</b>\\nThis destination is reachable. Alert routing is configured.",
        [row["chat_id"] for row in selected],
    )
    if not result.get("configured") or result.get("failures"):
        raise HTTPException(status_code=502, detail={
            "message": "Telegram test delivery failed",
            "sent": result.get("sent", 0), "failures": result.get("failures", []),
        })
    return {"status": "sent", "sent": result["sent"], "destination_ids": [row["id"] for row in selected]}


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
