# AIR Market Data and Broker Gateway

AIR uses a self-hosted backend so broker API credentials stay off the Flutter app and persistent market-data sessions remain available when a phone sleeps or changes network. The backend is a gateway and orchestrator; it does not replace broker APIs or create market data.

## Main Account data policy

At any moment, exactly **one broker account** is selected as AIR's Main Account for market-data retrieval. That same account supplies both historical candles and live WebSocket ticks. The provider can be changed by an explicit user action; it is not permanently fixed.

Switching closes the previous broker adapter before authenticating the selected account. If the new connection fails, AIR reports an outage and remains offline. There is no silent or automatic provider failover, and no second provider is queried in parallel. Execution accounts are separate: multi-account order execution can be supported independently of the single market-data Main Account.

## Architecture

One selected broker Main Account -> provider adapter -> normalized AIR market-data contracts -> (Redis pub/sub, next integration stage) -> FastAPI/WebSocket gateway -> (PostgreSQL historical bars, snapshots and audit records, next integration stage) -> Flutter app and AIR research modules.

## Current implementation

- `app/market_data/contracts.py`: normalized instrument, tick and historical-bar contracts and provider adapter protocol.
- `app/market_data/router.py`: single active Main Account lifecycle, shared historical/live source, explicit switching, close-before-authenticate, outage state and no automatic failover.
- `app/market_data/hub.py`: WebSocket fan-out to AIR clients.
- `app/main.py`: health, data-status, explicit Main Account select/disconnect endpoints and WebSocket endpoint.
- `Dockerfile`: container image for the FastAPI gateway.

This is a backend foundation only. No live broker provider adapter, credential vault, Redis persistence/pub-sub, PostgreSQL storage, user authentication, subscription endpoint, or broker connection has been enabled yet. The selection endpoint can only select an adapter that has already been registered by the server. The status endpoint must not be mistaken for a connected feed.

## Deployment

Build and run on an always-on self-hosted Linux machine, NAS or VPS. Docker Compose/Swarm can host the gateway, Redis and PostgreSQL. Use TLS at the reverse proxy. Put secrets in Docker secrets or a proper secret manager, not in source control or Flutter.

## Security and operational requirements before production

- Authenticate and authorize every REST/WebSocket client.
- Encrypt broker credentials and tokens at rest; restrict access by user/account.
- Never expose provider credentials or raw broker payloads to the mobile app.
- Add provider heartbeat, reconnect with backoff, subscription reconciliation and explicit outage reporting.
- Add durable storage, tick freshness checks, duplicate detection and market-session controls.
- Respect each broker's API terms, data redistribution rules, subscription limits and exchange licensing.
- Keep order execution separately permissioned from market-data access. Paper mode remains default.


## Customer execution accounts

Order destinations are modeled separately from the market-data Main Account. A customer may register multiple accounts under the same broker and across different brokers. Each account has an independent order-placement permission, and batch orders carry an explicit destination and quantity for every account.

- `app/brokers/customer_accounts.py`: SQLite-backed ownership directory. The composite broker/account identifier is unique, customer listings are tenant-scoped, and order permission can be enabled or revoked independently. The default database path is `data/customer_accounts.sqlite3`; persist the data directory with a Docker volume.
- `app/services/execution.py`: requires the authenticated customer identifier and validates ownership plus order permission for both single-account and batch routing. Batch preflight checks every selected account before the first live submission. Results remain per account because broker responses can partially succeed.
- `app/brokers/registry.py`: holds independently connected broker sessions for execution accounts. This registry does not change or expand the one-account market-data policy.

The directory stores account identifiers and permissions only. It does not store broker passwords, API secrets, refresh tokens or access tokens. Do not expose account-management or execution methods through public API routes until customer authentication, authorization, encrypted credential storage, CSRF/rate limiting where applicable, and audit logging are implemented. A customer identifier supplied by an unauthenticated client is not proof of identity.


## Authentication and credential protection foundation

- `app/auth_store.py`: SQLite customer identity store with unique email and active-account flag.
- `app/security.py`: Argon2 password hashing and short-lived JWT access tokens (30 minutes), with issuer/audience validation.
- `app/credential_vault.py`: Fernet authenticated encryption for broker credential payloads at rest. Credential listing returns metadata only; plaintext is never returned by account APIs.
- `app/main.py`: authenticated customer registration/login, customer-scoped execution account management, encrypted credential save, and authenticated market-data status/Main Account endpoints. WebSocket requires a bearer token.
- New customer registration is disabled by default. Set `AIR_ALLOW_CUSTOMER_SIGNUP=true` only for a controlled onboarding window or use an administrator-managed provisioning process.
- Configure `AIR_JWT_SECRET` (at least 32 characters) and `AIR_CREDENTIAL_KEY` (Fernet key). Prefer Docker secrets by setting `AIR_JWT_SECRET_FILE` and `AIR_CREDENTIAL_KEY_FILE` to mounted secret paths. Generate a Fernet key with `Fernet.generate_key()`; never rotate it without a planned re-encryption migration.
- Persist the `data/` directory as a protected volume. Back it up encrypted and restrict filesystem permissions.

**Not production-complete yet:** no provider-specific broker adapter or OAuth/token refresh flow is installed; credentials can be encrypted and saved but are not used to authenticate a broker. No public order-placement endpoint is exposed. Account order permission cannot be enabled through the API until broker authorization is verified. Add rate limiting, email verification/password reset, refresh-token rotation/revocation, admin provisioning, audit log, database migration strategy, TLS, and security review before onboarding real customers or enabling live trading.


## Durable order ledger (foundation)

- `app/services/order_ledger.py` persists broker order identifiers, status and normalized response metadata in SQLite using WAL mode and an account-scoped unique key: broker + account + idempotency key.
- `ExecutionService` can be constructed with this ledger so a completed result is returned after an application restart rather than being forgotten in process memory.
- This protects retries after a completed submission. It does **not** yet provide an atomic pre-submit reservation, broker-timeout ambiguity resolution, event-sourced audit history, or automated broker reconciliation. A timeout must be treated as unknown and checked against the broker order book; never blindly retry a possibly accepted live order.
- Keep live execution disabled until atomic intent reservation, durable audit events, provider-specific reconciliation and fault-injection tests are complete. The ledger database must be included in encrypted backups and protected persistent storage.
