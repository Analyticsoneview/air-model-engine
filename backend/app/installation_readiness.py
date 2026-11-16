"""Pure readiness checks for the AIR workflow runtime."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def evaluate_workflow_runtime(
    workers: list[dict[str, Any]], now: datetime | None = None,
    stale_after_seconds: int = 45,
) -> dict[str, Any]:
    """Require a fresh heartbeat, a live RabbitMQ connection and live runtime threads."""
    now = now or datetime.now(timezone.utc)
    evaluated = []
    for worker in workers:
        details = worker.get("details") or {}
        components = details.get("components") or {}
        try:
            seen = datetime.fromisoformat(str(worker["last_seen"]).replace("Z", "+00:00"))
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            age = max(0.0, (now - seen.astimezone(timezone.utc)).total_seconds())
        except (KeyError, TypeError, ValueError):
            age = None
        connected = details.get("rabbitmq_connected") is True
        threads_live = bool(components) and all(value is True for value in components.values())
        healthy = (
            worker.get("status") == "RUNNING"
            and age is not None and age <= stale_after_seconds
            and connected and threads_live
        )
        evaluated.append({
            "worker_id": worker.get("worker_id"),
            "component": worker.get("component"),
            "status": worker.get("status"),
            "age_seconds": round(age, 1) if age is not None else None,
            "rabbitmq_connected": connected,
            "components": components,
            "healthy": healthy,
        })
    healthy = any(item["healthy"] for item in evaluated)
    return {
        "status": "HEALTHY" if healthy else "DEGRADED" if evaluated else "NOT_SEEN",
        "healthy": healthy,
        "heartbeat_stale_after_seconds": stale_after_seconds,
        "workers": evaluated,
    }
