"""PostgreSQL integration coverage for core broker/execution repositories.

These tests run only when the integration workflow explicitly configures all
repository-specific PostgreSQL selectors. Ordinary SQLite unit runs skip them.
"""
import os
import uuid

import pytest
from cryptography.fernet import Fernet

from app.brokers.base import BrokerOrder
from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount
from app.credential_vault import CredentialVault
from app.services.execution_policy import ExecutionPolicy
from app.services.order_ledger import DurableOrderLedger


_REQUIRED_DATABASES = (
    "AIR_CREDENTIAL_DATABASE_URL",
    "AIR_CUSTOMER_ACCOUNTS_DATABASE_URL",
    "AIR_EXECUTION_POLICY_DATABASE_URL",
    "AIR_ORDER_LEDGER_DATABASE_URL",
)
pytestmark = pytest.mark.skipif(
    not all(os.getenv(name) for name in _REQUIRED_DATABASES),
    reason="Core PostgreSQL repository selectors are not configured",
)


def test_core_broker_and_execution_repositories_use_postgres(monkeypatch):
    monkeypatch.setenv("AIR_CREDENTIAL_KEY", Fernet.generate_key().decode())
    customer_id = "pg-domain-" + uuid.uuid4().hex
    account_id = "acct-" + uuid.uuid4().hex
    idempotency_key = "intent-" + uuid.uuid4().hex
    broker = "zerodha"

    vault = CredentialVault()
    directory = CustomerAccountDirectory()
    policy = ExecutionPolicy()
    ledger = DurableOrderLedger()

    try:
        credentials = {"api_key": "test-key", "access_token": "test-access-token"}
        vault.put(customer_id, broker, account_id, credentials)
        assert vault.get(customer_id, broker, account_id) == credentials
        assert vault.list_for_customer(customer_id)[0]["broker"] == broker

        directory.add(CustomerTradingAccount(customer_id, broker, account_id, True))
        assert directory.list_for_customer(customer_id)[0].enabled_for_orders is True
        directory.set_market_data_access(customer_id, "PAID", True)
        selected = directory.set_market_data_selection(customer_id, broker, account_id)
        assert selected["account_id"] == account_id
        directory.set_order_permission(customer_id, broker, account_id, False)
        assert directory.list_for_customer(customer_id)[0].enabled_for_orders is False

        policy.update(False, {"EXPIRY78": False, "EXPIRYSCAN": False, "RECOVERED": False})
        assert policy.get()["default_mode"] == "MANUAL"
        policy.update(True, {"EXPIRY78": True})
        assert policy.authorize_mode("EXPIRY78", "AUTO") == "AUTO"
        with pytest.raises(PermissionError):
            policy.authorize_mode("RECOVERED", "AUTO")
        policy.update(False, {"EXPIRY78": False})

        assert ledger.reserve(broker, account_id, idempotency_key, {"symbol": "NIFTY"})
        assert not ledger.reserve(broker, account_id, idempotency_key, {"symbol": "NIFTY"})
        order = BrokerOrder(
            broker=broker,
            account_id=account_id,
            broker_order_id="paper-" + uuid.uuid4().hex,
            status="PAPER_ACCEPTED",
            raw={"mode": "PAPER", "quantity": 1},
        )
        ledger.record(order, idempotency_key)
        saved = ledger.get(broker, account_id, idempotency_key)
        assert saved is not None
        assert saved.broker_order_id == order.broker_order_id
        assert saved.raw["mode"] == "PAPER"
        assert ledger.list_events(broker, account_id, limit=10)[0]["status"] == "PAPER_ACCEPTED"
        assert ledger.list_orders(broker, account_id, limit=10)[0].broker_order_id == order.broker_order_id

        vault.delete(customer_id, broker, account_id)
        directory.remove(customer_id, broker, account_id)
    finally:
        vault.close()
        directory.close()
        policy.close()
        ledger.close()
