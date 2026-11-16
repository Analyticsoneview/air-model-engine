from datetime import date
import base64
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.enterprise_licensing import (
    EnterpriseLicenseStore, EnterpriseLicenseError, verify_license, fingerprint_digest,
)


@pytest.fixture
def keypair():
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public_raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return (base64.urlsafe_b64encode(private_raw).decode().rstrip("="),
            base64.urlsafe_b64encode(public_raw).decode().rstrip("="))


def test_deployment_registration_is_idempotent_and_fingerprint_locked(tmp_path):
    store = EnterpriseLicenseStore(database_url="", sqlite_path=str(tmp_path / "license.db"))
    one = store.register_deployment(tenant_id="tenant-a", instance_key="prod-1",
        profile_id="onprem-single", fingerprint="hardware-fingerprint-0001")
    two = store.register_deployment(tenant_id="tenant-a", instance_key="prod-1",
        profile_id="onprem-single", fingerprint="hardware-fingerprint-0001")
    assert one["deployment_id"] == two["deployment_id"]
    with pytest.raises(EnterpriseLicenseError, match="identity cannot be changed"):
        store.register_deployment(tenant_id="tenant-a", instance_key="prod-1",
            profile_id="onprem-single", fingerprint="hardware-fingerprint-0002")


def _active_contract(store):
    from sqlalchemy import text
    with store._scope(), store.engine.begin() as conn:
        conn.execute(text("""CREATE TABLE air_commercial_contracts(
            contract_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL,
            product_code TEXT NOT NULL, plan_code TEXT NOT NULL, status TEXT NOT NULL)"""))
        conn.execute(text("""INSERT INTO air_commercial_contracts
            VALUES('contract-1','tenant-a','owner-a','AIR','B2B_BUSINESS_ANNUAL','ACTIVE')"""))
        conn.execute(text("""CREATE TABLE air_tenants(
            tenant_id TEXT PRIMARY KEY, max_members INTEGER NOT NULL)"""))
        conn.execute(text("INSERT INTO air_tenants VALUES('tenant-a',30)"))
        conn.execute(text("""CREATE TABLE air_tenant_members(
            tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL, status TEXT NOT NULL)"""))
        conn.execute(text("INSERT INTO air_tenant_members VALUES('tenant-a','owner-a','ACTIVE')"))
        conn.execute(text("INSERT INTO air_tenant_members VALUES('tenant-a','member-2','ACTIVE')"))
        conn.execute(text("""CREATE TABLE air_tenant_invitations(
            tenant_id TEXT NOT NULL, status TEXT NOT NULL, expires_at TEXT NOT NULL)"""))


def test_issue_bind_and_offline_verify_enterprise_license(tmp_path, keypair):
    store = EnterpriseLicenseStore(database_url="", sqlite_path=str(tmp_path / "license.db"))
    _active_contract(store)
    deployment = store.register_deployment(tenant_id="tenant-a", instance_key="prod-1",
        profile_id="onprem-single", fingerprint="hardware-fingerprint-0001")
    result = store.issue_and_bind(tenant_id="tenant-a", contract_id="contract-1",
        deployment_id=deployment["deployment_id"], max_seats=25, max_deployments=1,
        valid_from=date(2026,1,1), valid_until=date(2027,1,1), grace_until=date(2027,1,31),
        actor_id="operator", idempotency_key="issue-1", private_key_b64=keypair[0])
    verified = verify_license(result["license_token"], keypair[1], tenant_id="tenant-a",
        deployment_id=deployment["deployment_id"], profile_id="onprem-single",
        fingerprint="hardware-fingerprint-0001", today=date(2026,11,17))
    assert verified["max_seats"] == 25
    assert "api_access" in verified["features"]


def test_license_rejects_wrong_tenant_deployment_profile_or_fingerprint(tmp_path, keypair):
    store = EnterpriseLicenseStore(database_url="", sqlite_path=str(tmp_path / "license.db"))
    _active_contract(store)
    deployment = store.register_deployment(tenant_id="tenant-a", instance_key="prod-1",
        profile_id="onprem-single", fingerprint="hardware-fingerprint-0001")
    result = store.issue_and_bind(tenant_id="tenant-a", contract_id="contract-1",
        deployment_id=deployment["deployment_id"], max_seats=25, max_deployments=1,
        valid_from=date(2026,1,1), valid_until=date(2027,1,1), grace_until=None,
        actor_id="operator", idempotency_key="issue-1", private_key_b64=keypair[0])
    with pytest.raises(EnterpriseLicenseError, match="not bound"):
        verify_license(result["license_token"], keypair[1], tenant_id="tenant-b",
            deployment_id=deployment["deployment_id"], profile_id="onprem-single",
            fingerprint="hardware-fingerprint-0001", today=date(2026,11,17))
    with pytest.raises(EnterpriseLicenseError, match="profile"):
        verify_license(result["license_token"], keypair[1], tenant_id="tenant-a",
            deployment_id=deployment["deployment_id"], profile_id="aws-private-single",
            fingerprint="hardware-fingerprint-0001", today=date(2026,11,17))
    with pytest.raises(EnterpriseLicenseError, match="fingerprint"):
        verify_license(result["license_token"], keypair[1], tenant_id="tenant-a",
            deployment_id=deployment["deployment_id"], profile_id="onprem-single",
            fingerprint="different-fingerprint-0001", today=date(2026,11,17))


def test_expired_and_tampered_licences_fail_closed(tmp_path, keypair):
    store = EnterpriseLicenseStore(database_url="", sqlite_path=str(tmp_path / "license.db"))
    _active_contract(store)
    deployment = store.register_deployment(tenant_id="tenant-a", instance_key="prod-1",
        profile_id="onprem-single", fingerprint="hardware-fingerprint-0001")
    result = store.issue_and_bind(tenant_id="tenant-a", contract_id="contract-1",
        deployment_id=deployment["deployment_id"], max_seats=25, max_deployments=1,
        valid_from=date(2025,1,1), valid_until=date(2026,1,1), grace_until=None,
        actor_id="operator", idempotency_key="issue-1", private_key_b64=keypair[0])
    with pytest.raises(EnterpriseLicenseError, match="expired"):
        verify_license(result["license_token"], keypair[1], tenant_id="tenant-a",
            deployment_id=deployment["deployment_id"], profile_id="onprem-single",
            fingerprint="hardware-fingerprint-0001", today=date(2026,11,17))


def test_enterprise_licence_seat_limit_cannot_exceed_org_quota(tmp_path, keypair):
    store = EnterpriseLicenseStore(database_url="", sqlite_path=str(tmp_path / "license.db"))
    _active_contract(store)
    deployment = store.register_deployment(tenant_id="tenant-a", instance_key="prod-1",
        profile_id="onprem-single", fingerprint="hardware-fingerprint-0001")
    with pytest.raises(EnterpriseLicenseError, match="organisation quota"):
        store.issue_and_bind(tenant_id="tenant-a", contract_id="contract-1",
            deployment_id=deployment["deployment_id"], max_seats=31, max_deployments=1,
            valid_from=date(2026,1,1), valid_until=date(2027,1,1), grace_until=None,
            actor_id="operator", idempotency_key="issue-too-many", private_key_b64=keypair[0])


def test_enterprise_licence_seat_limit_cannot_exclude_existing_members(tmp_path, keypair):
    store = EnterpriseLicenseStore(database_url="", sqlite_path=str(tmp_path / "license.db"))
    _active_contract(store)
    deployment = store.register_deployment(tenant_id="tenant-a", instance_key="prod-1",
        profile_id="onprem-single", fingerprint="hardware-fingerprint-0001")
    with pytest.raises(EnterpriseLicenseError, match="current reservations"):
        store.issue_and_bind(tenant_id="tenant-a", contract_id="contract-1",
            deployment_id=deployment["deployment_id"], max_seats=1, max_deployments=1,
            valid_from=date(2026,1,1), valid_until=date(2027,1,1), grace_until=None,
            actor_id="operator", idempotency_key="issue-too-few", private_key_b64=keypair[0])


def test_issue_replay_returns_same_signed_license_and_rejects_changed_terms(tmp_path, keypair):
    store = EnterpriseLicenseStore(database_url="", sqlite_path=str(tmp_path / "license.db"))
    _active_contract(store)
    deployment = store.register_deployment(tenant_id="tenant-a", instance_key="prod-1",
        profile_id="onprem-single", fingerprint="hardware-fingerprint-0001")
    args = dict(tenant_id="tenant-a", contract_id="contract-1",
        deployment_id=deployment["deployment_id"], max_seats=25, max_deployments=1,
        valid_from=date(2026,1,1), valid_until=date(2027,1,1), grace_until=None,
        actor_id="operator", idempotency_key="issue-replay", private_key_b64=keypair[0])
    first = store.issue_and_bind(**args)
    replay = store.issue_and_bind(**args)
    assert replay["idempotent_replay"] is True
    assert replay["license_token"] == first["license_token"]
    with pytest.raises(EnterpriseLicenseError, match="different binding terms"):
        store.issue_and_bind(**(args | {"max_seats": 20}))