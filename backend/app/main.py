import os
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from uuid import uuid4
import secrets

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.auth_store import AuthStore
from app.access_control import access_store
from app.admin_auth import get_admin_auth_store
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
from app.market_data.customer_runtime import (configure_customer_market_data_runtime, invalidate_customer_market_data_service, close_customer_market_data_runtimes, get_customer_market_data_status)
from app.air_qoc_dhan import router as air_qoc_dhan_router
from app.model_engine_api import router as model_engine_router
from app.backtest_api import router as backtest_router
from app.model_engine_settlement_comparison import router as settlement_comparison_router
from app.orb_strategy_api import router as orb_strategy_router
from app.workflow_api import router as workflow_router
from app.air_monthly_pd_api import router as monthly_pd_router
from app.air_qoc_scheduler import start_qoc_scheduler, stop_qoc_scheduler, capture_dhan_eod_snapshots, capture_selected_provider_option_chains
from app.air_telegram_scheduler import start_telegram_scheduler, stop_telegram_scheduler
from app.telegram_notifications import send_telegram_message
from app.account_reporting import AccountReporting
from app.portfolio_risk import PortfolioRiskStore, build_portfolio_snapshot
from app.support_center import SupportStore
from app import telegram_destinations
from app.deployment_profiles import load_runtime_profile
from app.nse_bhavcopy import (nse_data_status, nse_data_rows, nse_bootstrap_is_ready, start_nse_data_jobs, stop_nse_data_jobs, trigger_nse_bootstrap)
from app.market_intelligence import build_market_intelligence_pulse
from app.security import create_access_token, create_admin_access_token, hash_password, require_customer, require_admin, verify_password
from app.persistence import get_persistence_runtime
from app.workflow_events import build_idempotency_key, emit_workflow_event
from app.workflow_engine import WorkflowStore
from app.installation_readiness import evaluate_workflow_runtime
from app.tenant_storage_api import router as tenant_storage_router
from app.internal_workspace_api import router as internal_workspace_router
from app.commercial_catalogue import public_catalogue, resolve_entitlements
from app.commercial_contracts_api import router as commercial_contracts_router
from app.usage_metering_api import router as usage_metering_router
from app.payment_providers_api import router as payment_providers_router
from app.billing_api import router as billing_router
from app.onboarding_api import router as onboarding_router
from app.tenant_memberships_api import router as tenant_memberships_router

app = FastAPI(title="AIR Model Engine API", version="0.3.0",
              description="Self-hosted AIR authentication, broker account and market-data gateway.")
app.include_router(air_qoc_dhan_router)
app.include_router(model_engine_router)
app.include_router(backtest_router)
app.include_router(settlement_comparison_router)
app.include_router(orb_strategy_router)
app.include_router(workflow_router)
app.include_router(monthly_pd_router)
app.include_router(tenant_storage_router)
app.include_router(internal_workspace_router)
app.include_router(commercial_contracts_router)
app.include_router(usage_metering_router)
app.include_router(payment_providers_router)
app.include_router(billing_router)
app.include_router(onboarding_router)
app.include_router(tenant_memberships_router)
_cors_origins = [
    origin.strip() for origin in os.getenv("AIR_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-AIR-ADMIN-KEY", "Idempotency-Key"],