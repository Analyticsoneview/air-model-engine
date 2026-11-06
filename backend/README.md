# AIR Market Data and Broker Gateway

AIR uses a self-hosted backend because the mobile app must not hold broker API secrets or be responsible for persistent WebSocket sessions. The backend is a gateway and orchestrator; it does not replace broker APIs or create market data.

## Why a server is needed

- Broker API credentials and session tokens stay off the Flutter app.
- WebSocket connections must remain alive when the phone is closed or changes network.
- One broker connection can distribute normalized data to AIR QOC, SURVIVOR, CPR, SMC, scanners and multiple app sessions.
- Historical downloads can be scheduled, retried, validated and stored centrally.
- Provider rate limits, instrument-token mapping, reconnects and failover are handled centrally.

A server is not inherently required for a single-device app that only fetches occasional REST quotes. It is required for AIR's intended persistent, multi-provider, multi-device and background-streaming architecture.

## Architecture

Broker APIs (multiple providers and accounts) -> provider adapters -> independent historical/live routing -> normalized AIR market-data contracts -> Redis pub/sub (next integration stage) -> FastAPI/WebSocket gateway -> PostgreSQL historical bars, snapshots and audit records (next integration stage) -> Flutter app and AIR research modules.

Historical and live sources are independent. A provider may supply historical candles while another supplies WebSocket ticks. Each record must retain provider, account, exchange timestamp and server receipt timestamp. Conflicting provider ticks must not be silently blended.

## Current implementation

- app/market_data/contracts.py: normalized instrument, tick and historical-bar contracts and provider adapter protocol.
- app/market_data/router.py: multiple provider/account registrations, independent historical/live source selection, priority routing and enable/disable.
- app/market_data/hub.py: WebSocket fan-out to AIR clients.
- app/main.py: health, data-status and WebSocket endpoints.
- Dockerfile: container image for the FastAPI gateway.

This is a backend foundation only. No live broker provider adapter, credential vault, Redis persistence/pub-sub, PostgreSQL storage, user authentication, subscription endpoint, or broker connection has been enabled yet. The status endpoint must not be mistaken for a connected feed.

## Deployment

Build and run on an always-on self-hosted Linux machine, NAS or VPS. Docker Compose/Swarm can host the gateway, Redis and PostgreSQL. Use TLS at the reverse proxy. Put secrets in Docker secrets or a proper secret manager, not in source control or Flutter.

## Security and operational requirements before production

- Authenticate and authorize every REST/WebSocket client.
- Encrypt broker credentials and tokens at rest; restrict access by user/account.
- Never expose provider credentials or raw broker payloads to the mobile app.
- Add per-provider connection limits, rate limiting, heartbeat, reconnect with backoff and subscription reconciliation.
- Add durable storage, tick freshness checks, duplicate detection and market-session controls.
- Respect each broker's API terms, data redistribution rules, subscription limits and exchange licensing.
- Keep order execution separately permissioned from market-data access. Paper mode remains default.
