"""Best-effort domain event bridge into the durable AIR workflow outbox."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.workflow_engine import WorkflowStore

log = logging.getLogger("air.workflow.events")


def build_idempotency_key(prefix: str, *parts: Any) -> str:
    """Create a bounded, stable key even when broker/customer identifiers are long."""
    material = "\\x1f".join(str(part or "") for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{str(prefix)[:120]}:{digest}"


def emit_workflow_event(
    *, event_type: str, source: str, payload: dict[str, Any],
    idempotency_key: str, correlation_id: str | None = None,
) -> dict[str, Any]:
    """Persist a domain event and outbox row without coupling domain APIs to RabbitMQ."""
    store = None
    try:
        store = WorkflowStore()
        return store.publish_event(
            event_type=event_type, source=source, payload=payload,
            idempotency_key=idempotency_key, correlation_id=correlation_id,
        )
    except Exception as exc:  # research domain actions must not fail due to workflow transport
        log.exception("Could not persist AIR workflow event %s (%s)", event_type, type(exc).__name__)
        return {"status": "deferred", "event_type": event_type, "error": type(exc).__name__}
    finally:
        if store is not None:
            store.close()
