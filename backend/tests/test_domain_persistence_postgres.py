"""Disposable PostgreSQL integration tests for QOC, instrument, source and order stores."""
import os
import pytest
from app.air_qoc_store import AirQocStore
from app.market_data.instrument_registry import MarketInstrumentDirectory
from app.market_data.provider_registry import MarketDataSourceRegistry
from app.services.order_ledger import DurableOrderLedger
from app.services.execution_policy import ExecutionPolicy
from app.brokers.base import BrokerOrder

pytestmark = pytest.mark.skipif(
    not all(os.getenv(k) for k in (
        "AIR_QOC_DATABASE_URL","AIR_MARKET_INSTRUMENT_DATABASE_URL",
        "AIR_MARKET_SOURCE_DATABASE_URL","AIR_ORDER_LEDGER_DATABASE_URL",
        "AIR_EXECUTION_POLICY_DATABASE_URL")),
    reason="requires disposable PostgreSQL integration services")

def test_domain_repositories_round_trip_and_preserve_manual_only():
    qoc = AirQocStore()
    instruments = MarketInstrumentDirectory()
    sources = MarketDataSourceRegistry()
    ledger = DurableOrderLedger()
    policy = ExecutionPolicy()
    try:
        qoc.save_option_chain(account_id="integration-account", underlying_scrip="NIFTY",
            underlying_segment="IDX_I", expiry="2026-12-31", underlying_price=25000.0,
            observed_at="2026-11-14T10:00:00+05:30",
            chain={"oc":{"25000":{"ce":{"last_price":100,"volume":1000,"oi":5000}}}})
        rows=qoc.latest_observations(account_id="integration-account")
        assert rows and rows[0]["underlying_scrip"] == "NIFTY"
        instruments.replace_snapshot("zerodha","integration-account",[{
            "exchange":"NFO","symbol":"NIFTY26DEC25000CE","token":"integration-token",
            "segment":"NFO-OPT","underlying_symbol":"NIFTY","expiry":"2026-12-31",
            "strike":"25000","option_type":"CE","lot_size":75}])
        assert instruments.get("zerodha","integration-account","integration-token")["underlying_symbol"] == "NIFTY"
        sources.set_source("historical","nse_bhavcopy",None,True)
        sources.set_failover("live",[{"provider":"dhan","account_id":"integration-account"}],False)
        assert sources.selections()["historical"]["enabled"] is True
        assert sources.failover()["live"]["candidates"][0]["provider"] == "dhan"
        assert ledger.reserve("dhan","integration-account","integration-intent",{"symbol":"NIFTY"})
        assert not ledger.reserve("dhan","integration-account","integration-intent",{"symbol":"NIFTY"})
        ledger.record(BrokerOrder("dhan","integration-account","", "UNKNOWN",
            {"reconcile_before_retry":True}),"integration-intent")
        assert ledger.get("dhan","integration-account","integration-intent").status == "UNKNOWN"
        state=policy.get()
        assert state["default_mode"] == "MANUAL"
        assert state["live_orders_enabled"] is False
        assert all(not enabled for enabled in state["effective_auto"].values())
    finally:
        qoc.close(); instruments.close(); sources.close(); ledger.close(); policy.close()
