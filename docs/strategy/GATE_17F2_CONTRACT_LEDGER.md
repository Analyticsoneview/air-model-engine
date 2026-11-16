# Gate 17F-2 — Annual contract lifecycle ledger

**Status:** Implementation branch; CI validation required.  
**Scope:** Durable annual contract records and append-only lifecycle events.  
**Non-goals:** Payment collection, provider webhooks, price publication, automatic renewals, or paid research activation.

## Data model

- Contract: tenant/customer, product and plan codes, annual billing period, optional currency and amount (minor units), start/end/grace dates, lifecycle status, renewal preference, provider references, timestamps and optimistic version.
- Event: immutable actor, event type, prior/next status, idempotency key, JSON payload and occurrence timestamp.
- PostgreSQL production migration: `0022_commercial_contract_ledger`.
- SQLite local/self-hosted fallback: created idempotently by the store.

Annual periods use calendar-year arithmetic; a 29 February start ends on 28 February in a non-leap year.

## Lifecycle

`DRAFT → TRIAL | ACTIVE | CANCELLED`  
`TRIAL → ACTIVE | CANCELLED | EXPIRED | SUSPENDED`  
`ACTIVE → GRACE | PAST_DUE | CANCELLED | EXPIRED | SUSPENDED`  
`GRACE → ACTIVE | PAST_DUE | CANCELLED | EXPIRED | SUSPENDED`  
`PAST_DUE → ACTIVE | GRACE | CANCELLED | EXPIRED | SUSPENDED`  
`SUSPENDED → ACTIVE | CANCELLED | EXPIRED`  
`CANCELLED` and `EXPIRED` are terminal.

Every transition is checked against the matrix and requires an idempotency key. Events are append-only at the application layer; PostgreSQL RLS scopes both tables to the tenant. Event updates/deletes are revoked from PUBLIC.

## API

- `POST /api/v1/commercial/contracts`
- `GET /api/v1/commercial/contracts`
- `GET /api/v1/commercial/contracts/{contract_id}`
- `GET /api/v1/commercial/contracts/{contract_id}/events`
- `POST /api/v1/commercial/contracts/{contract_id}/transitions`

The API derives tenant identity from active PostgreSQL membership when configured. Local SQLite currently uses the authenticated customer identity as an isolated workspace; Gate 17F-7 will add organisation and seat-level administration.

## Acceptance

Tests cover leap-year periods, create idempotency, legal/illegal transitions, immutable history, tenant-scoped lookup, and negative amounts. PostgreSQL migration-chain and tenant-RLS acceptance remain required in CI.
