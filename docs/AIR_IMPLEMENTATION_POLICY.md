# AIR Implementation and Release Policy

**Status:** Mandatory engineering policy  
**Applies to:** Backend, broker adapters, strategy engines, persistence, Android, deployment and release work.

## 1. Safety defaults

- Broker order submission and automatic execution remain disabled by default.
- Manual-order capability is not permission to submit a broker order. A broker order may only be routed through the authenticated account and explicit server-side execution gates.
- Tests must use fakes, mocks or disposable accounts. Never enable live broker trading to satisfy CI.
- No strategy, API, UI, environment variable or test shortcut may silently enable live orders.
- Keep the kill switch fail-closed. Missing authorization, stale or missing quotes, invalid instruments, missing risk inputs, unavailable persistence, or broker uncertainty must reject or hold execution.
- Preserve manual-first workflows and customer/admin authorization boundaries.

## 2. Evidence and strategy integrity

- Preserve each strategy's documented entry, exit, stop-loss, expiry and eligibility rules.
- Do not weaken the minimum of 10 verified trading sessions to expiry.
- Do not replace missing market/option replay evidence with estimates, weekday assumptions, fabricated prices or inferred outcomes.
- Missing or incomplete evidence must produce an explicit WAIT / unresolved / insufficient-data state.
- Preserve original strategy results separately from retrospective alternative exit simulations. A simulation must never be represented as a live position, re-entry or broker order.
- Expiry settlement outcomes require verified expiry-day underlying close data.

## 3. Required implementation sequence

1. Complete implementation in a coherent batch; review the diff and add targeted tests.
2. Run the clean backend test suite and backend static/contract validations.
3. Run Android analysis, unit/widget tests and the release APK build.
4. Run PostgreSQL disposable-database integration, migrations, import/reconciliation and rollback/conflict tests.
5. Run Redis integration for shared OAuth state, expiry, single-use consumption, sessions and throttling.
6. Deploy to the self-hosted Docker Swarm environment; verify health, secrets, persistence and restart/recovery behavior.
7. Perform real Super Admin bootstrap/login, authenticator enrollment, session restore/revocation and customer/device approval checks.
8. Review PRs and release evidence; create the final ZIP only after every applicable gate passes.

Backend gates must pass before Android release build. Do not merge PR #16. Do not perform production cutover or customer distribution before the required gates and explicit approval.

## 4. CI efficiency and evidence

- Group related implementation changes before starting validation.
- Do not launch a full validation workflow for each small commit.
- Use the consolidated validation workflow once the implementation batch is ready; rerun only failed jobs when the failure is isolated and the source SHA is unchanged.
- Record the exact commit SHA, workflow/run IDs, job results, test counts, artifact identity and checksum.
- Distinguish PR validation from Package CI. An old successful run or artifact does not validate a newer commit.
- A skipped, queued, cancelled or unavailable gate is not a pass.

## 5. Persistence migration policy

- Keep SQLite as the default until an explicit, verified migration and cutover.
- Test PostgreSQL migrations and importers against disposable databases first.
- Require dry-run, source backup, target-empty checks, transactional import, exact row/field reconciliation and rollback/conflict tests.
- Keep original SQLite sources read-only and retained until reconciliation and rollback readiness are accepted.
- Never claim production cutover based only on unit tests or a green migration job.

## 6. Broker adapter contract

- Each provider adapter must be account-scoped and normalize authentication, quotes, positions, holdings, order book and order lifecycle responses.
- Validate provider account identity after authentication.
- Do not manufacture prices, quantities, timestamps, order IDs or success statuses when the provider omits them.
- Preserve idempotency keys exactly within provider constraints; reject unsupported lengths rather than truncating keys and risking collisions.
- Validate provider-specific exchange segment, product, order type, validity, quantity, tick/lot constraints and required prices before any order route.
- Adapter implementation and tests do not imply that broker order submission is enabled.

## 7. Release completion criteria

A release is complete only when all required gates above have recorded passing evidence, the self-hosted installation and real login have been verified, the Android artifact is built from the same validated commit, and the final package includes all existing AIR features, release notes, installation/recovery instructions and checksums.

Until then, report the exact incomplete gates and blockers. Never describe a partial implementation as complete.
