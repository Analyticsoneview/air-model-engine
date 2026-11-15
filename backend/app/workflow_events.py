"""Best-effort domain event bridge into the durable AIR workflow outbox."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.workflow_engine import WorkflowStore

log = logging.getLogger("air.workflow.events")


def build_idempotency_key(prefix: str, *parts: Any) -> str:
    """Create a bounded, stable key even when broker/customer identifiers are long."""
    material = "\x1f".join(str(part if part is not None else "") for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{str(prefix)[:120]}:{digest}"


def emit_workflow_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist a batch of events using one store connection; never couple domain APIs to RabbitMQ."""
    if not events:
        return []
    store = None
    results: list[dict[str, Any]] = []
    try:
        store = WorkflowStore()
        for event in events:
            try:
                results.append(store.publish_event(
                    event_type=event["event_type"], source=event["source"],
                    payload=event.get("payload") or {},
                    idempotency_key=event["idempotency_key"],
                    correlation_id=event.get("correlation_id"),
                    occurred_at=event.get("occurred_at"),
                ))
            except Exception as exc:
                log.exception("Could not persist AIR workflow event %s (%s)",
                              event.get("event_type"), type(exc).__name__)
                results.append({
                    "status": "deferred", "event_type": event.get("event_type"),
                    "error": type(exc).__name__,
                })
    except Exception as exc:
        log.exception("Could not open AIR workflow event store (%s)", type(exc).__name__)
        return [{
            "status": "deferred", "event_type": event.get("event_type"),
            "error": type(exc).__name__,
        } for event in events]
    finally:
        if store is not None:
            store.close()
    return results


def emit_workflow_event(
    *, event_type: str, source: str, payload: dict[str, Any],
    idempotency_key: str, correlation_id: str | None = None,
) -> dict[str, Any]:
    """Persist one domain event without coupling its producer to RabbitMQ."""
    return emit_workflow_events([{
        "event_type": event_type, "source": source, "payload": payload,
        "idempotency_key": idempotency_key, "correlation_id": correlation_id,
    }])[0]
