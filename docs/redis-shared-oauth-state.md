# Shared broker OAuth state

AIR stores the one-time state values used by the Upstox and FYERS authorization-code flows for ten minutes.

## Production / multi-worker configuration

Configure `AIR_REDIS_URL_FILE` to point to a Docker/Swarm secret containing the Redis connection URL. The existing local Compose and Swarm manifests already mount this setting as `/run/secrets/air_redis_url`. Do not put Redis passwords or connection URLs in source control.

When Redis is configured:
- OAuth state is stored under a SHA-256-derived key; customer and broker account identifiers are not exposed in Redis key names.
- The state expires after 600 seconds.
- The exchange endpoint performs an atomic compare-and-delete, so only the matching state can be consumed and a wrong state does not invalidate the legitimate state.
- A second successful use is rejected.
- If Redis is unavailable, login URL issuance and code exchange fail closed with HTTP 503. AIR does not silently fall back to process-local state in a configured multi-worker deployment.

When Redis is not configured, a process-local fallback remains for single-worker local development only. It is not suitable for multiple backend workers or replicas.

## Session and login-throttling boundaries

Administrator sessions and administrator login throttling already use Redis in the PostgreSQL administrator store when Redis is configured. PostgreSQL remains the durable source of truth for session revocation and administrator records. Customer device-session approval and revocation remain persisted in the selected customer database; PostgreSQL mode therefore shares session state across backend instances without relying on a local process cache.

This change does not migrate the SQLite administrator store, broker credential vault, customer account directory, orders, QOC, instrument masters or market-data repositories. It does not enable automatic order placement or perform a production data cutover.
