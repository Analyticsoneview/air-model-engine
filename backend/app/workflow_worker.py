"""AIR workflow runtime: RabbitMQ outbox publisher, event consumer and time triggers.

This process is separate from the API. RabbitMQ outages do not prevent the API from
accepting durable events; the PostgreSQL outbox is retried with bounded backoff.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pika

from app.workflow_engine import WorkflowStore

log = logging.getLogger("air.workflow.worker")
EXCHANGE = "air.events"
QUEUE = "air.workflow.dispatch"
DEAD_EXCHANGE = "air.events.dead"
DEAD_QUEUE = "air.workflow.dead"


def _rabbit_url() -> str:
    direct = os.getenv("AIR_RABBITMQ_URL", "").strip()
    if direct:
        return direct
    password_file = os.getenv("AIR_RABBITMQ_PASSWORD_FILE", "")
    password = Path(password_file).read_text(encoding="utf-8").strip() if password_file else os.getenv("AIR_RABBITMQ_PASSWORD", "")
    if not password:
        raise RuntimeError("AIR_RABBITMQ_PASSWORD_FILE or AIR_RABBITMQ_PASSWORD is required")
    user = quote(os.getenv("AIR_RABBITMQ_USER", "air"), safe="")
    host = os.getenv("AIR_RABBITMQ_HOST", "rabbitmq")
    port = int(os.getenv("AIR_RABBITMQ_PORT", "5672"))
    vhost = quote(os.getenv("AIR_RABBITMQ_VHOST", "/"), safe="")
    return f"amqp://{user}:{quote(password, safe='')}@{host}:{port}/{vhost}"


def _connection() -> pika.BlockingConnection:
    params = pika.URLParameters(_rabbit_url())
    params.heartbeat = 30
    params.blocked_connection_timeout = 30
    params.connection_attempts = 3
    params.retry_delay = 2
    return pika.BlockingConnection(params)


def _declare(channel) -> None:
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=DEAD_EXCHANGE, exchange_type="fanout", durable=True)
    channel.queue_declare(
        queue=DEAD_QUEUE, durable=True,
        arguments={"x-queue-type": "quorum", "x-delivery-limit": 5},
    )
    channel.queue_bind(queue=DEAD_QUEUE, exchange=DEAD_EXCHANGE)
    channel.queue_declare(
        queue=QUEUE, durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": 5,
            "x-dead-letter-exchange": DEAD_EXCHANGE,
        },
    )
    channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key="#")



def _publish_batch(store: WorkflowStore, channel, items: list[dict]) -> None:
    """Publish confirmed persistent messages, then mark their outbox rows complete."""
    for item in items:
        body = json.dumps(item, separators=(",", ":"), allow_nan=False).encode("utf-8")
        confirmed = channel.basic_publish(
            exchange=EXCHANGE, routing_key=item["event_type"], body=body,
            properties=pika.BasicProperties(
                delivery_mode=2, content_type="application/json",
                message_id=item["event_id"], correlation_id=item.get("correlation_id"),
                type=item["event_type"],
            ),
            mandatory=True,
        )
        if confirmed is False:
            raise RuntimeError("RabbitMQ did not confirm event publication")
        store.mark_outbox_published(item["outbox_id"])


def _publish_outbox(stop: threading.Event) -> None:
    store = WorkflowStore()
    try:
        while not stop.is_set():
            items = store.pending_outbox(100)
            if not items:
                stop.wait(1.0)
                continue
            connection = None
            try:
                connection = _connection()
                channel = connection.channel()
                _declare(channel)
                channel.confirm_delivery()
                _publish_batch(store, channel, items)
            except Exception as exc:  # broker outage must not stop the API or worker
                log.warning("Workflow outbox publish deferred: %s", type(exc).__name__)
                for item in items:
                    try:
                        store.mark_outbox_failed(item["outbox_id"], item["attempts"], type(exc).__name__)
                    except Exception:
                        log.exception("Could not update workflow outbox retry state")
                stop.wait(2.0)
            finally:
                if connection and connection.is_open:
                    connection.close()
    finally:
        store.close()


def _schedule_time_triggers(stop: threading.Event) -> None:
    store = WorkflowStore()
    try:
        while not stop.is_set():
            try:
                for item in store.due_time_workflows():
                    store.publish_event(
                        event_type="workflow.time.triggered", source="workflow.scheduler",
                        payload={"workflow_id": item["workflow_id"], "workflow_name": item["name"],
                                 "scheduled_local_time": item["local_time"]},
                        idempotency_key=f"time:{item['workflow_id']}:{item['scheduled_key']}",
                    )
            except Exception:
                log.exception("AIR time-trigger scheduler iteration failed")
            stop.wait(5.0)
    finally:
        store.close()


def _consume(stop: threading.Event) -> None:
    while not stop.is_set():
        connection = None
        store = None
        try:
            connection = _connection()
            channel = connection.channel()
            _declare(channel)
            channel.basic_qos(prefetch_count=20)
            store = WorkflowStore()

            def handle(ch, method, properties, body):
                try:
                    message = json.loads(body.decode("utf-8"))
                    event_id = str(message.get("event_id") or properties.message_id or "")
                    if not event_id:
                        raise ValueError("RabbitMQ event has no event_id")
                    runs = store.process_event(event_id)
                    log.info("Processed workflow event %s; matched %d workflow(s)", event_id, len(runs))
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    log.exception("Workflow event processing failed; message returned to queue")
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            channel.basic_consume(queue=QUEUE, on_message_callback=handle, auto_ack=False)
            while not stop.is_set() and connection.is_open:
                connection.process_data_events(time_limit=1)
        except Exception as exc:
            log.warning("AIR workflow consumer reconnecting after %s", type(exc).__name__)
            stop.wait(3.0)
        finally:
            if store:
                store.close()
            if connection and connection.is_open:
                connection.close()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("AIR_WORKFLOW_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stop = threading.Event()
    publisher = threading.Thread(target=_publish_outbox, args=(stop,), name="workflow-outbox", daemon=True)
    scheduler = threading.Thread(target=_schedule_time_triggers, args=(stop,), name="workflow-scheduler", daemon=True)
    publisher.start()
    scheduler.start()
    log.info("AIR workflow runtime starting (RabbitMQ transport; no order execution)")
    try:
        _consume(stop)
    except KeyboardInterrupt:
        log.info("AIR workflow runtime stopping")
    finally:
        stop.set()
        publisher.join(timeout=5)
        scheduler.join(timeout=5)


if __name__ == "__main__":
    main()
