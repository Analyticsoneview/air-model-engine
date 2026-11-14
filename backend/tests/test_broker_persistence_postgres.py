"""PostgreSQL integration tests for customer broker accounts and encrypted credentials."""
from __future__ import annotations
import os
from unittest.mock import patch
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from app.brokers.customer_accounts import CustomerAccountDirectory, CustomerTradingAccount
from app.credential_vault import CredentialVault


def _database_url() -> str:
    url = os.getenv("AIR_TEST_CUSTOMER_DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("AIR_TEST_CUSTOMER_DATABASE_URL is not configured")
    if "test" not in url.rsplit("/", 1)[-1].lower():
        pytest.fail("Broker persistence integration tests require a disposable test database")
    return url


@pytest.fixture
def stores():
    url = _database_url()
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM broker_credentials"))
        conn.execute(text("DELETE FROM customer_market_data_selection"))
        conn.execute(text("DELETE FROM customer_market_data_access"))
        conn.execute(text("DELETE FROM customer_trading_accounts"))
    engine.dispose()
    env = {"AIR_ACCOUNT_DATABASE_URL": url, "AIR_CREDENTIAL_DATABASE_URL": url,
           "AIR_CREDENTIAL_KEY": Fernet.generate_key().decode()}
    with patch.dict(os.environ, env):
        accounts, vault = CustomerAccountDirectory(), CredentialVault()
        try:
            yield accounts, vault, url
        finally:
            vault.close()
            accounts.close()
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM broker_credentials"))
        conn.execute(text("DELETE FROM customer_market_data_selection"))
        conn.execute(text("DELETE FROM customer_market_data_access"))
        conn.execute(text("DELETE FROM customer_trading_accounts"))
    engine.dispose()


def test_postgres_account_ownership_and_order_permission(stores):
    accounts, _, _ = stores
    accounts.add(CustomerTradingAccount("customer-1", "Dhan", "D001", False))
    assert len(accounts.list_for_customer("customer-1")) == 1
    with pytest.raises(ValueError, match="already registered"):
        accounts.add(CustomerTradingAccount("customer-2", "Dhan", "D001", False))
    with pytest.raises(PermissionError, match="does not own"):
        accounts.authorize_order_target("customer-2", "dhan", "D001")
    with pytest.raises(PermissionError, match="disabled"):
        accounts.authorize_order_target("customer-1", "dhan", "D001")
    accounts.set_order_permission("customer-1", "dhan", "D001", True)
    accounts.authorize_order_target("customer-1", "dhan", "D001")


def test_postgres_market_data_entitlement_is_owned_and_transactional(stores):
    accounts, _, _ = stores
    accounts.add(CustomerTradingAccount("customer-1", "Dhan", "D001"))
    accounts.add(CustomerTradingAccount("customer-2", "Dhan", "D002"))
    with pytest.raises(PermissionError, match="paid entitlement"):
        accounts.set_market_data_selection("customer-1", "dhan", "D001")
    accounts.set_market_data_access("customer-1", "PAID", True)
    assert accounts.set_market_data_selection("customer-1", "dhan", "D001")["provider"] == "dhan"
    with pytest.raises(PermissionError, match="does not own"):
        accounts.set_market_data_selection("customer-1", "dhan", "D002")
    accounts.set_market_data_access("customer-1", "STANDARD", True)
    assert accounts.get_market_data_selection("customer-1") is None
    assert accounts.get_market_data_access("customer-1")["broker_data_enabled"] is False


def test_postgres_credential_vault_encrypts_and_scopes_credentials(stores):
    _, vault, url = stores
    secret = "dhan-token-sensitive-value"
    vault.put("customer-1", "dhan", "D001", {"access_token": secret, "client_id": "D001"})
    assert vault.get("customer-1", "dhan", "D001")["access_token"] == secret
    with pytest.raises(KeyError):
        vault.get("customer-2", "dhan", "D001")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            encrypted = conn.execute(text("""SELECT encrypted_payload FROM broker_credentials
                WHERE customer_id='customer-1' AND broker='dhan' AND account_id='D001'""")).scalar_one()
        assert secret.encode() not in bytes(encrypted)
    finally:
        engine.dispose()
