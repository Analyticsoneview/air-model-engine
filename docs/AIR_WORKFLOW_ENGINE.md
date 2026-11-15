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
- `strategy.orb.signal.created` — emitted by the existing live ORB engine when a new signal is formed
- `qoc.snapshot.captured`, `qoc.scan.completed`, `qoc.candidate.qualified`, `qoc.backtest.completed` — emitted by the evidence-based Dhan QOC endpoints
- `research.signal.persisted` — emitted when the operator Model Engine ledger stores a signal
- `portfolio.snapshot.updated` — emitted after a customer-owned read-only broker snapshot is persisted
- `market.session.opened`, `market.session.closed`, `market.instrument.updated`, `market.data.stale`, `report.ready` — reserved contracts for later adapters

A workflow may set `trigger_config.customer_id` to match only that customer's events. Unscoped definitions match across customers and should be reserved for platform-level administrator workflows.

Each event carries a stable event ID, type, source, UTC occurrence timestamp, JSON payload, idempotency key and optional correlation ID. CONDITION triggers evaluate a safe allowlist of nested JSON field operators (eq, neq, gt, gte, lt, lte, in, not_in, contains, exists) with ALL/ANY grouping; arbitrary expressions and code are never evaluated. For example: `{"event_type":"portfolio.snapshot.updated","customer_id":"customer-123","filters":[{"field":"summary.concentration_top_position_pct","operator":"gte","value":40}]}`. Exchange-session schedules currently support weekdays and configurable misfire grace; a verified NSE holiday calendar is still required before production trading-day schedules are enabled.

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
- `AUTHORIZED_EXECUTION`: reserved and currently rejected by the API until a separately approved execution capability exists. It must later require explicit permissions, risk checks, a kill switch and an auditable authorization path.

The initial engine will not call broker order-placement APIs. Broker execution remains disabled independently of workflow configuration.

## Delivery phases

1. **Foundation:** versioned workflow definitions, event contracts, durable event inbox and transactional outbox. (Merged in PR #50.)
2. **Transport:** RabbitMQ publisher/consumer, acknowledgements, retry/dead-letter policy and health checks. (Merged in PR #51.)
3. **Scheduler and run ledger:** time triggers, durable run records, deduplication, misfire grace and startup recovery. (Merged in PR #51; exchange holiday calendar remains to be added.)
4. **Rule and strategy adapters:** ORB, QOC, model-ledger and portfolio snapshot events, customer-scoped matching and safe nested condition operators. (In progress in Gate 8 Phase 4.)
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
