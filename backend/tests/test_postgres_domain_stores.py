"""PostgreSQL integration coverage for core broker/execution repositories.

These tests run only when the integration workflow explicitly configures all
repository-specific PostgreSQL selectors. Ordinary SQLite unit runs skip them.
"""
import json
import os
import sqlite3
import uuid

import pytest
from cryptography.fernet import Fernet

from app.brokers.base import BrokerOrder
from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount
from app.credential_vault import CredentialVault
from app.services.execution_policy import ExecutionPolicy
from app.services.order_ledger import DurableOrderLedger
from app.admin_auth_postgres import PostgresAdminAuthStore
from app.security import hash_password
from app.scripts.migrate_customer_auth_sqlite_to_postgres import migrate as import_customer_auth
from app.scripts.migrate_admin_sqlite_to_postgres import migrate as import_admin_auth
from scripts.import_sqlite_domain_stores import run as import_sqlite_domain_stores


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


def test_sqlite_customer_auth_import_is_field_reconciled(tmp_path):
    source_path = tmp_path / "air_auth.sqlite3"
    source = sqlite3.connect(source_path)
    source.executescript("""
        CREATE TABLE customers (
            customer_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE air_access_requests (
            request_id TEXT PRIMARY KEY, mobile_e164 TEXT NOT NULL,
            device_id TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
            reviewed_at TEXT, reviewer_note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE air_device_sessions (
            session_id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
    """)
    source.execute(
        "INSERT INTO customers VALUES(?,?,?,?,?)",
        ("legacy-customer-auth-1", "legacy-customer@example.test", "password-hash", 1, "2026-11-01 10:00:00"),
    )
    source.execute(
        "INSERT INTO air_access_requests VALUES(?,?,?,?,?,?,?)",
        ("legacy-request-1", "+14155550123", "legacy-device-1", "APPROVED",
         "2026-11-01 10:01:00", "2026-11-01 10:02:00", "migrated"),
    )
    source.execute(
        "INSERT INTO air_device_sessions VALUES(?,?,?,?)",
        ("legacy-session-1", "legacy-request-1", 1, "2026-11-01 10:03:00"),
    )
    source.commit()
    source.close()

    imported = import_customer_auth(str(source_path), os.getenv("AIR_CUSTOMER_DATABASE_URL"))
    assert imported["status"] == "IMPORTED_AND_RECONCILED"
    assert imported["customers"] == 1
    assert imported["air_access_requests"] == 1
    assert imported["air_device_sessions"] == 1
    repeated = import_customer_auth(str(source_path), os.getenv("AIR_CUSTOMER_DATABASE_URL"))
    assert repeated["status"] == "ALREADY_IMPORTED"


def test_sqlite_admin_auth_import_preserves_admin_and_mfa(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    cipher = Fernet(key)
    monkeypatch.setenv("AIR_ADMIN_MFA_KEY", key.decode())

    source_path = tmp_path / "air_auth.sqlite3"
    source = sqlite3.connect(source_path)
    source.executescript("""
        CREATE TABLE air_admin_users (
            admin_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL, mfa_secret BLOB NOT NULL,
            role TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, last_totp_counter INTEGER NOT NULL DEFAULT -1,
            must_change_password INTEGER NOT NULL DEFAULT 0, failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE air_admin_sessions (
            session_id TEXT PRIMARY KEY, admin_id TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE air_admin_login_limits (
            rate_key TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
            window_started INTEGER NOT NULL, locked_until INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE air_admin_audit (
            event_id TEXT PRIMARY KEY, actor_admin_id TEXT, action TEXT NOT NULL,
            target_admin_id TEXT, details TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
    """)
    admin_id = "admin-test-0001"
    source.execute(
        "INSERT INTO air_admin_users VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (admin_id, "legacy-admin@example.test", hash_password("LegacyPass!234"),
         cipher.encrypt(b"JBSWY3DPEHPK3PXP"), "SUPER_ADMIN", 1,
         "2026-11-01 10:00:00", -1, 0, 0, 0),
    )
    source.execute(
        "INSERT INTO air_admin_sessions VALUES(?,?,?,?)",
        ("legacy-session-0001", admin_id, 1, "2026-11-01 10:01:00"),
    )
    source.execute(
        "INSERT INTO air_admin_login_limits VALUES(?,?,?,?)",
        ("legacy-rate-key", 2, 1793500000, 0),
    )
    source.execute(
        "INSERT INTO air_admin_audit VALUES(?,?,?,?,?,?)",
        ("legacy-event-0001", admin_id, "LEGACY_BOOTSTRAP", admin_id, "preserve", "2026-11-01 10:00:00"),
    )
    source.commit()
    source.close()

    imported = import_admin_auth(str(source_path), os.getenv("AIR_DATABASE_URL"))
    assert imported["status"] == "IMPORTED_AND_RECONCILED"
    assert imported["air_admin_users"] == 1
    assert import_admin_auth(str(source_path), os.getenv("AIR_DATABASE_URL"))["status"] == "ALREADY_IMPORTED"

    store = PostgresAdminAuthStore(database_url=os.getenv("AIR_DATABASE_URL"), redis_url=None)
    try:
        admins = store.list_admins()
        assert len(admins) == 1
        assert admins[0]["admin_id"] == admin_id
        assert store.session("legacy-session-0001")["email"] == "legacy-admin@example.test"
        assert store.audit_events(limit=10)[0]["event_id"] == "legacy-event-0001"
    finally:
        store.close()


def test_sqlite_domain_store_import_is_field_reconciled(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    cipher = Fernet(key)
    monkeypatch.setenv("AIR_CREDENTIAL_KEY", key.decode())

    credentials_db = sqlite3.connect(tmp_path / "air_credentials.sqlite3")
    credentials_db.execute("""
        CREATE TABLE broker_credentials (
            customer_id TEXT NOT NULL, broker TEXT NOT NULL, account_id TEXT NOT NULL,
            encrypted_payload BLOB NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(customer_id, broker, account_id)
        )
    """)
    encrypted = cipher.encrypt(json.dumps({"api_key": "legacy-key", "access_token": "legacy-token"}).encode())
    credentials_db.execute(
        "INSERT INTO broker_credentials VALUES(?,?,?,?,?)",
        ("legacy-customer", "zerodha", "legacy-account", encrypted, "2026-11-01T10:00:00+00:00"),
    )
    credentials_db.commit()
    credentials_db.close()

    accounts_db = sqlite3.connect(tmp_path / "customer_accounts.sqlite3")
    accounts_db.executescript("""
        CREATE TABLE customer_trading_accounts (
            customer_id TEXT NOT NULL, broker TEXT NOT NULL, account_id TEXT NOT NULL,
            enabled_for_orders INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            PRIMARY KEY (broker, account_id)
        );
        CREATE TABLE customer_market_data_access (
            customer_id TEXT PRIMARY KEY, tier TEXT NOT NULL,
            broker_data_enabled INTEGER NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE customer_market_data_selection (
            customer_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
            account_id TEXT NOT NULL, updated_at TEXT NOT NULL
        );
    """)
    accounts_db.execute(
        "INSERT INTO customer_trading_accounts VALUES(?,?,?,?,?)",
        ("legacy-customer", "zerodha", "legacy-account", 1, "2026-11-01T10:00:00+00:00"),
    )
    accounts_db.execute(
        "INSERT INTO customer_market_data_access VALUES(?,?,?,?)",
        ("legacy-customer", "PAID", 1, "2026-11-01T10:00:00+00:00"),
    )
    accounts_db.execute(
        "INSERT INTO customer_market_data_selection VALUES(?,?,?,?)",
        ("legacy-customer", "zerodha", "legacy-account", "2026-11-01T10:00:00+00:00"),
    )
    accounts_db.commit()
    accounts_db.close()

    policy_db = sqlite3.connect(tmp_path / "air_execution_policy.sqlite3")
    policy_db.execute("""
        CREATE TABLE execution_policy (
            id INTEGER PRIMARY KEY CHECK(id=1), master_auto_enabled INTEGER NOT NULL,
            strategy_json TEXT NOT NULL, updated_at TEXT NOT NULL
        )
    """)
    policy_db.execute(
        "INSERT INTO execution_policy VALUES(1,0,?,?)",
        (json.dumps({"EXPIRY78": False, "EXPIRYSCAN": False, "RECOVERED": False}), "2026-11-01T10:00:00+00:00"),
    )
    policy_db.commit()
    policy_db.close()

    orders_db = sqlite3.connect(tmp_path / "air_orders.sqlite3")
    orders_db.executescript("""
        CREATE TABLE order_ledger (
            broker TEXT NOT NULL, account_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
            broker_order_id TEXT NOT NULL, status TEXT NOT NULL, raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (broker, account_id, idempotency_key)
        );
        CREATE TABLE order_ledger_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, broker TEXT NOT NULL,
            account_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, status TEXT NOT NULL,
            broker_order_id TEXT NOT NULL, raw_json TEXT NOT NULL, event_at TEXT NOT NULL
        );
    """)
    orders_db.execute(
        "INSERT INTO order_ledger VALUES(?,?,?,?,?,?,?,?)",
        ("zerodha", "legacy-account", "legacy-intent", "legacy-order-1", "PAPER_ACCEPTED",
         json.dumps({"symbol": "NIFTY", "quantity": 1}), "2026-11-01T10:00:00+00:00", "2026-11-01T10:00:00+00:00"),
    )
    orders_db.execute(
        "INSERT INTO order_ledger_events VALUES(?,?,?,?,?,?,?,?)",
        (17, "zerodha", "legacy-account", "legacy-intent", "PAPER_ACCEPTED", "legacy-order-1",
         json.dumps({"symbol": "NIFTY", "quantity": 1}), "2026-11-01T10:00:00+00:00"),
    )
    orders_db.commit()
    orders_db.close()

    dry_run = import_sqlite_domain_stores(tmp_path, dry_run=True)
    assert dry_run["status"] == "DRY_RUN_VALIDATED"
    imported = import_sqlite_domain_stores(tmp_path, dry_run=False)
    assert imported["status"] == "IMPORTED_AND_RECONCILED"
    assert imported["tables"]["broker_credentials"]["source_rows"] == 1
    assert imported["tables"]["order_ledger_events"]["target_rows_after"] == 1
    assert import_sqlite_domain_stores(tmp_path, dry_run=False)["status"] == "ALREADY_IMPORTED"

    vault = CredentialVault()
    directory = CustomerAccountDirectory()
    policy = ExecutionPolicy()
    ledger = DurableOrderLedger()
    try:
        assert vault.get("legacy-customer", "zerodha", "legacy-account") == {
            "api_key": "legacy-key", "access_token": "legacy-token"
        }
        assert directory.list_for_customer("legacy-customer")[0].enabled_for_orders is True
        assert directory.get_market_data_selection("legacy-customer")["account_id"] == "legacy-account"
        assert policy.get()["master_auto_enabled"] is False
        legacy_order = ledger.get("zerodha", "legacy-account", "legacy-intent")
        assert legacy_order is not None and legacy_order.broker_order_id == "legacy-order-1"
        assert ledger.list_events("zerodha", "legacy-account", limit=10)[0]["event_id"] == 17
    finally:
        vault.close()
        directory.close()
        policy.close()
        ledger.close()


def test_sqlite_domain_store_import_is_field_reconciled(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    cipher = Fernet(key)
    monkeypatch.setenv("AIR_CREDENTIAL_KEY", key.decode())

    credentials_db = sqlite3.connect(tmp_path / "air_credentials.sqlite3")
    credentials_db.execute("""
        CREATE TABLE broker_credentials (
            customer_id TEXT NOT NULL, broker TEXT NOT NULL, account_id TEXT NOT NULL,
            encrypted_payload BLOB NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(customer_id, broker, account_id)
        )
    """)
    encrypted = cipher.encrypt(json.dumps({"api_key": "legacy-key", "access_token": "legacy-token"}).encode())
    credentials_db.execute(
        "INSERT INTO broker_credentials VALUES(?,?,?,?,?)",
        ("legacy-customer", "zerodha", "legacy-account", encrypted, "2026-11-01T10:00:00+00:00"),
    )
    credentials_db.commit()
    credentials_db.close()

    accounts_db = sqlite3.connect(tmp_path / "customer_accounts.sqlite3")
    accounts_db.executescript("""
        CREATE TABLE customer_trading_accounts (
            customer_id TEXT NOT NULL, broker TEXT NOT NULL, account_id TEXT NOT NULL,
            enabled_for_orders INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            PRIMARY KEY (broker, account_id)
        );
        CREATE TABLE customer_market_data_access (
            customer_id TEXT PRIMARY KEY, tier TEXT NOT NULL,
            broker_data_enabled INTEGER NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE customer_market_data_selection (
            customer_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
            account_id TEXT NOT NULL, updated_at TEXT NOT NULL
        );
    """)
    accounts_db.execute(
        "INSERT INTO customer_trading_accounts VALUES(?,?,?,?,?)",
        ("legacy-customer", "zerodha", "legacy-account", 1, "2026-11-01T10:00:00+00:00"),
    )
    accounts_db.execute(
        "INSERT INTO customer_market_data_access VALUES(?,?,?,?)",
        ("legacy-customer", "PAID", 1, "2026-11-01T10:00:00+00:00"),
    )
    accounts_db.execute(
        "INSERT INTO customer_market_data_selection VALUES(?,?,?,?)",
        ("legacy-customer", "zerodha", "legacy-account", "2026-11-01T10:00:00+00:00"),
    )
    accounts_db.commit()
    accounts_db.close()

    policy_db = sqlite3.connect(tmp_path / "air_execution_policy.sqlite3")
    policy_db.execute("""
        CREATE TABLE execution_policy (
            id INTEGER PRIMARY KEY CHECK(id=1), master_auto_enabled INTEGER NOT NULL,
            strategy_json TEXT NOT NULL, updated_at TEXT NOT NULL
        )
    """)
    policy_db.execute(
        "INSERT INTO execution_policy VALUES(1,0,?,?)",
        (json.dumps({"EXPIRY78": False, "EXPIRYSCAN": False, "RECOVERED": False}), "2026-11-01T10:00:00+00:00"),
    )
    policy_db.commit()
    policy_db.close()

    orders_db = sqlite3.connect(tmp_path / "air_orders.sqlite3")
    orders_db.executescript("""
        CREATE TABLE order_ledger (
            broker TEXT NOT NULL, account_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
            broker_order_id TEXT NOT NULL, status TEXT NOT NULL, raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (broker, account_id, idempotency_key)
        );
        CREATE TABLE order_ledger_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, broker TEXT NOT NULL,
            account_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, status TEXT NOT NULL,
            broker_order_id TEXT NOT NULL, raw_json TEXT NOT NULL, event_at TEXT NOT NULL
        );
    """)
    orders_db.execute(
        "INSERT INTO order_ledger VALUES(?,?,?,?,?,?,?,?)",
        ("zerodha", "legacy-account", "legacy-intent", "legacy-order-1", "PAPER_ACCEPTED",
         json.dumps({"symbol": "NIFTY", "quantity": 1}), "2026-11-01T10:00:00+00:00", "2026-11-01T10:00:00+00:00"),
    )
    orders_db.execute(
        "INSERT INTO order_ledger_events VALUES(?,?,?,?,?,?,?,?)",
        (17, "zerodha", "legacy-account", "legacy-intent", "PAPER_ACCEPTED", "legacy-order-1",
         json.dumps({"symbol": "NIFTY", "quantity": 1}), "2026-11-01T10:00:00+00:00"),
    )
    orders_db.commit()
    orders_db.close()

    dry_run = import_sqlite_domain_stores(tmp_path, dry_run=True)
    assert dry_run["status"] == "DRY_RUN_VALIDATED"
    imported = import_sqlite_domain_stores(tmp_path, dry_run=False)
    assert imported["status"] == "IMPORTED_AND_RECONCILED"
    assert imported["tables"]["broker_credentials"]["source_rows"] == 1
    assert imported["tables"]["order_ledger_events"]["target_rows_after"] == 1

    vault = CredentialVault()
    directory = CustomerAccountDirectory()
    policy = ExecutionPolicy()
    ledger = DurableOrderLedger()
    try:
        assert vault.get("legacy-customer", "zerodha", "legacy-account") == {
            "api_key": "legacy-key", "access_token": "legacy-token"
        }
        assert directory.list_for_customer("legacy-customer")[0].enabled_for_orders is True
        assert directory.get_market_data_selection("legacy-customer")["account_id"] == "legacy-account"
        assert policy.get()["master_auto_enabled"] is False
        legacy_order = ledger.get("zerodha", "legacy-account", "legacy-intent")
        assert legacy_order is not None and legacy_order.broker_order_id == "legacy-order-1"
        assert ledger.list_events("zerodha", "legacy-account", limit=10)[0]["event_id"] == 17
    finally:
        vault.close()
        directory.close()
        policy.close()
        ledger.close()


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
