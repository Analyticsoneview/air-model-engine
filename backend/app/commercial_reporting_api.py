"""Restricted operator endpoints for Gate 17F-9 commercial reporting."""
from __future__ import annotations

from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException

from app.security import require_admin
from app.commercial_reporting import CommercialReportingStore

router = APIRouter(prefix="/api/v1/commercial/reporting", tags=["commercial-reporting"])


@lru_cache(maxsize=1)
def _store():
    return CommercialReportingStore()


def _require_commercial_admin(admin: dict = Depends(require_admin)):
    if admin.get("role") not in {"SUPER_ADMIN", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Commercial reporting requires administrator permission")
    return admin


@router.get("/overview")
def overview(admin: dict = Depends(_require_commercial_admin)):
    try:
        return _store().report()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Commercial reporting ledger is unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Commercial reporting query failed") from exc
