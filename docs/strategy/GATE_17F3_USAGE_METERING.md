# Gate 17F-3 — Usage metering and quotas

**Status:** Implementation branch; CI validation required.  
**Depends on:** Gate 17F-1 commercial catalogue and Gate 17F-2 contract ledger.  
**Safety:** No overage charging, no payment collection and no public price promises.

## Metered dimensions

- API calls (daily)
- Compute seconds (monthly)
- Storage bytes (monthly)
- Seats (monthly)
- Licensed-data bytes (monthly)

The versioned internal quota matrix maps each B2C/B2B catalogue plan to soft and hard limits. These are enforcement defaults, not public commercial commitments. Tenant-specific overrides support negotiated B2B entitlements and are writable only through the administrator quota-policy API.

## Ledger and enforcement

- `air_usage_events` is the immutable event ledger. Every event has a tenant, customer, metric, positive quantity, unit, period window, actor, metadata and tenant-scoped idempotency key.
- `air_usage_counters` stores transactionally maintained aggregates by tenant, metric and period.
- `air_usage_quota_overrides` stores audited custom tenant policy.
- PostgreSQL uses Alembic revision `0023_usage_metering_quotas`, tenant RLS and immutable event permissions. SQLite creates an equivalent local schema for self-hosted mode.
- The service serializes updates on the tenant/metric/period counter, records rejected attempts without counting them, and does not double-count idempotent retries.
- Soft-limit crossings are accepted with a warning signal. Hard-limit crossings are durably rejected. Unknown plans and metrics fail closed.
- Internal domain services call `UsageMeter.consume(...)` with a stable event idempotency key. This avoids trusting customer-submitted usage quantities. The usage API exposes current usage to customers and quota-policy changes to authenticated administrators.

## API

- `GET /api/v1/usage/me` — current tenant usage, limits and period boundaries.
- `PUT /api/v1/usage/admin/quotas` — administrator-only custom quota override.

## Acceptance

Unit tests cover period rollover, idempotency, hard and soft boundaries, tenant isolation, unknown plans, invalid quantities and custom quota validation. PostgreSQL migration/RLS and full deployment acceptance are required before merge.
