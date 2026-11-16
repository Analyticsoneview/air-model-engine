"""Tenant-scoped organisation membership, seat governance and invitation lifecycle."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text

ROLES = {"OWNER", "ADMIN", "MEMBER", "READ_ONLY"}
ASSIGNABLE_ROLES = {"ADMIN", "MEMBER", "READ_ONLY"}


class MembershipConflict(ValueError):
    """A membership, invitation or seat transition conflicts with current state."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TenantMembershipStore:
    """Transactional organisation membership operations over the tenant registry engine.

    The store uses an elevated database context only inside these methods. Every
    operation then applies explicit tenant and actor predicates before mutation;
    request callers never receive a database connection or arbitrary tenant scope.
    """

    def __init__(self, engine):
        self.engine = engine
        from app.tenant_context import install_tenant_context
        install_tenant_context(engine)

    @staticmethod
    def _scope():
        from app.tenant_context import tenant_scope
        return tenant_scope(is_admin=True)

    def _actor(self, conn, tenant_id: str, actor_id: str, *, manage: bool = False) -> dict:
        row = conn.execute(text("""SELECT m.role,m.status,t.status AS tenant_status
            FROM air_tenant_members m
            JOIN air_tenants t ON t.tenant_id=m.tenant_id
            WHERE m.tenant_id=:tenant AND m.customer_id=:actor"""),
            {"tenant": tenant_id, "actor": actor_id}).mappings().first()
        if not row or row["status"] != "ACTIVE" or row["tenant_status"] != "ACTIVE":
            raise PermissionError("An active organisation membership is required")
        if manage and row["role"] not in {"OWNER", "ADMIN"}:
            raise PermissionError("Organisation owner or administrator permission is required")
        return dict(row)

    def _lock_tenant(self, conn, tenant_id: str) -> dict:
        suffix = " FOR UPDATE" if self.engine.dialect.name == "postgresql" else ""
        row = conn.execute(text(
            "SELECT status,max_members FROM air_tenants WHERE tenant_id=:tenant" + suffix
        ), {"tenant": tenant_id}).mappings().first()
        if not row or row["status"] != "ACTIVE":
            raise MembershipConflict("Organisation must be ACTIVE")
        return dict(row)

    @staticmethod
    def _key(value: str) -> str:
        key = str(value or "").strip()
        if not key or len(key) > 200:
            raise ValueError("An idempotency key of 1-200 characters is required")
        return key

    def _event(self, conn, tenant_id, customer_id, actor_id, event_type,
               from_role, to_role, idempotency_key, details=None):
        conn.execute(text("""INSERT INTO air_tenant_membership_events
            (event_id,tenant_id,customer_id,actor_id,event_type,from_role,to_role,
             idempotency_key,details,occurred_at)
            VALUES(:id,:tenant,:customer,:actor,:kind,:old,:new,:key,:details,:now)"""),
            {"id": str(uuid4()), "tenant": tenant_id, "customer": customer_id,
             "actor": actor_id, "kind": event_type, "old": from_role, "new": to_role,
             "key": idempotency_key, "details": json.dumps(details or {}, sort_keys=True),
             "now": _now()})

    def seat_usage(self, tenant_id: str, actor_id: str) -> dict:
        with self._scope(), self.engine.connect() as conn:
            self._actor(conn, tenant_id, actor_id)
            tenant = conn.execute(text("SELECT max_members FROM air_tenants WHERE tenant_id=:tenant"),
                                  {"tenant": tenant_id}).first()
            active = conn.execute(text("""SELECT COUNT(*) FROM air_tenant_members
                WHERE tenant_id=:tenant AND status='ACTIVE'"""), {"tenant": tenant_id}).scalar_one()
            pending = conn.execute(text("""SELECT COUNT(*) FROM air_tenant_invitations
                WHERE tenant_id=:tenant AND status='PENDING' AND expires_at>:now"""),
                {"tenant": tenant_id, "now": _now()}).scalar_one()
        maximum = int(tenant[0])
        reserved = int(active) + int(pending)
        return {"tenant_id": tenant_id, "active_members": int(active),
                "pending_invitations": int(pending), "reserved_seats": reserved,
                "max_members": maximum, "available_seats": max(0, maximum - reserved)}

    def list_members(self, tenant_id: str, actor_id: str) -> list[dict]:
        with self._scope(), self.engine.connect() as conn:
            self._actor(conn, tenant_id, actor_id)
            rows = conn.execute(text("""SELECT customer_id,role,status,joined_at
                FROM air_tenant_members WHERE tenant_id=:tenant AND status IN ('ACTIVE','SUSPENDED')
                ORDER BY CASE role WHEN 'OWNER' THEN 0 WHEN 'ADMIN' THEN 1 ELSE 2 END,
                         joined_at,customer_id"""), {"tenant": tenant_id}).mappings().all()
        return [dict(row) for row in rows]

    def list_invitations(self, tenant_id: str, actor_id: str) -> list[dict]:
        with self._scope(), self.engine.connect() as conn:
            self._actor(conn, tenant_id, actor_id, manage=True)
            rows = conn.execute(text("""SELECT invitation_id,invited_customer_id,role,status,
                invited_by,created_at,expires_at,accepted_at,revoked_at
                FROM air_tenant_invitations WHERE tenant_id=:tenant
                ORDER BY created_at DESC LIMIT 500"""), {"tenant": tenant_id}).mappings().all()
        return [dict(row) for row in rows]

    def invite(self, tenant_id: str, actor_id: str, invitee_id: str,
               role: str, idempotency_key: str) -> dict:
        invitee = str(invitee_id or "").strip()
        role = str(role or "").upper()
        key = self._key(idempotency_key)
        if not invitee or len(invitee) > 128 or invitee == actor_id:
            raise ValueError("A different valid customer identity is required")
        if role not in ASSIGNABLE_ROLES:
            raise ValueError("Invitations may assign ADMIN, MEMBER or READ_ONLY; OWNER is not assignable")
        now = _now()
        with self._scope(), self.engine.begin() as conn:
            tenant = self._lock_tenant(conn, tenant_id)
            self._actor(conn, tenant_id, actor_id, manage=True)
            prior = conn.execute(text("""SELECT invitation_id,invited_customer_id,role,status
                FROM air_tenant_invitations WHERE tenant_id=:tenant AND idempotency_key=:key"""),
                {"tenant": tenant_id, "key": key}).first()
            if prior:
                if prior[1] != invitee or prior[2] != role:
                    raise MembershipConflict("Invitation idempotency key was reused with different content")
                return {"invitation_id": prior[0], "tenant_id": tenant_id,
                        "invited_customer_id": invitee, "role": role, "status": prior[3],
                        "idempotent_replay": True}
            conn.execute(text("""UPDATE air_tenant_invitations SET status='EXPIRED'
                WHERE tenant_id=:tenant AND status='PENDING' AND expires_at<=:now"""),
                {"tenant": tenant_id, "now": now})
            existing = conn.execute(text("""SELECT status FROM air_tenant_members
                WHERE tenant_id=:tenant AND customer_id=:customer
                  AND status IN ('ACTIVE','INVITED','SUSPENDED')"""),
                {"tenant": tenant_id, "customer": invitee}).first()
            if existing:
                raise MembershipConflict("Customer already has an organisation membership")
            pending_existing = conn.execute(text("""SELECT 1 FROM air_tenant_invitations
                WHERE tenant_id=:tenant AND invited_customer_id=:customer
                  AND status='PENDING' AND expires_at>:now"""),
                {"tenant": tenant_id, "customer": invitee, "now": now}).first()
            if pending_existing:
                raise MembershipConflict("A pending invitation already exists for this customer")
            active = conn.execute(text("""SELECT COUNT(*) FROM air_tenant_members
                WHERE tenant_id=:tenant AND status='ACTIVE'"""), {"tenant": tenant_id}).scalar_one()
            pending = conn.execute(text("""SELECT COUNT(*) FROM air_tenant_invitations
                WHERE tenant_id=:tenant AND status='PENDING' AND expires_at>:now"""),
                {"tenant": tenant_id, "now": now}).scalar_one()
            if int(active) + int(pending) >= int(tenant["max_members"]):
                raise MembershipConflict("No organisation seats are available")
            invitation_id = str(uuid4())
            expires = now + timedelta(days=7)
            conn.execute(text("""INSERT INTO air_tenant_invitations
                (invitation_id,tenant_id,invited_customer_id,role,invited_by,status,
                 idempotency_key,created_at,expires_at)
                VALUES(:id,:tenant,:customer,:role,:actor,'PENDING',:key,:now,:expires)"""),
                {"id": invitation_id, "tenant": tenant_id, "customer": invitee, "role": role,
                 "actor": actor_id, "key": key, "now": now, "expires": expires})
            self._event(conn, tenant_id, invitee, actor_id, "INVITED", None, role,
                        "invite:" + key, {"invitation_id": invitation_id})
        return {"invitation_id": invitation_id, "tenant_id": tenant_id,
                "invited_customer_id": invitee, "role": role, "status": "PENDING",
                "expires_at": expires, "idempotent_replay": False}

    def accept_invitation(self, tenant_id: str, invitation_id: str, customer_id: str) -> dict:
        with self._scope(), self.engine.begin() as conn:
            row = conn.execute(text("""SELECT * FROM air_tenant_invitations
                WHERE tenant_id=:tenant AND invitation_id=:id"""),
                {"tenant": tenant_id, "id": invitation_id}).mappings().first()
            if not row or row["invited_customer_id"] != customer_id:
                raise KeyError("Invitation not found for this customer")
            if row["status"] == "ACCEPTED":
                member = conn.execute(text("""SELECT tenant_id,customer_id,role,status
                    FROM air_tenant_members WHERE tenant_id=:tenant AND customer_id=:customer"""),
                    {"tenant": tenant_id, "customer": customer_id}).mappings().first()
                if member and member["status"] == "ACTIVE":
                    return dict(member) | {"idempotent_replay": True}
                raise MembershipConflict("Accepted invitation no longer has an active membership")
            if row["status"] != "PENDING":
                raise MembershipConflict("Invitation is no longer pending")
            now = _now()
            if row["expires_at"] <= now:
                conn.execute(text("""UPDATE air_tenant_invitations SET status='EXPIRED'
                    WHERE tenant_id=:tenant AND invitation_id=:id"""),
                    {"tenant": tenant_id, "id": invitation_id})
                raise MembershipConflict("Invitation has expired")
            self._lock_tenant(conn, tenant_id)
            existing = conn.execute(text("""SELECT status FROM air_tenant_members
                WHERE tenant_id=:tenant AND customer_id=:customer"""),
                {"tenant": tenant_id, "customer": customer_id}).first()
            if existing and existing[0] != "REMOVED":
                raise MembershipConflict("Customer already belongs to this organisation")
            if existing:
                conn.execute(text("""DELETE FROM air_tenant_members
                    WHERE tenant_id=:tenant AND customer_id=:customer"""),
                    {"tenant": tenant_id, "customer": customer_id})
            conn.execute(text("""INSERT INTO air_tenant_members
                (tenant_id,customer_id,role,status)
                VALUES(:tenant,:customer,:role,'ACTIVE')"""),
                {"tenant": tenant_id, "customer": customer_id, "role": row["role"]})
            conn.execute(text("""UPDATE air_tenant_invitations SET status='ACCEPTED',accepted_at=:now
                WHERE tenant_id=:tenant AND invitation_id=:id"""),
                {"now": now, "tenant": tenant_id, "id": invitation_id})
            self._event(conn, tenant_id, customer_id, customer_id, "INVITATION_ACCEPTED",
                        None, row["role"], "accept:" + invitation_id, {"invitation_id": invitation_id})
        return {"tenant_id": tenant_id, "customer_id": customer_id, "role": row["role"],
                "status": "ACTIVE", "idempotent_replay": False}

    def revoke_invitation(self, tenant_id: str, actor_id: str, invitation_id: str,
                          idempotency_key: str) -> dict:
        key = self._key(idempotency_key)
        with self._scope(), self.engine.begin() as conn:
            self._actor(conn, tenant_id, actor_id, manage=True)
            row = conn.execute(text("""SELECT invited_customer_id,role,status
                FROM air_tenant_invitations WHERE tenant_id=:tenant AND invitation_id=:id"""),
                {"tenant": tenant_id, "id": invitation_id}).first()
            if not row:
                raise KeyError("Invitation not found")
            prior = conn.execute(text("""SELECT customer_id,event_type,details
                FROM air_tenant_membership_events WHERE tenant_id=:tenant AND idempotency_key=:key"""),
                {"tenant": tenant_id, "key": key}).first()
            if prior:
                details = prior[2] if isinstance(prior[2], dict) else json.loads(prior[2] or "{}")
                if prior[0] != row[0] or prior[1] != "INVITATION_REVOKED" or details.get("invitation_id") != invitation_id:
                    raise MembershipConflict("Invitation idempotency key was reused with different content")
                return {"invitation_id": invitation_id, "status": "REVOKED", "idempotent_replay": True}
            if row[2] != "PENDING":
                raise MembershipConflict("Only pending invitations can be revoked")
            now = _now()
            conn.execute(text("""UPDATE air_tenant_invitations SET status='REVOKED',revoked_at=:now
                WHERE tenant_id=:tenant AND invitation_id=:id"""),
                {"now": now, "tenant": tenant_id, "id": invitation_id})
            self._event(conn, tenant_id, row[0], actor_id, "INVITATION_REVOKED",
                        None, row[1], key, {"invitation_id": invitation_id})
        return {"invitation_id": invitation_id, "status": "REVOKED", "idempotent_replay": False}

    def change_role(self, tenant_id: str, actor_id: str, customer_id: str,
                    new_role: str, idempotency_key: str) -> dict:
        role, key = str(new_role or "").upper(), self._key(idempotency_key)
        if role not in ROLES:
            raise ValueError("Unsupported organisation role")
        with self._scope(), self.engine.begin() as conn:
            actor = self._actor(conn, tenant_id, actor_id, manage=True)
            row = conn.execute(text("""SELECT role,status FROM air_tenant_members
                WHERE tenant_id=:tenant AND customer_id=:customer"""),
                {"tenant": tenant_id, "customer": customer_id}).first()
            if not row or row[1] != "ACTIVE":
                raise KeyError("Active organisation member not found")
            if actor["role"] != "OWNER" and (row[0] in {"OWNER", "ADMIN"} or role in {"OWNER", "ADMIN"}):
                raise PermissionError("Only an organisation owner can change owner or administrator roles")
            if row[0] == "OWNER" and role != "OWNER":
                owners = conn.execute(text("""SELECT COUNT(*) FROM air_tenant_members
                    WHERE tenant_id=:tenant AND role='OWNER' AND status='ACTIVE'"""),
                    {"tenant": tenant_id}).scalar_one()
                if int(owners) <= 1:
                    raise MembershipConflict("The last organisation owner cannot be demoted")
            prior = conn.execute(text("""SELECT customer_id,to_role FROM air_tenant_membership_events
                WHERE tenant_id=:tenant AND idempotency_key=:key"""),
                {"tenant": tenant_id, "key": key}).first()
            if prior:
                if prior[0] != customer_id or prior[1] != role:
                    raise MembershipConflict("Role idempotency key was reused with different content")
                return {"tenant_id": tenant_id, "customer_id": customer_id, "role": role,
                        "status": "ACTIVE", "idempotent_replay": True}
            conn.execute(text("""UPDATE air_tenant_members SET role=:role
                WHERE tenant_id=:tenant AND customer_id=:customer"""),
                {"role": role, "tenant": tenant_id, "customer": customer_id})
            self._event(conn, tenant_id, customer_id, actor_id, "ROLE_CHANGED",
                        row[0], role, key, {})
        return {"tenant_id": tenant_id, "customer_id": customer_id, "role": role,
                "status": "ACTIVE", "idempotent_replay": False}

    def remove_member(self, tenant_id: str, actor_id: str, customer_id: str,
                      idempotency_key: str) -> dict:
        key = self._key(idempotency_key)
        with self._scope(), self.engine.begin() as conn:
            actor = self._actor(conn, tenant_id, actor_id, manage=True)
            row = conn.execute(text("""SELECT role,status FROM air_tenant_members
                WHERE tenant_id=:tenant AND customer_id=:customer"""),
                {"tenant": tenant_id, "customer": customer_id}).first()
            if not row:
                raise KeyError("Organisation member not found")
            if row[0] == "OWNER":
                raise MembershipConflict("Transfer ownership before removing an organisation owner")
            if row[0] == "ADMIN" and actor["role"] != "OWNER":
                raise PermissionError("Only an organisation owner can remove another administrator")
            prior = conn.execute(text("""SELECT customer_id,event_type
                FROM air_tenant_membership_events WHERE tenant_id=:tenant AND idempotency_key=:key"""),
                {"tenant": tenant_id, "key": key}).first()
            if prior:
                if prior[0] != customer_id or prior[1] != "MEMBER_REMOVED":
                    raise MembershipConflict("Membership idempotency key was reused with different content")
                return {"tenant_id": tenant_id, "customer_id": customer_id,
                        "status": "REMOVED", "idempotent_replay": True}
            if row[1] == "REMOVED":
                raise MembershipConflict("Organisation member has already been removed")
            conn.execute(text("""UPDATE air_tenant_members SET status='REMOVED'
                WHERE tenant_id=:tenant AND customer_id=:customer"""),
                {"tenant": tenant_id, "customer": customer_id})
            self._event(conn, tenant_id, customer_id, actor_id, "MEMBER_REMOVED",
                        row[0], None, key, {})
        return {"tenant_id": tenant_id, "customer_id": customer_id,
                "status": "REMOVED", "idempotent_replay": False}
