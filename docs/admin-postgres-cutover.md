# Admin SQLite to PostgreSQL cutover runbook

## Safety status

The PostgreSQL Admin store is opt-in. Until migration and verification are complete, keep `AIR_ADMIN_DATABASE_URL_FILE` unset in the API service. The existing SQLite Admin database remains authoritative. Do not run this against production until a tested backup and maintenance window are available.

## Pre-cutover checks

1. Stop Admin write traffic or put the Admin console into maintenance mode.
2. Stop all Admin writers, take a consistent SQLite backup, and verify it by restoring it to an isolated scratch path and querying the restored tables. Preserve the original file read-only. Record the backup timestamp and SHA-256 checksum.
3. Provision a dedicated PostgreSQL database and create the Docker secrets `air_admin_database_url` and `air_admin_mfa_key`. The MFA key must be the same Fernet key used to encrypt existing SQLite MFA secrets. Back up any existing PostgreSQL target with a custom-format `pg_dump` and verify a restore to an isolated scratch database. Do not use a target containing conflicting Admin rows.
4. Apply Alembic migrations with `AIR_DATABASE_URL_FILE` pointing at the intended PostgreSQL database: `alembic upgrade head`.
5. Run the transfer from a controlled one-off container with the SQLite source mounted read-only: `AIR_ADMIN_SQLITE_PATH=/var/lib/air/auth.sqlite3 AIR_ADMIN_DATABASE_URL_FILE=/run/secrets/air_admin_database_url python -m app.scripts.migrate_admin_sqlite_to_postgres`.
6. Run integration tests against a disposable database using `AIR_TEST_ADMIN_DATABASE_URL`. Never point test variables at production.

## Reconciliation before activation

Compare source and target counts for all four tables: users, sessions, login limits and audit events. Verify every row and field using the migration tool. Resolve any conflict explicitly; the transfer is transactional and must roll back rather than overwrite a conflicting target row. Confirm MFA ciphertext is byte-identical and the configured MFA key decrypts it. Verify Admin bootstrap is one-time; verify password + TOTP login, TOTP replay rejection, session lookup, logout/revocation, password rotation (other sessions become invalid), role change, account disable and audit-event creation. Record the test result and timestamp for each check.

## Activation

Only after reconciliation and the above checks pass, add `AIR_ADMIN_DATABASE_URL_FILE: /run/secrets/air_admin_database_url` to the API service and mount the matching external Docker secret. Deploy one API replica with stop-first updates. Keep the SQLite backup untouched for the agreed rollback window. Do not scale the API horizontally until concurrency and shared-session tests pass.

## Rollback

1. Stop API writes and revert service configuration so `AIR_ADMIN_DATABASE_URL_FILE` is absent only if no post-cutover Admin writes need to be retained. If writes occurred, keep PostgreSQL authoritative until those changes have been reconciled into SQLite.
2. Redeploy the previous known-good image/configuration; the factory then selects the existing SQLite Admin store.
3. Confirm Admin login and session behavior against the preserved SQLite file.
4. Preserve PostgreSQL data and logs for diagnosis; do not delete or overwrite either database during rollback.
5. Reconcile any Admin changes made after cutover before a later retry. A config rollback alone does not copy post-cutover writes back into SQLite.

## Current limitations

This runbook covers Admin authentication only. Other SQLite-backed domains (accounts, broker credentials, QOC, instrument masters, orders and market data) remain separate migration work. Committing this procedure does not imply a live cutover, Swarm deployment or real-server login.