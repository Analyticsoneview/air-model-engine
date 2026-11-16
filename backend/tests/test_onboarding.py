from datetime import date
import pytest
from app.onboarding import OnboardingStore, OnboardingConflict, REQUIRED_CONSENTS


def make_store(tmp_path):
    return OnboardingStore(database_url="", sqlite_path=str(tmp_path / "onboarding.sqlite3"))


def consents():
    return [
        {"consent_type": "TERMS", "document_version": "terms-1", "accepted": True},
        {"consent_type": "PRIVACY", "document_version": "privacy-1", "accepted": True},
        {"consent_type": "DATA_PROCESSING", "document_version": "dpa-1", "accepted": True},
        {"consent_type": "MARKETING", "document_version": "marketing-1", "accepted": False},
    ]


def test_required_consents_are_explicit_and_marketing_is_optional(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.record_consents("t1", "c1", consents()[:2], "consent-a")
    rows = store.record_consents("t1", "c1", consents(), "consent-b")
    assert len(rows) == 4
    assert rows[-1]["accepted"] is False
    assert len(store.consents("t1", "c1")) == 4


def test_required_consent_rejection_fails_closed(tmp_path):
    store = make_store(tmp_path)
    items = consents()
    items[0]["accepted"] = False
    with pytest.raises(ValueError):
        store.record_consents("t1", "c1", items, "consent-a")


def test_consent_idempotency_rejects_changed_content(tmp_path):
    store = make_store(tmp_path)
    items = consents()
    store.record_consents("t1", "c1", items, "consent-a")
    changed = consents()
    changed[0]["document_version"] = "terms-2"
    with pytest.raises(OnboardingConflict):
        store.record_consents("t1", "c1", changed, "consent-a")


def test_trial_state_machine_and_append_only_events(tmp_path):
    store = make_store(tmp_path)
    item = store.create("t1", "c1", "AIR", "B2C_TRADER_ANNUAL", "create-a", "c1")
    trial = store.transition("t1", "c1", item["onboarding_id"], "TRIAL", "c1", "trial-a", trial_days=14)
    assert trial["status"] == "TRIAL"
    assert trial["trial_ends_at"] > trial["trial_started_at"]
    active = store.transition("t1", "c1", item["onboarding_id"], "ACTIVE", "admin", "active-a")
    assert active["status"] == "ACTIVE"
    with pytest.raises(OnboardingConflict):
        store.transition("t1", "c1", item["onboarding_id"], "TRIAL", "c1", "trial-again")


def test_customer_cannot_recreate_active_onboarding(tmp_path):
    store = make_store(tmp_path)
    item = store.create("t1", "c1", "AIR", "B2C_TRADER_ANNUAL", "create-a", "c1")
    with pytest.raises(OnboardingConflict):
        store.create("t1", "c1", "AIR", "B2C_TRADER_ANNUAL", "create-b", "c1")


def test_tenant_isolation(tmp_path):
    store = make_store(tmp_path)
    item = store.create("tenant-a", "c1", "AIR", "B2C_TRADER_ANNUAL", "create-a", "c1")
    assert store.get("tenant-b", "c1") is None
    assert store.events("tenant-b", "c1", item["onboarding_id"]) == []

def test_expired_customer_can_start_a_new_onboarding_cycle(tmp_path):
    store = make_store(tmp_path)
    first = store.create("t1", "c1", "AIR", "B2C_TRADER_ANNUAL", "create-1", "c1")
    store.transition("t1", "c1", first["onboarding_id"], "TRIAL", "c1", "trial-1")
    store.transition("t1", "c1", first["onboarding_id"], "EXPIRED", "admin", "expire-1")
    second = store.create("t1", "c1", "AIR", "B2C_TRADER_ANNUAL", "create-2", "c1")
    renewed = store.transition("t1", "c1", second["onboarding_id"], "ACTIVE", "admin", "renew-1")
    assert renewed["status"] == "ACTIVE"
    assert store.get("t1", "c1")["onboarding_id"] == second["onboarding_id"]


def test_transition_idempotency_rejects_changed_details(tmp_path):
    store = make_store(tmp_path)
    item = store.create("t1", "c1", "AIR", "B2C_TRADER_ANNUAL", "create-1", "c1")
    store.transition("t1", "c1", item["onboarding_id"], "TRIAL", "c1", "trial-1",
                     {"consent_reference": "accepted"}, trial_days=14)
    with pytest.raises(OnboardingConflict):
        store.transition("t1", "c1", item["onboarding_id"], "TRIAL", "c1", "trial-1",
                         {"consent_reference": "different"}, trial_days=14)

def test_customer_cannot_self_activate_a_commercial_contract():
    from fastapi import HTTPException
    from app.commercial_contracts_api import ContractTransition, transition_contract

    body = ContractTransition(to_status="ACTIVE", idempotency_key="self-activate")
    with pytest.raises(HTTPException) as exc:
        transition_contract("contract-1", body, customer_id="customer-1")
    assert exc.value.status_code == 403
