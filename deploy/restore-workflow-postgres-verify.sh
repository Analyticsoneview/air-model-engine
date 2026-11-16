#!/usr/bin/env bash
set -Eeuo pipefail

BACKUP_FILE="${1:?Usage: bash deploy/restore-workflow-postgres-verify.sh <backup.dump> [restore_database_name]}"
RESTORE_DB="${2:-air_restore_verify_$(date -u +%Y%m%d%H%M%S)}"
STACK_NAME="${AIR_STACK_NAME:-air}"
POSTGRES_SERVICE="${STACK_NAME}_postgres"

if [[ "$RESTORE_DB" == "air" || ! "$RESTORE_DB" =~ ^[a-zA-Z][a-zA-Z0-9_]{0,62}$ ]]; then
  echo "Restore target must be a new, non-production database name; 'air' is forbidden." >&2
  exit 1
fi
if [[ ! -s "$BACKUP_FILE" ]]; then
  echo "Backup file is missing or empty: $BACKUP_FILE" >&2
  exit 1
fi
if [[ -f "$BACKUP_FILE.sha256" ]]; then
  (cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$BACKUP_FILE").sha256")
fi

POSTGRES_CONTAINER="$(docker ps --filter "label=com.docker.swarm.service.name=$POSTGRES_SERVICE" --format '{{.ID}}' | head -n 1)"
if [[ -z "$POSTGRES_CONTAINER" ]]; then
  echo "No running PostgreSQL task found for Swarm service $POSTGRES_SERVICE." >&2
  exit 1
fi

EXISTS_SQL="SELECT 1 FROM pg_database WHERE datname = '$RESTORE_DB'"
EXISTS="$(docker exec "$POSTGRES_CONTAINER" sh -ec \
  'export PGPASSWORD="$(cat /run/secrets/air_postgres_password)"; exec psql -U air -d postgres -Atqc "$1"' \
  sh "$EXISTS_SQL")"
if [[ "$EXISTS" == "1" ]]; then
  echo "Restore target already exists; refusing to overwrite database $RESTORE_DB." >&2
  exit 1
fi

docker exec "$POSTGRES_CONTAINER" sh -ec \
  'export PGPASSWORD="$(cat /run/secrets/air_postgres_password)"; exec createdb -U air "$1"' \
  sh "$RESTORE_DB"

docker exec -i "$POSTGRES_CONTAINER" sh -ec \
  'export PGPASSWORD="$(cat /run/secrets/air_postgres_password)"; exec pg_restore --clean --if-exists --no-owner --no-acl -U air -d "$1"' \
  sh "$RESTORE_DB" < "$BACKUP_FILE"

VERIFY_SQL="DO \$\$ BEGIN
  IF to_regclass('public.air_workflow_definitions') IS NULL
     OR to_regclass('public.air_workflow_events') IS NULL
     OR to_regclass('public.air_workflow_outbox') IS NULL
     OR to_regclass('public.air_workflow_runs') IS NULL
     OR to_regclass('public.air_workflow_run_steps') IS NULL
     OR to_regclass('public.air_workflow_audit') IS NULL
     OR to_regclass('public.air_exchange_calendar') IS NULL
     OR to_regclass('public.air_workflow_worker_heartbeats') IS NULL THEN
    RAISE EXCEPTION 'Restored database is missing AIR workflow acceptance tables';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_air_workflow_runs_lease') THEN
    RAISE EXCEPTION 'Restored database is missing workflow lease index';
  END IF;
END; \$\$;"

docker exec "$POSTGRES_CONTAINER" sh -ec \
  'export PGPASSWORD="$(cat /run/secrets/air_postgres_password)"; exec psql -v ON_ERROR_STOP=1 -U air -d "$1" -c "$2"' \
  sh "$RESTORE_DB" "$VERIFY_SQL"

COUNTS_SQL="SELECT 'workflow_definitions=' || count(*) FROM air_workflow_definitions
UNION ALL SELECT 'events=' || count(*) FROM air_workflow_events
UNION ALL SELECT 'outbox=' || count(*) FROM air_workflow_outbox
UNION ALL SELECT 'runs=' || count(*) FROM air_workflow_runs
UNION ALL SELECT 'run_steps=' || count(*) FROM air_workflow_run_steps
UNION ALL SELECT 'audit=' || count(*) FROM air_workflow_audit
UNION ALL SELECT 'calendar_days=' || count(*) FROM air_exchange_calendar
UNION ALL SELECT 'worker_heartbeats=' || count(*) FROM air_workflow_worker_heartbeats"

docker exec "$POSTGRES_CONTAINER" sh -ec \
  'export PGPASSWORD="$(cat /run/secrets/air_postgres_password)"; exec psql -U air -d "$1" -At -c "$2"' \
  sh "$RESTORE_DB" "$COUNTS_SQL"

echo "PASS: backup restored and required AIR workflow tables/indexes verified in $RESTORE_DB."
echo "The verification database was retained for inspection; it was not swapped into production."
