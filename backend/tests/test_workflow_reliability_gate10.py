import json

from app import workflow_worker


class RecordingStore:
    def __init__(self):
        self.published = []
        self.failed = []

    def mark_outbox_published(self, outbox_id):
        self.published.append(outbox_id)

    def mark_outbox_failed(self, outbox_id, attempts, error):
        self.failed.append((outbox_id, attempts, error))


class PartialFailureChannel:
    def __init__(self):
        self.calls = 0
        self.bodies = []

    def basic_publish(self, **kwargs):
        self.calls += 1
        self.bodies.append(json.loads(kwargs["body"].decode("utf-8")))
        if self.calls == 2:
            raise ConnectionError("simulated connection loss")
        return True


def test_outbox_batch_failure_does_not_reset_confirmed_events(monkeypatch):
    store = RecordingStore()
    channel = PartialFailureChannel()
    monkeypatch.setattr(workflow_worker.pika, "BasicProperties", lambda **kwargs: kwargs)

    items = [
        {"outbox_id": "out-1", "event_id": "event-1", "event_type": "test.one", "attempts": 0},
        {"outbox_id": "out-2", "event_id": "event-2", "event_type": "test.two", "attempts": 3},
        {"outbox_id": "out-3", "event_id": "event-3", "event_type": "test.three", "attempts": 1},
    ]

    workflow_worker._publish_batch(store, channel, items)

    assert store.published == ["out-1", "out-3"]
    assert store.failed == [("out-2", 3, "ConnectionError")]
    assert [body["event_id"] for body in channel.bodies] == [
        "event-1", "event-2", "event-3"
    ]


def test_outbox_batch_false_publisher_confirm_is_retried(monkeypatch):
    store = RecordingStore()
    monkeypatch.setattr(workflow_worker.pika, "BasicProperties", lambda **kwargs: kwargs)

    class NackChannel:
        def basic_publish(self, **kwargs):
            return False

    workflow_worker._publish_batch(store, NackChannel(), [
        {"outbox_id": "out-nack", "event_id": "event-nack",
         "event_type": "test.nack", "attempts": 2}
    ])

    assert store.published == []
    assert store.failed == [("out-nack", 2, "RuntimeError")]
