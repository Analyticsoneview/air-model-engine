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


def test_service_customer_download_is_not_metered(monkeypatch):
    calls = []
    monkeypatch.setattr(usage_metering_api, "_meter", lambda: calls.append("meter"))
    result = usage_metering_api.record_licensed_data_download("service-1", "SERVICE", 4096, "")
    assert result == {"metered": False, "customer_type": "SERVICE"}
    assert calls == []


def test_data_product_download_is_metered_in_bytes(monkeypatch):
    class Meter:
        def consume(self, *args, **kwargs):
            return {"metric": args[2], "quantity": args[3], "allowed": True}
    monkeypatch.setattr(usage_metering_api, "_tenant", lambda customer: "tenant-1")
    monkeypatch.setattr(usage_metering_api, "_active_plan", lambda customer, tenant: "B2C_TRADER_ANNUAL")
    monkeypatch.setattr(usage_metering_api, "_meter", lambda: Meter())
    result = usage_metering_api.record_licensed_data_download(
        "product-1", "DATA_PRODUCT", 4096, "download-001",
        metadata={"market": "FO", "row_count": 12},
    )
    assert result["metered"] is True
    assert result["metric"] == "licensed_data_bytes"
    assert result["quantity"] == 4096


def test_data_product_download_requires_idempotency_key(monkeypatch):
    import pytest
    from fastapi import HTTPException
    monkeypatch.setattr(usage_metering_api, "_tenant", lambda customer: "tenant-1")
    monkeypatch.setattr(usage_metering_api, "_active_plan", lambda customer, tenant: "B2C_TRADER_ANNUAL")
    with pytest.raises(HTTPException) as error:
        usage_metering_api.record_licensed_data_download("product-1", "DATA_PRODUCT", 4096, "")
    assert error.value.status_code == 400
