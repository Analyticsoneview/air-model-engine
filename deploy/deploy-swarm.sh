#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="${AIR_STACK_NAME:-air}"
ENV_FILE="${AIR_DEPLOY_ENV_FILE:-/etc/air/air.env}"

if [[ ! -r "$ENV_FILE" ]]; then
  echo "Required server environment file is missing or unreadable: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${AIR_BACKEND_IMAGE:?AIR_BACKEND_IMAGE must be supplied by the deployment workflow}"
: "${AIR_PWA_IMAGE:?AIR_PWA_IMAGE must be supplied by the deployment workflow}"
: "${AIR_OPERATOR_CUSTOMER_IDS:?Set AIR_OPERATOR_CUSTOMER_IDS in $ENV_FILE}"
: "${AIR_TELEGRAM_CHAT_IDS:?Set AIR_TELEGRAM_CHAT_IDS in $ENV_FILE}"

state="$(docker info --format '{{.Swarm.LocalNodeState}}')"
if [[ "$state" != "active" ]]; then
  echo "Docker Swarm is not active on this host (state: $state)." >&2
  exit 1
fi

if ! docker secret inspect air_jwt_secret >/dev/null 2>&1 ||
   ! docker secret inspect air_credential_key >/dev/null 2>&1 ||
   ! docker secret inspect air_admin_api_key >/dev/null 2>&1 ||
   ! docker secret inspect air_telegram_bot_token >/dev/null 2>&1; then
  echo "One or more required Docker Swarm secrets are missing. Complete deploy/DOCKER_SWARM.md first." >&2
  exit 1
fi

echo "Pulling immutable AIR images..."
docker pull "$AIR_BACKEND_IMAGE"
docker pull "$AIR_PWA_IMAGE"

echo "Applying Docker Swarm stack '$STACK_NAME'..."
docker stack deploy --with-registry-auth --prune -c docker-stack.yml "$STACK_NAME"

for service in "${STACK_NAME}_air-api" "${STACK_NAME}_air-pwa"; do
  ready=0
  replicas=""
  container_id=""
  health=""
  for attempt in $(seq 1 36); do
    replicas="$(docker service ls --filter "name=$service" --format '{{.Replicas}}' | head -n 1)"
    if [[ "$replicas" == "1/1" ]]; then
      container_id="$(docker ps --filter "label=com.docker.swarm.service.name=$service" --format '{{.ID}}' | head -n 1)"
      if [[ -n "$container_id" ]]; then
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_id")"
        if [[ "$health" == "healthy" ]]; then
          ready=1
          break
        fi
      fi
    fi
    sleep 5
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "Service did not become healthy: $service (replicas: ${replicas:-not found}, health: ${health:-unknown})" >&2
    docker service ps "$service" --no-trunc || true
    exit 1
  fi
done

echo "AIR Swarm services report 1/1 replicas:"
docker service ls --filter "label=com.docker.stack.namespace=$STACK_NAME"
