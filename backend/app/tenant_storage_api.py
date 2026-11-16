"""Authenticated tenant object storage API for AWS SaaS deployments.

Objects are immutable by key. PostgreSQL reserves quota before S3 writes, so
concurrent uploads cannot oversubscribe a tenant's storage allowance.
"""
from __future__ import annotations

import hashlib
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from app.security import require_customer
from app.tenant_context import current_customer_id, current_tenant_id

router = APIRouter()


def _services():
    # Resolve lazily to avoid a module-import cycle with app.main.
    from app.main import _get_aws_tenant_provisioner, _get_tenant_registry
    return _get_tenant_registry(), _get_aws_tenant_provisioner


def _context() -> tuple[dict, str, str]:
    if os.getenv("AIR_DEPLOYMENT_PROFILE", "onprem-single") != "aws-saas-multi":
        raise HTTPException(status_code=409, detail="Tenant object storage is available only in aws-saas-multi")
    tenant_id, customer_id = current_tenant_id(), current_customer_id()
    if not tenant_id or not customer_id:
        raise HTTPException(status_code=403, detail="Active tenant context is required")
    registry, _ = _services()
    try:
        tenant = registry.get_customer_context(customer_id)
    except KeyError as exc:
        raise HTTPException(status_code=403, detail="Customer tenant membership is not active") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Tenant storage registry is unavailable") from exc
    if str(tenant.get("tenant_id", "")) != str(tenant_id) or tenant.get("tenant_status") != "ACTIVE":
        raise HTTPException(status_code=403, detail="Authenticated tenant context does not match active membership")
    return tenant, tenant_id, customer_id


def _max_upload() -> int:
    try:
        configured = int(os.getenv("AIR_TENANT_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Tenant upload limit configuration is invalid") from exc
    if configured < 1:
        raise HTTPException(status_code=503, detail="Tenant upload limit must be positive")
    return min(configured, 25 * 1024 * 1024)


@router.get("/api/v1/tenant/objects")
async def list_tenant_objects(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    customer_id: str = Depends(require_customer),
) -> dict:
    tenant, tenant_id, owner = _context()
    registry, _ = _services()
    try:
        rows = registry.list_tenant_objects(tenant_id, owner, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Tenant object metadata is unavailable") from exc
    return {
        "objects": rows, "count": len(rows),
        "storage_used_bytes": int(tenant.get("storage_used_bytes", 0)),
        "max_storage_bytes": int(tenant["max_storage_bytes"]),
    }


@router.put("/api/v1/tenant/objects/{object_key:path}")
async def upload_tenant_object(
    object_key: str,
    request: Request,
    customer_id: str = Depends(require_customer),
) -> dict:
    tenant, tenant_id, owner = _context()
    if tenant.get("role") not in {"OWNER", "ADMIN", "MEMBER"}:
        raise HTTPException(status_code=403, detail="Tenant membership is read-only")
    maximum = _max_upload()
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > maximum:
                raise HTTPException(status_code=413, detail="Tenant object exceeds the configured upload limit")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc

    digest = hashlib.sha256()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > maximum:
            raise HTTPException(status_code=413, detail="Tenant object exceeds the configured upload limit")
        digest.update(chunk)
        chunks.append(chunk)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty tenant object uploads are not supported")
    body = b"".join(chunks)
    sha256 = digest.hexdigest()
    content_type = request.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower()
    registry, get_provisioner = _services()
    try:
        reservation = registry.reserve_object_upload(
            tenant_id, owner, object_key, size_bytes=size,
            sha256=sha256, content_type=content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=409, detail="Tenant storage quota would be exceeded") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Tenant storage quota registry is unavailable") from exc

    if reservation.get("already_stored"):
        return {"status": "already_stored", "object": reservation}

    try:
        uploaded = get_provisioner().put_tenant_object(
            tenant, object_key, body, content_type=content_type,
            sha256=sha256, quota_prevalidated=True,
        )
        metadata = registry.complete_object_upload(
            tenant_id, owner, object_key, uploaded.get("etag", ""),
        )
    except Exception as exc:
        # A PENDING reservation is deliberately retained after an ambiguous
        # S3/network failure. Repeating the same key and digest safely resumes.
        raise HTTPException(
            status_code=502,
            detail="Tenant object upload could not be confirmed; retry the same key and content to resume",
        ) from exc
    return {
        "status": "stored", "object": metadata,
        "storage_used_bytes": reservation["storage_used_bytes"],
        "max_storage_bytes": reservation["max_storage_bytes"],
        "resumed": bool(reservation.get("resume_pending")),
    }


@router.get("/api/v1/tenant/objects/{object_key:path}")
async def download_tenant_object(
    object_key: str,
    customer_id: str = Depends(require_customer),
) -> Response:
    tenant, tenant_id, owner = _context()
    registry, get_provisioner = _services()
    try:
        metadata = registry.get_tenant_object(tenant_id, owner, object_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tenant object does not exist") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Tenant object metadata is unavailable") from exc
    try:
        result = get_provisioner().get_tenant_object(tenant, object_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tenant object does not exist") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Tenant object storage is unavailable") from exc
    body = result.get("body")
    if not isinstance(body, bytes):
        raise HTTPException(status_code=502, detail="Tenant object integrity verification failed")
    if (
        len(body) != int(metadata["size_bytes"])
        or not hashlib.compare_digest(hashlib.sha256(body).hexdigest(), str(metadata["sha256"]))
    ):
        raise HTTPException(status_code=502, detail="Tenant object integrity verification failed")
    return Response(
        content=body,
        media_type=metadata["content_type"],
        headers={
            "Content-Length": str(metadata["size_bytes"]),
            "ETag": f'"{metadata.get("etag") or result.get("etag", "")}"',
            "X-AIR-Content-SHA256": metadata["sha256"],
            "Content-Disposition": "attachment",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
