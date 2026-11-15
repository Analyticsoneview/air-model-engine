"""Administrator API for AIR workflow definitions, events and run history."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import require_admin
from app.workflow_engine import WorkflowStore

router = APIRouter(prefix="/api/v1/admin/workflows", tags=["AIR Workflow Engine"])


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    trigger_type: str
    trigger_config: dict = Field(default_factory=dict)
    workflow_spec: dict = Field(default_factory=dict)
    execution_mode: str = "RESEARCH_ONLY"


class WorkflowUpdate(WorkflowCreate):
    pass


class ExchangeCalendarDay(BaseModel):
    status: str = Field(pattern="^(HOLIDAY|SPECIAL_SESSION|TRADING_DAY)$")
    description: str = Field(default="", max_length=240)
    session_open: str | None = Field(default=None, max_length=5)
    session_close: str | None = Field(default=None, max_length=5)
    source: str = Field(default="ADMIN", min_length=1, max_length=240)


class EventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=200)
    payload: dict = Field(default_factory=dict)
    occurred_at: str | None = None
    correlation_id: str | None = None


def _management_admin(admin: dict) -> dict:
    if admin["role"] not in {"SUPER_ADMIN", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Workflow management permission is required")
    return admin


@router.get("")
async def list_workflows(limit: int = 100, admin: dict = Depends(require_admin)):
    store = WorkflowStore()
    try:
        return {"workflows": store.list_workflows(limit=limit)}
    finally:
        store.close()


@router.post("")
async def create_workflow(body: WorkflowCreate, admin: dict = Depends(require_admin)):
    _management_admin(admin)
    store = WorkflowStore()
    try:
        try:
            return store.create_workflow(
                name=body.name, description=body.description, created_by=admin["admin_id"],
                trigger_type=body.trigger_type, trigger_config=body.trigger_config,
                workflow_spec=body.workflow_spec, execution_mode=body.execution_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        store.close()


@router.put("/{workflow_id}")
async def update_workflow(workflow_id: str, body: WorkflowUpdate, admin: dict = Depends(require_admin)):
    _management_admin(admin)
    store = WorkflowStore()
    try:
        try:
            workflow = store.update_workflow(
                workflow_id, name=body.name, description=body.description,
                trigger_type=body.trigger_type, trigger_config=body.trigger_config,
                workflow_spec=body.workflow_spec, execution_mode=body.execution_mode,
                updated_by=admin["admin_id"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return workflow
    finally:
        store.close()


@router.get("/{workflow_id}/versions")
async def list_workflow_versions(workflow_id: str, admin: dict = Depends(require_admin)):
    store = WorkflowStore()
    try:
        if store.get_workflow(workflow_id) is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"workflow_id": workflow_id, "versions": store.list_workflow_versions(workflow_id)}
    finally:
        store.close()


@router.post("/{workflow_id}/enabled")
async def set_workflow_enabled(workflow_id: str, enabled: bool, admin: dict = Depends(require_admin)):
    _management_admin(admin)
    store = WorkflowStore()
    try:
        workflow = store.set_workflow_enabled(workflow_id, enabled, actor_id=admin["admin_id"])
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return workflow
    finally:
        store.close()



@router.get("/runtime")
async def workflow_runtime_status(admin: dict = Depends(require_admin)):
    store = WorkflowStore()
    try:
        now = datetime.now(timezone.utc)
        workers = []
        for worker in store.list_worker_heartbeats(100):
            try:
                seen = datetime.fromisoformat(worker["last_seen"].replace("Z", "+00:00"))
                age = max(0.0, (now - seen).total_seconds())
            except (TypeError, ValueError):
                age = None
            live = age is not None and age <= 45 and worker["status"] == "RUNNING"
            workers.append({
                **worker, "age_seconds": round(age, 1) if age is not None else None,
                "healthy": live,
            })
        healthy = any(item["healthy"] for item in workers)
        status = "HEALTHY" if healthy else "DEGRADED" if workers else "NOT_SEEN"
        return {
            "status": status,
            "heartbeat_stale_after_seconds": 45,
            "workers": workers,
            "metrics": store.runtime_metrics(),
        }
    finally:
        store.close()


@router.get("/runs")
async def list_workflow_runs(limit: int = 100, admin: dict = Depends(require_admin)):
    store = WorkflowStore()
    try:
        return {"runs": store.list_runs(limit)}
    finally:
        store.close()



@router.get("/runs/{run_id}/steps")
async def list_workflow_run_steps(run_id: str, admin: dict = Depends(require_admin)):
    store = WorkflowStore()
    try:
        if store.run_context(run_id) is None:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        return {"run_id": run_id, "steps": store.list_run_steps(run_id)}
    finally:
        store.close()


@router.get("/audit")
async def list_workflow_audit(workflow_id: str | None = None, limit: int = 100,
                              admin: dict = Depends(require_admin)):
    store = WorkflowStore()
    try:
        return {"audit": store.list_workflow_audit(workflow_id=workflow_id, limit=limit)}
    finally:
        store.close()


@router.get("/calendar")
async def list_exchange_calendar(exchange_code: str = "NSE", start_date: str = "2026-01-01",
                                 end_date: str = "2027-12-31", admin: dict = Depends(require_admin)):
    store = WorkflowStore()
    try:
        try:
            return {"exchange_code": exchange_code.upper(),
                    "sessions": store.list_exchange_calendar(exchange_code, start_date, end_date)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        store.close()


@router.put("/calendar/{exchange_code}/{session_date}")
async def set_exchange_calendar_day(exchange_code: str, session_date: str, body: ExchangeCalendarDay,
                                    admin: dict = Depends(require_admin)):
    _management_admin(admin)
    store = WorkflowStore()
    try:
        try:
            return {"session": store.set_exchange_calendar_day(
                exchange_code=exchange_code, session_date=session_date, status=body.status,
                description=body.description, session_open=body.session_open,
                session_close=body.session_close, source=body.source,
                updated_by=admin["admin_id"],
            )}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        store.close()


@router.post("/events")
async def publish_workflow_event(body: EventCreate, admin: dict = Depends(require_admin)):
    _management_admin(admin)
    store = WorkflowStore()
    try:
        try:
            return store.publish_event(
                event_type=body.event_type, source=body.source, payload=body.payload,
                idempotency_key=body.idempotency_key, occurred_at=body.occurred_at,
                correlation_id=body.correlation_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        store.close()
