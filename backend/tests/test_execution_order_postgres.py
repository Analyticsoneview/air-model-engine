"""PostgreSQL integration tests for execution policy and durable order ledger."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.brokers.base import BrokerOrder
from app.services.execution_policy import ExecutionPolicy
from app.services.order_ledger import DurableOrderLedger

pytestmark = pytest.mark.skipif(
    not (os.getenv("AIR_EXECUTION_POLICY_DATABASE_URL") and os.getenv("AIR_ORDER_LEDGER_DATABASE_URL")),
    reason="Execution policy and order ledger PostgreSQL selectors are not configured",
)


def test_execution_policy_defaults_to_manual_and_fails_closed():
    policy = ExecutionPolicy()
    try:
        state = policy.get()
        assert state["master_auto_enabled"] is False
        assert state["manual_orders_enabled"] is True
        assert state["manual_order_submission_enabled"] is False
        assert state["live_orders_enabled"] is False
        with pytest.raises(PermissionError):
            policy.authorize_mode("EXPIRY78", "AUTO")
        policy.update(True, {"EXPIRY78": True})
        assert policy.authorize_mode("EXPIRY78", "AUTO") == "AUTO"
        with pytest.raises(PermissionError):
            policy.authorize_mode("RECOVERED", "AUTO")
        policy.update(False, {"EXPIRY78": False})
        with pytest.raises(PermissionError):
            policy.authorize_mode("EXPIRY78", "AUTO")
    finally:
        policy.close()


def test_durable_order_ledger_idempotency_recovery_and_event_history():
    ledger = DurableOrderLedger()
    broker = "zerodha"
    account_id = "acct-" + uuid.uuid4().hex
    key = "intent-" + uuid.uuid4().hex
    try:
        assert ledger.reserve(broker, account_id, key, {"symbol": "NIFTY", "mode": "PAPER"})
        # Separate processes/connections racing on the same intent still get one reservation.
        concurrent_key = "race-" + uuid.uuid4().hex
        race_account_id = "race-acct-" + uuid.uuid4().hex
        def reserve_once(_):
            connection = DurableOrderLedger()
            try:
                return connection.reserve(broker, account_id, concurrent_key, {"symbol": "BANKNIFTY"})
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=8) as pool:
            race_results = list(pool.map(reserve_once, range(8)))
        assert sum(race_results) == 1
        # A restart/retry with the same idempotency key cannot reserve again.
        assert not ledger.reserve(broker, account_id, key, {"symbol": "NIFTY", "mode": "PAPER"})
        pending = ledger.get(broker, account_id, key)
        assert pending is not None and pending.status == "PENDING"

        # An uncertain broker outcome remains reserved and is never auto-resubmitted.
        order = BrokerOrder(
            broker=broker,
            account_id=account_id,
            broker_order_id="paper-" + uuid.uuid4().hex,
            status="UNKNOWN",
            raw={"mode": "PAPER", "reconciliation_required": True},
        )
        ledger.record(order, key)
        assert not ledger.reserve(broker, account_id, key, {"symbol": "NIFTY"})
        saved = ledger.get(broker, account_id, key)
        assert saved is not None and saved.status == "UNKNOWN"
        assert saved.raw["reconciliation_required"] is True

        accepted = BrokerOrder(
            broker=broker,
            account_id=account_id,
            broker_order_id="paper-" + uuid.uuid4().hex,
            status="PAPER_ACCEPTED",
            raw={"mode": "PAPER", "quantity": 1},
        )
        ledger.record(accepted, key)
        assert ledger.get(broker, account_id, key).broker_order_id == accepted.broker_order_id
        events = ledger.list_events(broker, account_id, limit=10)
        assert [event["status"] for event in events][:3] == ["PAPER_ACCEPTED", "UNKNOWN", "PENDING"]
        assert ledger.list_orders(broker, account_id, limit=10)[0].status == "PAPER_ACCEPTED"
    finally:
        ledger.close()
