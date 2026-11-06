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


## Agreed broker integration scope

The initial supported-provider catalog is Angel One SmartAPI, DhanHQ, Zerodha Kite Connect, Upstox API and FYERS API v3. The authenticated `GET /api/v1/brokers/catalog` endpoint exposes the provider-specific authorization and feed modes to the app. Account registration rejects providers outside this list.

Provider-specific authorization cannot be treated as one generic username/password form:

- Angel One uses client code, PIN and TOTP; its session returns JWT, refresh token and feed token. Historical candles use the SmartAPI candle endpoint and live ticks use Smart Stream.
- DhanHQ uses an access token (or its TOTP-enabled token-generation flow); historical candles use `/charts/historical` and `/charts/intraday`; live data uses its authenticated binary WebSocket feed. Data API entitlement is separate from trading API access.
- Zerodha requires a browser login redirect, a short-lived request token and a server-side SHA-256 checksum exchange using the API secret. The API secret must never be placed in Flutter.
- Upstox uses OAuth 2.0 authorization-code login and a server-side code exchange; market feed v3 requires the broker-authorized WebSocket URI and Protobuf decoding.
- FYERS uses an authorization-code redirect and server-side app-id hash exchange; the API exposes separate data and general WebSockets.

The catalog is not an integration. All five currently report `authorization_ready=false`. Provider adapters, callback/state validation, token lifecycle, feed decoding, order/position normalization, broker-specific rate-limit handling and sandbox/live verification remain required. Dhan data entitlement and static-IP restrictions for order APIs, plus each broker's commercial/API terms, must be confirmed before enabling production features.


## AIR operator scope for the global Main Account

The Main Account is an app-wide data-source decision, not a per-customer preference. Only customer IDs explicitly listed in `AIR_OPERATOR_CUSTOMER_IDS` (comma-separated UUIDs) can read global feed status, switch the Main Account or disconnect it. Regular customers can manage only their own execution accounts and credentials. Provision operator IDs out of band; never expose this setting as a customer-editable field. Until a provider adapter is registered and authenticated, Main Account selection correctly remains unavailable.


## DhanHQ v2 REST integration milestone

`app/brokers/dhan.py` now provides an async HTTPX client for Dhan profile verification, LTP/OHLC/quote snapshots, daily and intraday historical candles, order-book reads, and order place/modify/cancel request construction. Customer-facing backend routes expose profile verification and market-data retrieval. Market-data routes are operator-only and reject any account that is not the one configured as the single AIR Main Account.

Dhan integration constraints:
- Save `client_id` and a user-authorized `access_token` in the encrypted credential vault. The profile check verifies that the returned Dhan client ID matches the configured account.
- Dhan documents access tokens as short-lived (24 hours for the documented individual token flow); renewability differs by token-generation method. Do not assume a permanent refresh token.
- Data API entitlement is separate from trading API access. Verify the account's `dataPlan` and `dataValidity` before relying on historical or quote APIs.
- Dhan requires a whitelisted static IP for order placement, modification and cancellation. The current AIR client includes request methods but AIR does not expose live order routes or enable order permission.
- The binary Dhan live market WebSocket and normalized packet decoder are not yet connected to the AIR MarketDataHub. Therefore this milestone is **REST integration only**, not a completed live streaming integration.

References: DhanHQ official Authentication, Market Quote, Historical Data, Live Market Feed and Orders documentation.


### DhanHQ live-feed transport and decoder milestone

- `app/brokers/dhan_feed.py` decodes Dhan v2 little-endian ticker, previous-close, quote, OI, full-depth and disconnect packets. It handles concatenated packets and rejects malformed lengths.
- `app/brokers/dhan_socket.py` opens the documented v2 WebSocket URL, sends JSON subscriptions in batches of at most 100 instruments, enforces the 5,000-instrument connection limit, and decodes binary responses.
- This transport is currently a reusable provider component; it is **not yet wired into the application lifecycle, Main Account router, or MarketDataHub**. No live feed should be shown as connected until that integration and a real authorized Dhan account test pass.
- Dhan v2 docs specify up to five sockets per user, up to 5,000 instruments per connection, little-endian response packets and feed request codes 15/17/21 for ticker/quote/full subscriptions.

Official references:
- https://dhanhq.co/docs/v2/live-market-feed/
- https://dhanhq.co/docs/v2/annexure/


## Zerodha Kite Connect v3 integration milestone

- `app/brokers/zerodha.py` implements the server-side login URL, SHA-256 request-token checksum exchange, authenticated profile, quote snapshots, historical candles, order book, positions, holdings, and guarded order request validation.
- Customer-owned account endpoints expose a login URL and accept the short-lived request token for server-side exchange. The resulting access token is written back into the encrypted credential vault only after profile verification.
- The API secret is never returned to Flutter. Zerodha's access token expires at the next daily session boundary; the login flow must be repeated when expired. The route keeps AIR order permission disabled.
- Kite live WebSocket streaming, normalized quote packet parsing and Main Account router integration are not yet wired. Do not treat this as a completed live market-data feed.

Official references:
- https://www.kite.trade/docs/connect/v3/user/
- https://kite.trade/docs/connect/v3/market-quotes/
- https://kite.trade/docs/connect/v3/websocket/


## Upstox OAuth and REST integration milestone

- `app/brokers/upstox.py` implements OAuth authorization URL construction, authorization-code exchange, profile, market quote, historical candle, portfolio and order REST operations.
- Customer-owned Upstox accounts can save `client_id`, `client_secret` and the exact registered `redirect_uri` in the encrypted vault. AIR generates a one-time random OAuth state, validates it on callback exchange, exchanges the single-use code server-side and verifies the profile before storing the access token encrypted.
- OAuth state is currently held in process memory and is invalidated by server restart; production deployment must use a shared, expiring, one-time state store (e.g. Redis) before running multiple replicas.
- Upstox standard access tokens expire at 3:30 AM the following day. Upstox analytics-token product has different entitlement and expiry characteristics and is not implemented here. Live Protobuf feed decoding and Main Account router integration remain outstanding; live order permission stays disabled.

Official references:
- https://upstox.com/developer/api-documentation/authentication/
- https://upstox.com/developer/api-documentation/v3/get-market-data-feed/
- https://upstox.com/developer/api-documentation/get-market-data-feed-authorize-v3/
