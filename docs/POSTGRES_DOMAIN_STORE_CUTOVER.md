# PostgreSQL domain-store migration and cutover

## Scope of this phase

This phase adds PostgreSQL storage for four existing SQLite repositories:

- Encrypted broker credentials (broker_credentials)
- Customer broker accounts and market-data entitlements/selections
- AIR execution policy (master switch and EXPIRY78 / EXPIRYSCAN / RECOVERED switches)
- Durable order intents, broker results and order events

SQLite remains the default when the repository-specific PostgreSQL selector is absent. The migration does not silently switch existing deployments to an empty PostgreSQL database.

## Required order

1. Back up the SQLite files and the PostgreSQL database.
2. Ensure the PostgreSQL database URL is available to the API container as AIR_DATABASE_URL_FILE or AIR_DATABASE_URL.
3. Run Alembic migrations:
   ```powershell
   python -m alembic upgrade head
   ```
4. Before running the importer, set the existing SQLite source-file paths to the exact mounted files used by the current Compose deployment. The current local and Swarm manifests use these paths:
   - `AIR_CREDENTIAL_DB_PATH=/var/lib/air/credentials.sqlite3`
   - `AIR_ACCOUNT_DB_PATH=/var/lib/air/accounts.sqlite3`
   - `AIR_EXECUTION_POLICY_DB_PATH=/var/lib/air/air_execution_policy.sqlite3`
   - `AIR_ORDER_DB_PATH=/var/lib/air/orders.sqlite3`

   Run the importer from the backend directory with those variables and the existing `AIR_CREDENTIAL_KEY_FILE` available. Then run it in dry-run mode against the mounted data volume:
   ```powershell
   python scripts/import_sqlite_domain_stores.py --source-data-dir data --dry-run
   ```
5. Review source counts, target-empty checks and credential decryption validation. If the report is clean, run the importer without --dry-run:
   ```powershell
   python scripts/import_sqlite_domain_stores.py --source-data-dir data
   ```
6. Confirm the importer reports IMPORTED_AND_RECONCILED. It verifies row counts and every imported field, and decrypts the copied credential ciphertext with the existing Fernet key.
7. Only after successful import, configure these selectors for the API service. They may all point to the same PostgreSQL secret:
   ```text
   AIR_CREDENTIAL_DATABASE_URL_FILE=/run/secrets/air_database_url
   AIR_CUSTOMER_ACCOUNTS_DATABASE_URL_FILE=/run/secrets/air_database_url
   AIR_EXECUTION_POLICY_DATABASE_URL_FILE=/run/secrets/air_database_url
   AIR_ORDER_LEDGER_DATABASE_URL_FILE=/run/secrets/air_database_url
   ```
8. Restart the API service and verify customer accounts, broker credential reads, execution policy and order-ledger reads before allowing writes.

## Importer safety

- Source SQLite files are read-only and are not deleted or renamed.
- The importer refuses to write if any target table is non-empty.
- Credential ciphertext is copied byte-for-byte; the Fernet key is not rotated.
- Credential ciphertext is decrypted before and after import to prove the existing key still works.
- It checks source and target row counts and field-by-field equality.
- If any check fails, the PostgreSQL transaction rolls back and the source SQLite files remain intact.
- A successful import writes a one-time migration marker in PostgreSQL; subsequent startup runs return ALREADY_IMPORTED without re-reading legacy credentials or importing again.

## Important cutover warning

After the application starts writing to PostgreSQL, unsetting the selectors and returning to SQLite would lose writes made after cutover. Do not roll back by simply switching the environment variables. Preserve the PostgreSQL database and perform a reconciled reverse migration or restore a coordinated backup.

The API currently reads the general AIR_DATABASE_URL for connectivity and migrations. That alone does not migrate or switch these repositories. The four repository-specific selectors above are the explicit cutover switches.

Live broker order placement remains disabled. This migration provides durable storage and idempotency foundations; it does not approve live execution.
