from datetime import date, timedelta
from app.commercial_contracts import CommercialContractStore
from app import usage_metering_api


def test_self_hosted_usage_uses_active_annual_contract_plan(tmp_path, monkeypatch):
    monkeypatch.delenv("AIR_CUSTOMER_DATABASE_URL", raising=False)
    monkeypatch.delenv("AIR_CUSTOMER_DATABASE_URL_FILE", raising=False)
    monkeypatch.setenv("AIR_COMMERCIAL_DB_PATH", str(tmp_path / "contracts.sqlite3"))
    ledger=CommercialContractStore(database_url="",sqlite_path=str(tmp_path / "contracts.sqlite3"))
    item=ledger.create_contract(tenant_id="customer-1",customer_id="customer-1",
        product_code="AIR_B2C",plan_code="B2C_TRADER_ANNUAL",start_date=date.today(),
        idempotency_key="local-contract")
    ledger.transition("customer-1",item["contract_id"],"ACTIVE",actor_id="customer-1",
        idempotency_key="local-activate")
    assert usage_metering_api._active_plan("customer-1","customer-1")=="B2C_TRADER_ANNUAL"


def test_self_hosted_usage_does_not_apply_expired_contract(tmp_path, monkeypatch):
    monkeypatch.delenv("AIR_CUSTOMER_DATABASE_URL", raising=False)
    monkeypatch.delenv("AIR_CUSTOMER_DATABASE_URL_FILE", raising=False)
    monkeypatch.setenv("AIR_COMMERCIAL_DB_PATH", str(tmp_path / "contracts.sqlite3"))
    ledger=CommercialContractStore(database_url="",sqlite_path=str(tmp_path / "contracts.sqlite3"))
    item=ledger.create_contract(tenant_id="customer-1",customer_id="customer-1",
        product_code="AIR_B2C",plan_code="B2C_ELITE_ANNUAL",
        start_date=date.today()-timedelta(days=400),idempotency_key="expired-contract")
    ledger.transition("customer-1",item["contract_id"],"ACTIVE",actor_id="customer-1",
        idempotency_key="expired-activate")
    assert usage_metering_api._active_plan("customer-1","customer-1")=="B2C_FREE"
