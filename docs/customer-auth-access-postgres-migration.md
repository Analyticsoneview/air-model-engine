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
- Keep the SQLite file and a backup that has been restored and queried in an
  isolated scratch location. Stop all writers before taking the backup. The
  importer opens SQLite in read-only mode and never edits or deletes it.
- Use the same PostgreSQL database already initialized with Alembic revision
  `0001_admin_auth_schema`; revision `0002_customer_auth_access` follows it.

## Migration sequence

From the `backend` directory, using the dedicated customer database secret:

1. Stop API/worker writes to the source SQLite database. Take a consistent
   SQLite backup, restore it to an isolated scratch path and query the restored
   tables. Record its timestamp and SHA-256 checksum. Back up any existing
   PostgreSQL target with `pg_dump` and verify a restore to a scratch database.
   Set `AIR_CUSTOMER_DATABASE_URL_FILE` only in the one-off migration environment
   to a protected file containing the PostgreSQL URL. Do not put credentials in
   source control or a plain .env.
2. Apply the versioned schema: `alembic upgrade head`.
3. Import and reconcile the SQLite source:
   `AIR_CUSTOMER_SQLITE_PATH=data/air_auth.sqlite3 python -m app.scripts.migrate_customer_auth_sqlite_to_postgres`.
4. Review the per-table row counts. The importer verifies every primary-key row
   and every field, checks exact table row counts, and wraps the import in one
   PostgreSQL transaction. Any mismatch aborts and rolls back the import.
5. Run backend tests, then perform an application-level customer login, pending
   access request, Admin approval, approved-device session creation,
   blocked/rejected session revocation and subscription status test against the
   migrated database. Capture the result before activation.
6. Only then configure `AIR_CUSTOMER_DATABASE_URL_FILE` for the API service
   and restart a single API replica. Retain SQLite unchanged for rollback.

## Rollback

Stop API and worker writes first. If no post-cutover writes occurred, unset
`AIR_CUSTOMER_DATABASE_URL` and `AIR_CUSTOMER_DATABASE_URL_FILE`, then restart
the API to select the preserved SQLite stores. If any writes reached PostgreSQL,
keep PostgreSQL authoritative until those writes are reconciled into SQLite
through a reviewed reverse migration or application-level replay. Do not drop
PostgreSQL tables or remove the SQLite source during the rollback window. This
importer is a one-way initial import, not continuous replication.

## Tests

- SQLite behavior tests run without external services.
- PostgreSQL importer/store integration tests run only when
  `AIR_TEST_CUSTOMER_DATABASE_URL` points to a disposable PostgreSQL database
  with revision `0002_customer_auth_access` applied.
- Never point the integration-test URL at production.
