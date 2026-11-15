import json
import os

import pika
import pytest

from app.workflow_engine import WorkflowStore
from app.workflow_worker import DEAD_QUEUE, QUEUE, EXCHANGE, _connection, _declare, _publish_batch


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


def test_duplicate_delivery_is_idempotent(tmp_path):
    store = WorkflowStore(str(tmp_path / "duplicate.sqlite3"))
    connection = None
    try:
        workflow = store.create_workflow(
            name="Duplicate delivery", created_by="ci", trigger_type="EVENT",
            trigger_config={"event_type": "integration.duplicate.event"},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True)
        event = store.publish_event(
            event_type="integration.duplicate.event", source="ci",
            payload={"case": "duplicate"}, idempotency_key="rabbitmq-duplicate",
        )
        connection = _connection()
        channel = connection.channel()
        _declare(channel)
        channel.queue_purge(queue=QUEUE)
        channel.queue_purge(queue=DEAD_QUEUE)
        channel.confirm_delivery()
        _publish_batch(store, channel, store.pending_outbox())
        method, _, body = channel.basic_get(queue=QUEUE, auto_ack=False)
        assert method is not None
        event_id = json.loads(body)["event_id"]
        assert event_id == event["event_id"]
        first = store.process_event(event_id)
        second = store.process_event(event_id)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        assert len(first) == 1
        assert len(second) == 1
        assert second[0]["run_id"] == first[0]["run_id"]
        assert second[0]["duplicate"] is True
        assert len(store.list_runs()) == 1
    finally:
        if connection and connection.is_open:
            connection.close()
        store.close()


def test_unacked_message_redelivered_after_consumer_disconnect():
    first = _connection()
    second = None
    try:
        channel = first.channel()
        _declare(channel)
        channel.queue_purge(queue=QUEUE)
        channel.queue_purge(queue=DEAD_QUEUE)
        channel.confirm_delivery()
        event_id = "integration-disconnect-redelivery"
        channel.basic_publish(
            exchange=EXCHANGE, routing_key="integration.recovery",
            body=json.dumps({"event_id": event_id}).encode(),
            properties=pika.BasicProperties(delivery_mode=2, message_id=event_id),
            mandatory=True,
        )
        method, _, _ = channel.basic_get(queue=QUEUE, auto_ack=False)
        assert method is not None
        first.close()  # Simulate loss of consumer before acknowledgement.
        second = _connection()
        recovered = second.channel()
        _declare(recovered)
        method, _, body = recovered.basic_get(queue=QUEUE, auto_ack=False)
        assert method is not None
        assert json.loads(body)["event_id"] == event_id
        recovered.basic_ack(delivery_tag=method.delivery_tag)
    finally:
        if first.is_open:
            first.close()
        if second and second.is_open:
            second.close()


def test_poison_message_reaches_dead_letter_queue_after_delivery_limit():
    connection = _connection()
    try:
        channel = connection.channel()
        _declare(channel)
        channel.queue_purge(queue=QUEUE)
        channel.queue_purge(queue=DEAD_QUEUE)
        channel.confirm_delivery()
        event_id = "integration-poison-message"
        channel.basic_publish(
            exchange=EXCHANGE, routing_key="integration.poison",
            body=b'{"event_id":"integration-poison-message","invalid":true}',
            properties=pika.BasicProperties(delivery_mode=2, message_id=event_id),
            mandatory=True,
        )
        deliveries = []

        def reject_poison(ch, method, properties, body):
            deliveries.append(method.delivery_tag)
            # Exercise the same consumer-side negative acknowledgement path.
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        tag = channel.basic_consume(queue=QUEUE, on_message_callback=reject_poison, auto_ack=False)
        import time
        for _ in range(50):
            connection.process_data_events(time_limit=0.1)
            if len(deliveries) >= 8:
                break
        channel.basic_cancel(tag)
        assert len(deliveries) >= 5, "Expected repeated consumer deliveries before dead-lettering"

        dead = None
        for _ in range(30):
            dead, _, body = channel.basic_get(queue=DEAD_QUEUE, auto_ack=False)
            if dead is not None:
                break
            time.sleep(0.1)
        assert dead is not None, "Expected poison message in durable dead-letter queue"
        assert json.loads(body)["event_id"] == event_id
        channel.basic_ack(delivery_tag=dead.delivery_tag)
    finally:
        if connection.is_open:
            connection.close()


def test_confirmed_publish_database_commit_gap_replays_same_event_idempotently(tmp_path):
    store = WorkflowStore(str(tmp_path / "outbox-confirm-gap.sqlite3"))
    connection = None
    try:
        workflow = store.create_workflow(
            name="Confirm gap replay", created_by="ci", trigger_type="EVENT",
            trigger_config={"event_type": "integration.confirm-gap"},
        )
        store.set_workflow_enabled(workflow["workflow_id"], True)
        event = store.publish_event(
            event_type="integration.confirm-gap", source="ci",
            payload={"case": "confirm-before-db-commit"},
            idempotency_key="rabbitmq-confirm-gap",
        )
        connection = _connection()
        channel = connection.channel()
        _declare(channel)
        channel.queue_purge(queue=QUEUE)
        channel.queue_purge(queue=DEAD_QUEUE)
        channel.confirm_delivery()

        # Model the crash window: RabbitMQ confirms the durable message, but the
        # process dies before the outbox row can be marked PUBLISHED.
        pending = store.pending_outbox()
        item = pending[0]
        confirmed = channel.basic_publish(
            exchange=EXCHANGE, routing_key=item["event_type"],
            body=json.dumps(item, separators=(",", ":")).encode(),
            properties=pika.BasicProperties(
                delivery_mode=2, content_type="application/json",
                message_id=item["event_id"], type=item["event_type"],
            ),
            mandatory=True,
        )
        assert confirmed is not False
        assert store.pending_outbox()[0]["event_id"] == event["event_id"]

        # Restarted publisher retries the still-pending row with the same ID.
        _publish_batch(store, channel, store.pending_outbox())
        assert store.pending_outbox() == []

        deliveries = []
        for _ in range(2):
            method, _, body = channel.basic_get(queue=QUEUE, auto_ack=False)
            assert method is not None
            deliveries.append(json.loads(body)["event_id"])
            store.process_event(deliveries[-1])
            channel.basic_ack(delivery_tag=method.delivery_tag)

        assert deliveries == [event["event_id"], event["event_id"]]
        assert len(store.list_runs()) == 1
        assert store.list_runs()[0]["workflow_id"] == workflow["workflow_id"]
    finally:
        if connection and connection.is_open:
            connection.close()
        store.close()
