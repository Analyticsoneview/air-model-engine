from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from app.tenant_memberships import MembershipConflict, TenantMembershipStore


@pytest.fixture
def membership_store():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE air_tenants (
            tenant_id TEXT PRIMARY KEY, name TEXT NOT NULL, plan_code TEXT NOT NULL, status TEXT NOT NULL, max_members INTEGER NOT NULL)"""))
        conn.execute(text("""CREATE TABLE air_tenant_members (
            tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL, role TEXT NOT NULL,
            status TEXT NOT NULL, joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (tenant_id, customer_id))"""))
        conn.execute(text("""CREATE TABLE air_tenant_invitations (
            invitation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, invited_customer_id TEXT NOT NULL,
            role TEXT NOT NULL, invited_by TEXT NOT NULL, status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            accepted_at TEXT, revoked_at TEXT, UNIQUE(tenant_id,idempotency_key))"""))
        conn.execute(text("""CREATE TABLE air_tenant_membership_events (
            event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL,
            actor_id TEXT NOT NULL, event_type TEXT NOT NULL, from_role TEXT, to_role TEXT,
            idempotency_key TEXT NOT NULL, details TEXT NOT NULL, occurred_at TEXT NOT NULL,
            UNIQUE(tenant_id,idempotency_key))"""))
        conn.execute(text("INSERT INTO air_tenants VALUES('org-a','Organisation A','STANDARD','ACTIVE',3),('org-b','Organisation B','STANDARD','ACTIVE',2)"))
        conn.execute(text("""INSERT INTO air_tenant_members(tenant_id,customer_id,role,status)
            VALUES('org-a','owner-a','OWNER','ACTIVE'),
                  ('org-b','owner-b','OWNER','ACTIVE')"""))
    yield TenantMembershipStore(engine)
    engine.dispose()


def test_invitation_reserves_seat_and_replay_is_idempotent(membership_store):
    store = membership_store
    first = store.invite("org-a", "owner-a", "customer-1", "MEMBER", "invite-1")
    replay = store.invite("org-a", "owner-a", "customer-1", "MEMBER", "invite-1")
    assert first["invitation_id"] == replay["invitation_id"]
    assert replay["idempotent_replay"] is True
    usage = store.seat_usage("org-a", "owner-a")
    assert (usage["active_members"], usage["pending_invitations"], usage["available_seats"]) == (1, 1, 1)


def test_seat_limit_counts_pending_invitations(membership_store):
    store = membership_store
    store.invite("org-a", "owner-a", "customer-1", "MEMBER", "invite-1")
    store.invite("org-a", "owner-a", "customer-2", "READ_ONLY", "invite-2")
    with pytest.raises(MembershipConflict, match="No organisation seats"):
        store.invite("org-a", "owner-a", "customer-3", "MEMBER", "invite-3")


def test_invitation_acceptance_and_replay(membership_store):
    store = membership_store
    invitation = store.invite("org-a", "owner-a", "customer-1", "READ_ONLY", "invite-1")
    accepted = store.accept_invitation("org-a", invitation["invitation_id"], "customer-1")
    replay = store.accept_invitation("org-a", invitation["invitation_id"], "customer-1")
    assert accepted["role"] == "READ_ONLY"
    assert replay["idempotent_replay"] is True
    assert store.seat_usage("org-a", "owner-a")["reserved_seats"] == 2


def test_invitation_cannot_be_accepted_by_another_customer(membership_store):
    store = membership_store
    invitation = store.invite("org-a", "owner-a", "customer-1", "MEMBER", "invite-1")
    with pytest.raises(KeyError):
        store.accept_invitation("org-a", invitation["invitation_id"], "customer-2")


def test_member_role_change_and_last_owner_protection(membership_store):
    store = membership_store
    invitation = store.invite("org-a", "owner-a", "customer-1", "MEMBER", "invite-1")
    store.accept_invitation("org-a", invitation["invitation_id"], "customer-1")
    changed = store.change_role("org-a", "owner-a", "customer-1", "ADMIN", "role-1")
    assert changed["role"] == "ADMIN"
    with pytest.raises(MembershipConflict, match="last organisation owner"):
        store.change_role("org-a", "owner-a", "owner-a", "MEMBER", "role-2")


def test_admin_cannot_promote_or_remove_another_admin(membership_store):
    store = membership_store
    invitation = store.invite("org-a", "owner-a", "customer-1", "ADMIN", "invite-1")
    store.accept_invitation("org-a", invitation["invitation_id"], "customer-1")
    with pytest.raises(PermissionError):
        store.change_role("org-a", "customer-1", "owner-a", "MEMBER", "role-1")


def test_tenant_membership_and_invitation_data_are_scoped(membership_store):
    store = membership_store
    store.invite("org-a", "owner-a", "customer-1", "MEMBER", "invite-1")
    assert [m["customer_id"] for m in store.list_members("org-b", "owner-b")] == ["owner-b"]
    assert store.list_invitations("org-b", "owner-b") == []


def test_revocation_releases_reserved_seat(membership_store):
    store = membership_store
    invitation = store.invite("org-a", "owner-a", "customer-1", "MEMBER", "invite-1")
    revoked = store.revoke_invitation("org-a", "owner-a", invitation["invitation_id"], "revoke-1")
    assert revoked["status"] == "REVOKED"
    assert store.seat_usage("org-a", "owner-a")["pending_invitations"] == 0


def test_invitation_role_cannot_assign_owner(membership_store):
    with pytest.raises(ValueError, match="OWNER is not assignable"):
        membership_store.invite("org-a", "owner-a", "customer-1", "OWNER", "invite-1")



def test_customer_can_discover_multiple_active_organisations(membership_store):
    store = membership_store
    with store._scope(), store.engine.begin() as conn:
        conn.execute(text("""INSERT INTO air_tenant_members(tenant_id,customer_id,role,status)
            VALUES('org-b','owner-a','ADMIN','ACTIVE')"""))
    organisations = store.list_customer_organisations("owner-a")
    assert [row["tenant_id"] for row in organisations] == ["org-a", "org-b"]
    assert organisations[1]["role"] == "ADMIN"


def test_customer_invitation_inbox_only_returns_their_live_pending_invites(membership_store):
    store = membership_store
    invitation = store.invite("org-a", "owner-a", "customer-1", "READ_ONLY", "invite-1")
    inbox = store.list_customer_invitations("customer-1")
    assert len(inbox) == 1
    assert inbox[0]["invitation_id"] == invitation["invitation_id"]
    assert inbox[0]["organisation_name"] == "Organisation A"
    assert store.list_customer_invitations("customer-2") == []
