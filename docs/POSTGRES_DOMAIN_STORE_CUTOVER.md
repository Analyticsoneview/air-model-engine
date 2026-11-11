# PostgreSQL domain-store migration and cutover

## Scope of this phase

This phase adds PostgreSQL storage for four existing SQLite repositories:

- Encrypted broker credentials (broker_credentials)
- Customer broker accounts and market-data entitlements/selections
- AIR execution policy (master switch and EXPIRY78 / EXPIRYSCAN / RECOVERED switches)
- Durable order intents, broker results and order events

SQLite remains the default for these four repositories when their dedicated PostgreSQL selectors are absent. Customer identity/access and Admin authentication are separate migrations in the startup sequence: the API launcher switches those two stores to PostgreSQL only after their import scripts complete successfully.

## Backup and preflight — mandatory before import

1. Schedule a maintenance window. Stop or quiesce every API, worker, scheduler and other process that can write to the four SQLite databases. Do not take four independent live copies while writers are active.
2. Create consistent SQLite backups for all four source databases using SQLite's online backup API, or copy the files only after all writers have stopped and the databases are closed:
   - `/var/lib/air/credentials.sqlite3`
   - `/var/lib/air/accounts.sqlite3`
   - `/var/lib/air/air_execution_policy.sqlite3`
   - `/var/lib/air/orders.sqlite3`
3. Verify each backup can be opened and queried. Record the backup timestamp, file size and SHA-256 checksum. Preserve the original source files unchanged.
4. Back up the existing Fernet credential key as a protected Docker secret or equivalent restricted secret backup. The importer needs the existing key to decrypt and verify credentials; do not rotate it as part of this migration and never print it in logs.
5. Back up the PostgreSQL target before schema or data changes where it contains any pre-existing AIR data. Use a custom-format `pg_dump` and verify the dump can be listed and restored to an isolated scratch database. The domain importer requires its target tables to be empty; use a dedicated target database or a reviewed clean schema rather than deleting existing production rows.
6. Record the source file paths and checksums, PostgreSQL target identity, Alembic revision, image version and maintenance-window owner in the change record.

## Required order

1. Ensure the PostgreSQL database URL is available to the API/one-off migration container as `AIR_DATABASE_URL_FILE` or `AIR_DATABASE_URL`.
2. Run Alembic migrations:
   ```powershell
   python -m alembic upgrade head
   ```
3. Before running the importer, set the existing SQLite source-file paths to the exact mounted files used by the current Compose/Swarm deployment:
   - `AIR_CREDENTIAL_DB_PATH=/var/lib/air/credentials.sqlite3`
   - `AIR_ACCOUNT_DB_PATH=/var/lib/air/accounts.sqlite3`
   - `AIR_EXECUTION_POLICY_DB_PATH=/var/lib/air/air_execution_policy.sqlite3`
   - `AIR_ORDER_DB_PATH=/var/lib/air/orders.sqlite3`

   Run the importer from the backend directory with those variables and the existing `AIR_CREDENTIAL_KEY_FILE` available. First run it in dry-run mode against the mounted data volume:
   ```powershell
   python scripts/import_sqlite_domain_stores.py --source-data-dir data --dry-run
   ```
4. Review the per-table source row counts, target-empty checks and credential decryption validation. `DRY_RUN_VALIDATED` means validation passed without writing rows; it is not a completed import. If any source path, count or credential check is unexpected, stop and resolve it before proceeding.
5. If the dry-run is clean and the backups are verified, run the importer without `--dry-run`:
   ```powershell
   python scripts/import_sqlite_domain_stores.py --source-data-dir data
   ```
6. Require `IMPORTED_AND_RECONCILED`. The importer verifies row counts and every imported field, decrypts the copied credential ciphertext with the existing Fernet key, and records a content fingerprint for each imported table. A later run returns `ALREADY_IMPORTED` only if the source paths, row counts and imported source content still match the recorded manifest. Any changed source content causes a hard stop.
7. Take a post-import PostgreSQL backup and verify it can be restored to an isolated scratch database before switching application selectors.
8. After successful import and restore verification, configure these selectors for the API service. They may all point to the same PostgreSQL secret:
   ```text
   AIR_CREDENTIAL_DATABASE_URL_FILE=/run/secrets/air_database_url
   AIR_CUSTOMER_ACCOUNTS_DATABASE_URL_FILE=/run/secrets/air_database_url
   AIR_EXECUTION_POLICY_DATABASE_URL_FILE=/run/secrets/air_database_url
   AIR_ORDER_LEDGER_DATABASE_URL_FILE=/run/secrets/air_database_url
   ```
9. Keep automatic execution disabled. Confirm the execution master switch and EXPIRY78 / EXPIRYSCAN / RECOVERED switches are all disabled before deployment. Restart one API replica using stop-first deployment and verify customer accounts, broker credential reads, execution policy and order-ledger reads. Do not enable live broker order placement as part of this migration.
10. Observe the agreed validation window, compare application-level counts and logs, then scale out only after the single-replica checks pass.

**Alternative one-time startup cutover:** after taking and verifying backups and reviewing the dry-run, set `AIR_DOMAIN_STORES_IMPORT_ON_STARTUP=true` in the deployment environment and restart once. The startup script runs the importer before starting FastAPI and, only if it succeeds, exports all four repository selectors to `AIR_DATABASE_URL_FILE` for that API process. Leave this switch `false` for normal restarts after cutover; the selectors are then supplied by the launcher. The default remains `false`. The same maintenance, backup, reconciliation and post-import restore checks remain mandatory.

## Importer safety

- All four expected SQLite source databases must exist; a missing file stops the import instead of silently treating that repository as empty.
- SQLite source files are opened with SQLite read-only URI mode and query-only enforcement; they are never modified, deleted or renamed.
- The importer refuses to write if any target table is non-empty.
- Credential ciphertext is copied byte-for-byte; the Fernet key is not rotated.
- Credential ciphertext is decrypted before and after import to prove the existing key still works.
- It checks source and target row counts and field-by-field equality inside one PostgreSQL transaction.
- The source manifest includes a SHA-256 digest of imported column values, not just file paths and row counts. Same-count source edits after import are detected and rejected.
- If any check fails, the PostgreSQL transaction rolls back and the source SQLite files remain intact.
- A successful import writes a one-time migration marker in PostgreSQL; subsequent startup runs return `ALREADY_IMPORTED` only when the recorded source manifest still matches.

## Rollback

1. Stop API writes, workers and schedulers. Record the exact cutover timestamp and PostgreSQL backup identifier.
2. Do not roll back by simply unsetting selectors if any writes may have reached PostgreSQL. That would hide post-cutover data from the SQLite-backed application.
3. If no post-cutover writes occurred, restore the coordinated pre-cutover PostgreSQL backup (or retain the untouched target) and revert the API service configuration so the repository-specific selectors are absent. Redeploy the previous known-good image/configuration.
4. If post-cutover writes occurred, keep PostgreSQL authoritative while those changes are reconciled into SQLite through a reviewed reverse migration or application-level replay. Do not resume SQLite writes until row counts and field-level comparisons are signed off.
5. Verify Admin/customer access, account reads, credentials, execution policy and order-ledger reads against the selected store. Preserve both database copies and logs for diagnosis; do not delete or overwrite either source.
6. Keep automatic execution and live broker order placement disabled throughout rollback and recovery.

## Important cutover warning

The general `AIR_DATABASE_URL` controls connectivity and migrations; it does not by itself migrate or switch these repositories. The four repository-specific selectors above are the explicit cutover switches. Production import, selector changes and Swarm rollout require an approved maintenance window and explicit operator authorization.

Live broker order placement remains disabled. This migration provides durable storage and idempotency foundations; it does not approve live execution.
