# AIR Customer PostgreSQL Storage and SQLite Cutover

## What this changes

The customer access store now has a PostgreSQL implementation selected only when
`AIR_CUSTOMER_DATABASE_URL` or `AIR_CUSTOMER_DATABASE_URL_FILE` is explicitly
configured. The existing SQLite implementation remains the default for compatibility.

Alembic revision `0002_customer_access_schema` creates the six customer tables:
access requests, device sessions, subscriptions, marketing preferences, offers and
marketing audit. The migration utility copies rows in one PostgreSQL transaction,
opens the SQLite source read-only, is safe to re-run, and rejects conflicting target
rows rather than overwriting them.

## CI validation

The disposable PostgreSQL integration workflow applies `alembic upgrade head`,
then tests both Admin and customer stores against temporary PostgreSQL/Redis
services. Customer tests cover access request deduplication, approval, session
creation and revocation, customer consent, subscription segmentation, offer
approval/revocation, persistence after reconnect, and idempotent SQLite import.

## Local cutover — do not enable the customer PostgreSQL selector before migration

1. Stop the API to prevent concurrent writes and make a separate backup copy of
   `/var/lib/air/auth.sqlite3`. Keep the original file and backup.
2. Apply Alembic migrations using the existing database URL secret:
   `docker compose -f compose.local.yml run --rm --no-deps --entrypoint python air-api -m alembic upgrade head`
3. Copy the SQLite customer data. The command uses the mounted data volume and
   existing database URL secret; it does not print the URL:
   `docker compose -f compose.local.yml run --rm --no-deps -e AIR_CUSTOMER_DATABASE_URL_FILE=/run/secrets/air_database_url -e AIR_CUSTOMER_SQLITE_PATH=/var/lib/air/auth.sqlite3 --entrypoint python air-api -m app.scripts.migrate_customer_sqlite_to_postgres`
4. Confirm all six reported row counts, then run the customer integration tests
   against the same PostgreSQL database. Do not delete or rename the SQLite source.
5. Only after successful migration and verification, configure
   `AIR_CUSTOMER_DATABASE_URL_FILE=/run/secrets/air_database_url` for the API
   service and restart it. Confirm customer login, Admin access review, session
   revocation, subscription reads, consent and offer management.
6. Retain the SQLite backup through the agreed rollback window. Rollback means
   restoring the previous application configuration to SQLite; do not attempt to
   write PostgreSQL data back into the old SQLite file.

For local operations, stop/start the API explicitly around the maintenance window.
The migration itself does not delete, rename, or modify the source SQLite database.
