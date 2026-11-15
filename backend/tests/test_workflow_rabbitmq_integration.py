import json
import os

import pika
import pytest

from app.workflow_engine import WorkflowStore
from app.workflow_worker import DEAD_QUEUE, QUEUE, _connection, _declare, _publish_batch


pytestmark = pytest.mark.skipif(
    not os.getenv("AIR_RABBITMQ_URL"),
    reason="RabbitMQ integration requires the dedicated RabbitMQ service job",
)


def test_outbox_publish_and_rabbitmq_delivery_create_durable_run(tmp_path, monkeypatch):
    monkeypatch.setenv("AIR_RABBITMQ_URL", "amqp://air:testpass@localhost:5672/%2F")
    store = WorkflowStore(str(tmp_path / "workflow.sqlite3"))
    connection = None
    try:
        workflow = store.create_workflow(
            name="Rabbit integration", created_by="ci", trigger_type="EVENT",
            trigger_config={"event_type": "integration.workflow.event"},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True)
        event = store.publish_event(
            event_type="integration.workflow.event", source="ci",
            payload={"run": "rabbitmq"}, idempotency_key="rabbitmq-integration-1",
        )
        pending = store.pending_outbox()
        assert len(pending) == 1

        connection = _connection()
        channel = connection.channel()
        _declare(channel)
        channel.queue_purge(queue=QUEUE)
        channel.queue_purge(queue=DEAD_QUEUE)
        channel.confirm_delivery()
        _publish_batch(store, channel, pending)

        method, properties, body = channel.basic_get(queue=QUEUE, auto_ack=False)
        assert method is not None
        message = json.loads(body.decode("utf-8"))
        assert message["event_id"] == event["event_id"]
        runs = store.process_event(message["event_id"])
        channel.basic_ack(delivery_tag=method.delivery_tag)

        assert len(runs) == 1
        assert runs[0]["workflow_id"] == workflow["workflow_id"]
        assert store.list_runs()[0]["status"] == "QUEUED"
        assert store.pending_outbox() == []
    finally:
        if connection and connection.is_open:
            connection.close()
        store.close()
