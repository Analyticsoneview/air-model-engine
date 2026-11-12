# Customer authentication and device-access PostgreSQL migration

This gate migrates only the `customers`, `air_access_requests`, and
`air_device_sessions` repositories. Broker credentials, customer accounts,
account reporting, QOC, instrument masters, orders, market-data repositories,
and Redis shared state are explicitly out of scope.

## Safety and selection

- SQLite remains the default and remains the source of truth.
- PostgreSQL is selected only when `AIR_CUSTOMER_DATABASE_URL` or
  `AIR_CUSTOMER_DATABASE_URL_FILE` is explicitly configured.
- Do not set the runtime PostgreSQL URL until the schema is migrated and the
  source import/reconciliation has passed.
- Keep the SQLite file and a verified backup. The importer opens SQLite in
  read-only mode and never edits or deletes it.
- Use the same PostgreSQL database already initialized with Alembic revision
  `0001_admin_auth_schema`; revision `0002_customer_auth_access` follows it.

## Migration sequence

From the `backend` directory, using the dedicated customer database secret:

1. Set `AIR_CUSTOMER_DATABASE_URL_FILE` to a protected file containing the
   PostgreSQL URL. Do not put credentials in source control or a plain .env.
2. Apply the versioned schema: `alembic upgrade head`.
3. Import and reconcile the SQLite source:
   `AIR_CUSTOMER_SQLITE_PATH=data/air_auth.sqlite3 python -m app.scripts.migrate_customer_auth_sqlite_to_postgres`.
4. Review the per-table row counts. The importer verifies every primary-key row
   and every field, checks exact table row counts, and wraps the import in one
   PostgreSQL transaction. Any mismatch aborts and rolls back the import.
5. Run backend tests, then perform an application-level login, pending access,
   admin approval, session creation, and session revocation test against the
   migrated database.
6. Only then configure `AIR_CUSTOMER_DATABASE_URL_FILE` for the API service
   and restart a single API replica. Retain SQLite unchanged for rollback.

## Rollback

Unset `AIR_CUSTOMER_DATABASE_URL` and `AIR_CUSTOMER_DATABASE_URL_FILE`, then
restart the API to select the existing SQLite stores. Do not drop PostgreSQL
tables or remove the SQLite source during the rollback window. Reconcile any
writes made after cutover before attempting a later cutover; this importer is
a one-way initial import, not continuous replication.

## Tests

- SQLite behavior tests run without external services.
- PostgreSQL importer/store integration tests run only when
  `AIR_TEST_CUSTOMER_DATABASE_URL` points to a disposable PostgreSQL database
  with revision `0002_customer_auth_access` applied.
- Never point the integration-test URL at production.
