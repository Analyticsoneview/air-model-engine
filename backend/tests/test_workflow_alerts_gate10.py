from datetime import datetime, timedelta, timezone

from app import workflow_alerts


class FakeStore:
    def runtime_metrics(self):
        return {
            "outbox": {"pending": 125, "published": 20, "failed": 2},
            "runs": {"queued": 0, "running": 0, "succeeded": 0, "failed": 0, "cancelled": 0},
            "steps": {"pending": 0, "running": 0, "succeeded": 0, "failed": 0, "skipped": 0},
        }

    def list_worker_heartbeats(self, limit):
        return [
            {
                "worker_id": "worker-stale", "component": "workflow-runtime",
                "status": "RUNNING",
                "last_seen": (datetime(2025, 12, 31, 23, 58, tzinfo=timezone.utc)).isoformat(),
            },
            {
                "worker_id": "worker-degraded", "component": "workflow-runtime",
                "status": "DEGRADED",
                "last_seen": datetime.now(timezone.utc).isoformat(),
            },
            {
                "worker_id": "worker-stopping", "component": "workflow-runtime",
                "status": "STOPPING",
                "last_seen": datetime.now(timezone.utc).isoformat(),
            },
        ]


def test_runtime_alerts_cover_backlog_retry_exhaustion_dead_letter_and_worker_health(monkeypatch):
    monkeypatch.setenv("AIR_WORKFLOW_ALERT_BACKLOG_THRESHOLD", "100")
    alerts = workflow_alerts.evaluate_runtime_alerts(
        FakeStore(), dispatch_depth=150, dead_letter_depth=3,
        now=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
    )
    keys = {item["key"] for item in alerts}
    assert keys == {
        "outbox-backlog", "outbox-retry-exhaustion", "dispatch-backlog",
        "dead-letter-depth", "worker-unhealthy:worker-degraded",
    }


def test_runtime_alert_delivery_is_deduplicated_per_destination_and_retries_failures(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("AIR_WORKFLOW_ALERT_DEDUPE_DB_PATH", str(tmp_path / "alerts.sqlite3"))
    monkeypatch.setattr("app.telegram_notifications._chat_ids", lambda strategy, customer: ["admin-a", "admin-b"])
    calls = []

    async def fake_send(message, destination_ids=None):
        chat_id = destination_ids[0]
        calls.append(chat_id)
        if chat_id == "admin-b" and calls.count("admin-b") == 1:
            return {"sent": 0, "failures": [{"chat_id": chat_id, "error": "temporary"}]}
        return {"sent": 1, "failures": []}

    monkeypatch.setattr("app.telegram_notifications.send_telegram_message", fake_send)
    alerts = [{"key": "dead-letter-depth", "title": "DLQ", "detail": "3 messages"}]

    first = workflow_alerts.deliver_runtime_alerts(alerts)
    second = workflow_alerts.deliver_runtime_alerts(alerts)

    assert first == {"attempted": 2, "sent": 1}
    assert second == {"attempted": 1, "sent": 1}
    assert calls == ["admin-a", "admin-b", "admin-b"]
