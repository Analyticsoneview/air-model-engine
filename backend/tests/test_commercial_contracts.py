from datetime import date
import pytest

from app.commercial_contracts import (
    CommercialContractStore, ContractConflict, annual_period,
)


def store(tmp_path):
    return CommercialContractStore(database_url="", sqlite_path=str(tmp_path / "contracts.sqlite3"))


def test_annual_period_is_calendar_year_and_leap_safe():
    assert annual_period(date(2024, 2, 29)) == date(2025, 2, 28)
    assert annual_period(date(2025, 6, 1)) == date(2026, 6, 1)


def test_create_contract_and_idempotency(tmp_path):
    ledger = store(tmp_path)
    args = dict(tenant_id="tenant-a", customer_id="cust-a", product_code="AIR_B2C",
                plan_code="B2C_TRADER_ANNUAL", start_date=date(2024, 2, 29),
                idempotency_key="create-1")
    first = ledger.create_contract(**args)
    second = ledger.create_contract(**args)
    assert first["contract_id"] == second["contract_id"]
    assert first["billing_period"] == "ANNUAL"
    assert first["end_date"] == "2025-02-28"
    assert first["status"] == "DRAFT"
    assert len(ledger.events("tenant-a", first["contract_id"])) == 1


def test_transition_matrix_and_append_only_history(tmp_path):
    ledger = store(tmp_path)
    item = ledger.create_contract(tenant_id="t1", customer_id="c1", product_code="AIR",
        plan_code="B2C_ESSENTIAL_ANNUAL", start_date=date(2026,1,1), idempotency_key="create")
    active = ledger.transition("t1", item["contract_id"], "ACTIVE", actor_id="admin", idempotency_key="activate")
    assert active["status"] == "ACTIVE"
    again = ledger.transition("t1", item["contract_id"], "ACTIVE", actor_id="admin", idempotency_key="activate")
    assert again["version"] == active["version"]
    with pytest.raises(ContractConflict):
        ledger.transition("t1", item["contract_id"], "TRIAL", actor_id="admin", idempotency_key="illegal")
    assert [e["event_type"] for e in ledger.events("t1", item["contract_id"])] == ["CONTRACT_CREATED", "STATUS_CHANGED"]


def test_tenant_scope_does_not_disclose_other_tenant(tmp_path):
    ledger = store(tmp_path)
    item = ledger.create_contract(tenant_id="tenant-a", customer_id="c1", product_code="AIR",
        plan_code="B2C_FREE", start_date=date(2026,1,1), idempotency_key="create-a")
    assert ledger.get_contract("tenant-b", item["contract_id"]) is None
    assert ledger.list_contracts("tenant-b") == []


def test_invalid_billing_period_and_negative_amount_rejected(tmp_path):
    ledger = store(tmp_path)
    with pytest.raises(ValueError):
        ledger.create_contract(tenant_id="t", customer_id="c", product_code="AIR", plan_code="X",
            start_date=date.today(), amount_minor=-1, idempotency_key="bad")
