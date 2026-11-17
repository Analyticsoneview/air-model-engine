# PostgreSQL / Redis domain-store integration reconciliation

**Status:** IN PROGRESS — integration branch `integration/postgres-redis-domain-stores`  
**Base:** `main` at `efec317ae0ca2ace6791fd7aad33da4b10b1673b`  
**Purpose:** Reconcile historical PRs #19, #20, #21 and #35 without replaying stale migration history or duplicating code already merged to main.

## Scope and merge policy

This is one coordinated integration effort, not four independent merges. Historical PRs are source references. Only functionality demonstrably missing from current main is ported. Existing migration revisions and already-merged gate work are preserved.

No production database import/cutover, live broker order submission, automatic execution, or cloud resource creation is authorized by this work.

## Reconciliation

| Historical PR | Intended capability | Current-main finding | Action |
|---|---|---|---|
| #19 | Customer authentication and device access in PostgreSQL | Customer device access, subscription and lifecycle stores plus PostgreSQL migration chain are already present. The email/password `AuthStore` still defaults to SQLite and has no PostgreSQL credentials table. | Port only the missing customer credential store and migration; retain existing customer-access implementation. |
| #20 | Shared Redis OAuth state for Upstox/FYERS | Current main still keeps OAuth state in process-local dictionaries; no shared OAuth state module exists. | Port Redis-backed state, atomic compare-and-delete, 10-minute expiry and fail-closed Redis behavior. |
| #21 | Broker credential/account and execution PostgreSQL stores | Current main already contains PostgreSQL selectors and repositories for credentials, accounts, execution policy and order ledger, with migration coverage and integration tests. | Do not replay the old branch. Verify the current-main implementation with disposable PostgreSQL integration. |
| #35 | QOC, instrument, provider/failover and execution persistence | Current main already contains migrations 0004–0007 and PostgreSQL selectors/repositories for these stores. PR #35 proposes overlapping migration IDs. | Do not copy its migrations. Verify current-main implementations and only port any proven missing tests or fixes. |

## Changes in this integration slice

1. Add Alembic revision `0029_customer_credentials` after `0028_enterprise_license`; it creates the customer credential table and case-insensitive unique email index.
2. Add a PostgreSQL implementation of the existing `AuthStore` contract, selected only when `AIR_CUSTOMER_DATABASE_URL` or `AIR_CUSTOMER_DATABASE_URL_FILE` is explicitly configured.
3. Preserve explicit SQLite paths and the local SQLite default.
4. Add customer credential PostgreSQL round-trip, activation and duplicate-email tests.
5. Add `OAuthStateStore`: Redis TTL, hashed identity keys, atomic compare-and-delete, invalid-attempt preservation, single-use state, local single-worker development fallback, and fail-closed configured Redis outages.
6. Replace the Upstox and FYERS process-local callback-state dictionaries with the shared store.
7. Extend the disposable PostgreSQL/Redis acceptance workflow to run these tests.

## Required acceptance before merge

- Full backend unittest and pytest suites.
- Alembic upgrade to the single expected head, including revision 0029.
- Customer credential PostgreSQL integration against the disposable database.
- Customer access and admin PostgreSQL integration regressions.
- Broker credential/account, QOC, instrument, provider/failover, execution-policy and order-ledger PostgreSQL integration regressions.
- Real Redis OAuth shared-state, expiry and one-time-consumption integration.
- Compose/Swarm configuration and existing deployment checks.
- Exact-head green required checks; no skipped required integration acceptance.

## Remaining work after this slice

- Review CI results and correct defects before expanding the PR.
- Inspect whether any additional behavior from historical #19–#21 is absent from current main; port only evidence-backed gaps.
- Confirm #21/#35 functionality through current-main tests rather than creating duplicate migrations.
- Close or mark superseded historical PRs only after the replacement integration is merged and verified.
- Keep the four original PRs unmerged until this reconciliation is complete.

## Deployment boundary

PostgreSQL and Redis integration tests use disposable CI services. Runtime selection remains opt-in through secret-backed database/Redis URL settings. No production cutover is performed. Redis is required for shared OAuth state when configured; a Redis outage returns an unavailable error rather than silently falling back to process-local state.
