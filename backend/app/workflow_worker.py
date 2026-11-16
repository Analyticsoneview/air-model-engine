"""AIR workflow runtime: RabbitMQ transport, scheduler, executor and health heartbeat.

This process is separate from the API. RabbitMQ outages do not prevent the API from
accepting durable events; the PostgreSQL outbox is retried with bounded backoff.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timezone

import pika

from app.deployment_profiles import load_runtime_profile
from app.workflow_engine import WorkflowStore
from app.workflow_executor import execute_workflow_run
from app.workflow_alerts import deliver_runtime_alerts, evaluate_runtime_alerts

log = logging.getLogger("air.workflow.worker")
EXCHANGE = "air.events"
QUEUE = "air.workflow.dispatch"
DEAD_EXCHANGE = "air.events.dead"
DEAD_QUEUE = "air.workflow.dead"
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
WORKER_STARTED_AT = datetime.now(timezone.utc).isoformat()
_CONSUMER_CONNECTED = False


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




def _retry_or_dead_letter(channel, method, properties, body: bytes, max_attempts: int = 5) -> str:
    """Republish failed deliveries with an explicit bounded retry counter.

    Quorum-queue delivery limits remain a crash-loop safety net, but application
    retries are explicit because broker delivery-count behavior differs across
    RabbitMQ versions and consumer acknowledgement patterns.
    """
    headers = dict(getattr(properties, "headers", None) or {})
    attempts = int(headers.get("x-air-retry-count", 0)) + 1
    dead_letter = attempts >= max_attempts
    headers["x-air-retry-count"] = attempts
    target_exchange = DEAD_EXCHANGE if dead_letter else EXCHANGE
    confirmed = channel.basic_publish(
        exchange=target_exchange,
        routing_key="" if dead_letter else method.routing_key,
        body=body,
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type=getattr(properties, "content_type", None) or "application/json",
            message_id=getattr(properties, "message_id", None),
            correlation_id=getattr(properties, "correlation_id", None),
            type=getattr(properties, "type", None),
            headers=headers,
        ),
        mandatory=True,
    )
    if confirmed is False:
        raise RuntimeError("RabbitMQ did not confirm retry/dead-letter publication")
    channel.basic_ack(delivery_tag=method.delivery_tag)
    return "dead-lettered" if dead_letter else "retried"


def _publish_batch(store: WorkflowStore, channel, items: list[dict]) -> None:
    """Publish each outbox row independently so a partial batch cannot poison prior rows.

    Publisher confirms make each successful message durable at RabbitMQ before its
    outbox row is marked published. If a later publish fails, only that row is
    scheduled for retry; earlier confirmed rows remain PUBLISHED. A crash between
    broker confirmation and the database update can still redeliver, so consumers
    must continue to rely on the event/run uniqueness constraints.
    """
    for item in items:
        try:
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
        except Exception as exc:
            # Do not reset already-confirmed rows to PENDING when a later item
            # fails. The stable event ID and database uniqueness make any
            # unavoidable confirm/commit redelivery safe.
            store.mark_outbox_failed(item["outbox_id"], item.get("attempts", 0), type(exc).__name__)
            log.warning("Workflow outbox item %s deferred after %s",
                        item.get("outbox_id"), type(exc).__name__)


def _publish_outbox(stop: threading.Event) -> None:
    store = None
    try:
        while not stop.is_set():
            try:
                # The API applies migrations during startup. In Swarm the worker may
                # start first, so database/schema availability must be retried.
                if store is None:
                    store = WorkflowStore()
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
                except Exception as exc:
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
            except Exception as exc:
                log.warning("Workflow outbox runtime will retry after %s", type(exc).__name__)
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass
                    store = None
                stop.wait(3.0)
    finally:
        if store is not None:
            store.close()


def _schedule_time_triggers(stop: threading.Event) -> None:
    store = None
    try:
        while not stop.is_set():
            try:
                # Retry until the API has completed the workflow migrations.
                if store is None:
                    store = WorkflowStore()
                for item in store.due_time_workflows():
                    store.publish_event(
                        event_type="workflow.time.triggered", source="workflow.scheduler",
                        payload={"workflow_id": item["workflow_id"], "workflow_name": item["name"],
                                 "customer_id": item.get("customer_id"),
                                 "scheduled_local_time": item["local_time"]},
                        idempotency_key=f"time:{item['workflow_id']}:{item['scheduled_key']}",
                    )
            except Exception as exc:
                log.warning("AIR time-trigger scheduler will retry after %s", type(exc).__name__)
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass
                    store = None
            stop.wait(5.0)
    finally:
        if store is not None:
            store.close()



def _execute_claim_with_heartbeat(store: WorkflowStore, claim: dict) -> dict | None:
    """Keep a claimed run leased while a potentially long action is executing."""
    stop_heartbeat = threading.Event()
    lease_lost = threading.Event()
    run_id = claim["run_id"]
    claim_version = claim["claim_version"]

    def maintain_lease() -> None:
        heartbeat_store = None
        try:
            heartbeat_store = WorkflowStore()
            while not stop_heartbeat.is_set():
                try:
                    renewed = heartbeat_store.renew_run_lease(
                        run_id, WORKER_ID, claim_version, lease_seconds=60,
                    )
                    if not renewed:
                        current = heartbeat_store.run_context(run_id)
                        if current and current.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                            return
                        lease_lost.set()
                        return
                except Exception as exc:
                    log.warning("Workflow run %s lease heartbeat retrying after %s",
                                run_id, type(exc).__name__)
                if stop_heartbeat.wait(15.0):
                    return
        except Exception as exc:
            log.warning("Workflow run %s lease heartbeat unavailable (%s)",
                        run_id, type(exc).__name__)
        finally:
            if heartbeat_store is not None:
                heartbeat_store.close()

    heartbeat = threading.Thread(
        target=maintain_lease, name=f"workflow-lease-{run_id[:8]}", daemon=True,
    )
    heartbeat.start()
    try:
        result = execute_workflow_run(
            store, run_id, worker_id=WORKER_ID, claim_version=claim_version,
        )
        if lease_lost.is_set():
            raise RuntimeError("Workflow run lease was lost while executing")
        return result
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=5.0)


def _execute_runs(stop: threading.Event) -> None:
    store = None
    try:
        while not stop.is_set():
            try:
                if store is None:
                    store = WorkflowStore()
                claims = store.claim_runnable_runs(WORKER_ID, 20, lease_seconds=60)
                for claim in claims:
                    if stop.is_set():
                        store.release_run_claim(
                            claim["run_id"], WORKER_ID, claim["claim_version"],
                            "Worker shutting down before execution",
                        )
                        continue
                    try:
                        result = _execute_claim_with_heartbeat(store, claim)
                        if result:
                            log.info("AIR workflow run %s finished with %s",
                                     claim["run_id"], result.get("status"))
                    except Exception as exc:
                        log.exception("AIR workflow run %s executor iteration failed (%s)",
                                      claim["run_id"], type(exc).__name__)
                        try:
                            store.release_run_claim(
                                claim["run_id"], WORKER_ID, claim["claim_version"],
                                f"{type(exc).__name__}: {str(exc)[:800]}",
                            )
                        except Exception:
                            log.exception("Could not release workflow run claim %s", claim["run_id"])
                stop.wait(1.0 if claims else 2.0)
            except Exception as exc:
                log.warning("AIR workflow execution runtime will retry after %s", type(exc).__name__)
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass
                    store = None
                stop.wait(3.0)
    finally:
        if store is not None:
            store.close()


def _consume(stop: threading.Event) -> None:
    global _CONSUMER_CONNECTED
    while not stop.is_set():
        connection = None
        store = None
        try:
            connection = _connection()
            channel = connection.channel()
            _declare(channel)
            _CONSUMER_CONNECTED = True
            channel.basic_qos(prefetch_count=20)
            channel.confirm_delivery()
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
                    log.exception("Workflow event processing failed; applying bounded retry policy")
                    try:
                        outcome = _retry_or_dead_letter(ch, method, properties, body)
                        log.warning("Workflow event %s %s", getattr(properties, "message_id", None), outcome)
                    except Exception:
                        log.exception("Workflow retry publication failed; retaining original delivery")
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            channel.basic_consume(queue=QUEUE, on_message_callback=handle, auto_ack=False)
            while not stop.is_set() and connection.is_open:
                connection.process_data_events(time_limit=1)
        except Exception as exc:
            _CONSUMER_CONNECTED = False
            log.warning("AIR workflow consumer reconnecting after %s", type(exc).__name__)
            stop.wait(3.0)
        finally:
            _CONSUMER_CONNECTED = False
            if store:
                store.close()
            if connection and connection.is_open:
                connection.close()



def _monitor_runtime(stop: threading.Event) -> None:
    """Poll durable runtime state and notify configured AIR operations destinations."""
    while not stop.is_set():
        store = None
        connection = None
        try:
            store = WorkflowStore()
            dispatch_depth = dead_letter_depth = None
            try:
                connection = _connection()
                channel = connection.channel()
                _declare(channel)
                dispatch_depth = channel.queue_declare(queue=QUEUE, passive=True).method.message_count
                dead_letter_depth = channel.queue_declare(queue=DEAD_QUEUE, passive=True).method.message_count
            except Exception as exc:
                log.warning("Workflow runtime monitor cannot inspect RabbitMQ (%s)", type(exc).__name__)
                alerts = [{
                    "key": "rabbitmq-unavailable",
                    "title": "Workflow RabbitMQ unavailable",
                    "detail": "The workflow operations monitor cannot reach RabbitMQ; event delivery may be delayed.",
                }]
            else:
                alerts = evaluate_runtime_alerts(
                    store, dispatch_depth=dispatch_depth,
                    dead_letter_depth=dead_letter_depth,
                )
            if alerts:
                result = deliver_runtime_alerts(alerts)
                log.warning("Workflow runtime alerts evaluated=%d attempted=%d delivered=%d",
                            len(alerts), result["attempted"], result["sent"])
        except Exception as exc:
            log.warning("Workflow runtime monitor will retry after %s", type(exc).__name__)
        finally:
            if connection and connection.is_open:
                connection.close()
            if store is not None:
                store.close()
        stop.wait(max(15, int(os.getenv("AIR_WORKFLOW_ALERT_POLL_SECONDS", "30"))))


def _record_heartbeat(status: str, details: dict) -> None:
    store = WorkflowStore()
    try:
        store.record_worker_heartbeat(
            worker_id=WORKER_ID, component="workflow-runtime", status=status,
            details=details, started_at=WORKER_STARTED_AT,
        )
    finally:
        store.close()


def _heartbeat_loop(stop: threading.Event, components: list[threading.Thread]) -> None:
    while not stop.is_set():
        live = {thread.name: thread.is_alive() for thread in components}
        connected = bool(_CONSUMER_CONNECTED)
        healthy = connected and all(live.values())
        status = "RUNNING" if healthy else "DEGRADED"
        try:
            _record_heartbeat(status, {
                "rabbitmq_connected": connected,
                "components": live,
                "pid": os.getpid(),
            })
        except Exception as exc:
            log.warning("Could not persist workflow worker heartbeat (%s)", type(exc).__name__)
        stop.wait(10.0)
    try:
        _record_heartbeat("STOPPING", {"pid": os.getpid(), "rabbitmq_connected": bool(_CONSUMER_CONNECTED)})
    except Exception as exc:
        log.warning("Could not persist workflow worker shutdown heartbeat (%s)", type(exc).__name__)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("AIR_WORKFLOW_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    profile = load_runtime_profile()
    log.info(
        "AIR workflow runtime profile=%s tenancy=%s",
        profile["profile_id"], profile["deployment"]["tenancy"],
    )
    stop = threading.Event()
    publisher = threading.Thread(target=_publish_outbox, args=(stop,), name="workflow-outbox", daemon=True)
    scheduler = threading.Thread(target=_schedule_time_triggers, args=(stop,), name="workflow-scheduler", daemon=True)
    executor = threading.Thread(target=_execute_runs, args=(stop,), name="workflow-executor", daemon=True)
    monitor = threading.Thread(target=_monitor_runtime, args=(stop,), name="workflow-operations-monitor", daemon=True)
    publisher.start()
    scheduler.start()
    executor.start()
    monitor.start()
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(stop, [publisher, scheduler, executor, monitor]),
        name="workflow-heartbeat", daemon=True,
    )
    heartbeat.start()
    log.info("AIR workflow runtime starting (RabbitMQ transport; no order execution)")
    try:
        _consume(stop)
    except KeyboardInterrupt:
        log.info("AIR workflow runtime stopping")
    finally:
        stop.set()
        publisher.join(timeout=5)
        scheduler.join(timeout=5)
        executor.join(timeout=5)
        monitor.join(timeout=5)
        heartbeat.join(timeout=5)


if __name__ == "__main__":
    main()
