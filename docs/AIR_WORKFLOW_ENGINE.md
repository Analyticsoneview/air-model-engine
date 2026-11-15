# AIR Workflow Engine & Automation Platform

## Decision record

**Status:** Gate 8 in progress — Phase 1 foundation under validation  
**Runtime target:** self-hosted Docker Swarm on Linux  
**Developer workstation:** Windows 10/11, with native tools or Docker Desktop  
**Initial message transport:** RabbitMQ  
**Durable system of record:** PostgreSQL  
**Short-lived coordination:** Redis, only where needed  
**Execution default:** research-only; no order placement

AIR already contains QOC, ORB, market-data, portfolio-risk, backtest, reporting and notification capabilities. The workflow engine orchestrates these services; it must not reimplement their calculations.

## Why RabbitMQ first

RabbitMQ is the preferred first transport because AIR's initial needs are task/event routing, competing consumers, acknowledgements, retries and delayed/retry queues. Kafka is a stronger fit if AIR later needs very high-volume event streams, long retention/replay and multiple independent stream-processing consumers. Starting with Kafka now would add operational complexity without a demonstrated requirement.

The application persists every accepted event and its outbox record in one database transaction. A publisher will later forward pending outbox records to RabbitMQ. This avoids the dual-write failure in which the database commits but the broker publish is lost. Consumers must be idempotent because broker delivery is at-least-once.

Do not add a broker dependency to API startup or make the API unavailable when RabbitMQ is down. The outbox remains durable and publisher/worker services recover independently.

## Windows development and self-hosted deployment

- **Windows native:** RabbitMQ supports Windows and can run as a Windows service. Install a supported Erlang/OTP version first, then the RabbitMQ installer. Use a dedicated non-guest application account.
- **Windows with Docker Desktop:** preferred for parity with the production container. Use the official RabbitMQ management image for local development and keep its data in a named volume.
- **Kafka on Windows:** use WSL2 or Docker for development; do not make native Windows Kafka the standard developer setup.
- **Production:** run RabbitMQ as a private service on the existing Ubuntu Docker Swarm overlay network. Persist broker data, protect credentials with Docker secrets, configure health checks and resource limits, and do not publish the AMQP or management ports to the public internet.
- **No cloud or Kubernetes dependency** is introduced.

## Event and workflow model

### Trigger types
- `EVENT`: a named domain event arrives, e.g. `market.orb.breakout`.
- `TIME`: a calendar/time-zone aware schedule fires, e.g. weekday 09:18 Asia/Kolkata.
- `STRATEGY`: a strategy engine emits a candidate or state transition.
- `CONDITION`: a persisted metric or event satisfies a threshold.
- Composite triggers will be represented as explicit workflow conditions, not hidden scheduler code.

### Initial event families
- `market.session.opened`, `market.session.closed`
- `market.orb.breakout`, `market.orb.failed`
- `market.instrument.updated`, `market.data.stale`
- `qoc.scan.requested`, `qoc.candidate.qualified`, `qoc.candidate.rejected`
- `portfolio.snapshot.updated`, `portfolio.risk.threshold_breached`
- `backtest.completed`, `report.ready`

Each event carries a stable event ID, type, source, UTC occurrence timestamp, JSON payload, idempotency key and optional correlation ID. Exchange-session schedules use Asia/Kolkata and an exchange calendar; they must not assume every weekday is a trading day.

### Workflow lifecycle
1. Define and validate a workflow; save a versioned definition.
2. Keep new definitions disabled until explicitly enabled by an authorized administrator.
3. Match an event or due schedule to enabled definitions.
4. Create one durable run per workflow version and trigger identity.
5. Execute steps through registered AIR service adapters.
6. Persist each step result, retryable failure and terminal state.
7. Publish completion/failure events and notify according to permissions.

Workflow runs need idempotency keys, bounded retries with backoff, timeout handling, stale-data guards, correlation IDs and append-only audit history. Replay must create a traceable new attempt and must not silently duplicate side effects.

## Execution modes and safety boundary

- `RESEARCH_ONLY`: compute, evaluate and publish research records. Default.
- `ALERT_NOTIFY`: research plus configured user notifications.
- `AUTHORIZED_EXECUTION`: reserved for a future separately approved capability. It must require explicit permissions, risk checks, a kill switch and an auditable authorization path.

The initial engine will not call broker order-placement APIs. Broker execution remains disabled independently of workflow configuration.

## Delivery phases

1. **Foundation:** versioned workflow definitions, event contracts, durable event inbox and transactional outbox. (In progress in PR #50.)
2. **Transport:** RabbitMQ publisher/consumer, acknowledgements, retry/dead-letter policy and health checks.
3. **Scheduler and run ledger:** time triggers, exchange calendar, durable run/step state, deduplication and recovery.
4. **Rule and strategy adapters:** connect ORB, QOC, market data and portfolio-risk events without duplicating domain logic.
5. **Notifications and reports:** dashboard, mobile, Telegram/email adapters with per-customer authorization and deduplication.
6. **Workflow Studio:** admin builder/templates, enable/pause controls, versioning and run history.
7. **Hardening:** failure injection, restart/replay tests, load tests, permissions, audit and production acceptance.

## Initial workflow examples

- **QOC live research:** eligible session trigger → data freshness check → request QOC scan → persist qualified/rejected evidence → publish dashboard event.
- **ORB alert:** ORB breakout event → underlying/volume confirmation from existing strategy service → optional QOC confirmation → alert only when configured.
- **Portfolio risk:** portfolio snapshot event → evaluate concentration/exposure thresholds → create risk alert.
- **Post-market:** exchange close trigger → request existing research/report services → publish report-ready event.

## Current implementation boundary

PR #50 adds the PostgreSQL schema and repository for workflow definitions, idempotent event intake and transactional outbox, plus SQLite local/test compatibility. It intentionally does not yet dispatch jobs, schedule workflows, send notifications, or place orders. RabbitMQ is added only in the transport phase, after the durable contracts pass CI.
