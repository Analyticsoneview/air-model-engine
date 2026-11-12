#!/bin/sh
set -eu

cd /app
python -m scripts.migrate_all

# Customer and Admin auth migrations are part of every PostgreSQL startup.
# Point the API at those stores only after migrate_all completed successfully.
: "${AIR_DATABASE_URL_FILE:?AIR_DATABASE_URL_FILE is required for PostgreSQL auth stores}"
export AIR_CUSTOMER_DATABASE_URL_FILE="${AIR_CUSTOMER_DATABASE_URL_FILE:-$AIR_DATABASE_URL_FILE}"
export AIR_ADMIN_DATABASE_URL_FILE="${AIR_ADMIN_DATABASE_URL_FILE:-$AIR_DATABASE_URL_FILE}"

# When an operator explicitly opts into the one-time domain-store cutover,
# point the API repositories at the same PostgreSQL secret after import succeeds.
if [ "${AIR_DOMAIN_STORES_IMPORT_ON_STARTUP:-false}" = "true" ] || [ "${AIR_DOMAIN_STORES_IMPORT_ON_STARTUP:-false}" = "1" ]; then
  : "${AIR_DATABASE_URL_FILE:?AIR_DATABASE_URL_FILE is required for PostgreSQL cutover}"
  export AIR_CREDENTIAL_DATABASE_URL_FILE="${AIR_CREDENTIAL_DATABASE_URL_FILE:-$AIR_DATABASE_URL_FILE}"
  export AIR_CUSTOMER_ACCOUNTS_DATABASE_URL_FILE="${AIR_CUSTOMER_ACCOUNTS_DATABASE_URL_FILE:-$AIR_DATABASE_URL_FILE}"
  export AIR_EXECUTION_POLICY_DATABASE_URL_FILE="${AIR_EXECUTION_POLICY_DATABASE_URL_FILE:-$AIR_DATABASE_URL_FILE}"
  export AIR_ORDER_LEDGER_DATABASE_URL_FILE="${AIR_ORDER_LEDGER_DATABASE_URL_FILE:-$AIR_DATABASE_URL_FILE}"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
