"""Authenticated organisation membership, invitation and seat management API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.security import require_customer
from app.tenant_context import current_customer_id

router = APIRouter()


class InvitationRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=128)
    role: str = Field(default="MEMBER", min_length=1, max_length=16)


class RoleRequest(BaseModel):
    role: str = Field(min_length=1, max_length=16)


def _store():
    from app.main import _get_tenant_registry
    from app.tenant_memberships import TenantMembershipStore
    registry = _get_tenant_registry()
    return TenantMembershipStore(registry.engine)


def _actor() -> str:
    actor = current_customer_id()
    if not actor:
        raise HTTPException(status_code=403, detail="Authenticated customer identity is unavailable")
    return actor


def _call(fn, *args, **kwargs):
    from app.tenant_memberships import MembershipConflict
    try:
        return fn(*args, **kwargs)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MembershipConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/v1/organisations")
async def customer_organisations(customer_id: str = Depends(require_customer)):
    store, actor = _store(), _actor()
    return {"organisations": _call(store.list_customer_organisations, actor)}


@router.get("/api/v1/organisations/invitations/me")
async def customer_organisation_invitations(customer_id: str = Depends(require_customer)):
    store, actor = _store(), _actor()
    return {"invitations": _call(store.list_customer_invitations, actor)}


@router.get("/api/v1/organisations/{tenant_id}/members")
async def organisation_members(tenant_id: str, customer_id: str = Depends(require_customer)):
    store, actor = _store(), _actor()
    return {"tenant_id": tenant_id, "members": _call(store.list_members, tenant_id, actor)}


@router.get("/api/v1/organisations/{tenant_id}/seats")
async def organisation_seats(tenant_id: str, customer_id: str = Depends(require_customer)):
    store, actor = _store(), _actor()
    return _call(store.seat_usage, tenant_id, actor)


@router.get("/api/v1/organisations/{tenant_id}/invitations")
async def organisation_invitations(tenant_id: str, customer_id: str = Depends(require_customer)):
    store, actor = _store(), _actor()
    return {"tenant_id": tenant_id, "invitations": _call(store.list_invitations, tenant_id, actor)}


@router.post("/api/v1/organisations/{tenant_id}/invitations", status_code=201)
async def invite_to_organisation(
    tenant_id: str, body: InvitationRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    customer_id: str = Depends(require_customer),
):
    store, actor = _store(), _actor()
    return _call(store.invite, tenant_id, actor, body.customer_id, body.role, idempotency_key)


@router.post("/api/v1/organisations/{tenant_id}/invitations/{invitation_id}/accept")
async def accept_organisation_invitation(
    tenant_id: str, invitation_id: str, customer_id: str = Depends(require_customer),
):
    store, actor = _store(), _actor()
    return _call(store.accept_invitation, tenant_id, invitation_id, actor)


@router.post("/api/v1/organisations/{tenant_id}/invitations/{invitation_id}/revoke")
async def revoke_organisation_invitation(
    tenant_id: str, invitation_id: str,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    customer_id: str = Depends(require_customer),
):
    store, actor = _store(), _actor()
    return _call(store.revoke_invitation, tenant_id, actor, invitation_id, idempotency_key)


@router.patch("/api/v1/organisations/{tenant_id}/members/{member_id}/role")
async def change_organisation_member_role(
    tenant_id: str, member_id: str, body: RoleRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    customer_id: str = Depends(require_customer),
):
    store, actor = _store(), _actor()
    return _call(store.change_role, tenant_id, actor, member_id, body.role, idempotency_key)


@router.delete("/api/v1/organisations/{tenant_id}/members/{member_id}")
async def remove_organisation_member(
    tenant_id: str, member_id: str,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    customer_id: str = Depends(require_customer),
):
    store, actor = _store(), _actor()
    return _call(store.remove_member, tenant_id, actor, member_id, idempotency_key)
