#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="${AIR_STACK_NAME:-air}"
BACKUP_DIR="${AIR_WORKFLOW_BACKUP_DIR:-/var/backups/air/workflows}"
POSTGRES_SERVICE="${STACK_NAME}_postgres"

umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

POSTGRES_CONTAINER="$(docker ps --filter "label=com.docker.swarm.service.name=$POSTGRES_SERVICE" --format '{{.ID}}' | head -n 1)"
if [[ -z "$POSTGRES_CONTAINER" ]]; then
  echo "No running PostgreSQL task found for Swarm service $POSTGRES_SERVICE." >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="$BACKUP_DIR/air-postgres-$STAMP.dump"
TEMP_FILE="$BACKUP_FILE.partial"
trap 'rm -f "$TEMP_FILE"' EXIT

docker exec "$POSTGRES_CONTAINER" sh -ec \
  'export PGPASSWORD="$(cat /run/secrets/air_postgres_password)"; exec pg_dump -U air -d air --format=custom --no-owner --no-acl' \
  > "$TEMP_FILE"

if [[ ! -s "$TEMP_FILE" ]]; then
  echo "PostgreSQL backup archive is empty; refusing to publish it." >&2
  exit 1
fi

mv "$TEMP_FILE" "$BACKUP_FILE"
sha256sum "$BACKUP_FILE" > "$BACKUP_FILE.sha256"
chmod 600 "$BACKUP_FILE" "$BACKUP_FILE.sha256"
trap - EXIT

echo "Created protected PostgreSQL backup: $BACKUP_FILE"
echo "Checksum: $BACKUP_FILE.sha256"
echo "The backup has not been copied off-host; configure encrypted off-host retention separately."
