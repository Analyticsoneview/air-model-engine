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
