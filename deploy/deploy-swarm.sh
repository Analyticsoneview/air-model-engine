#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="${AIR_STACK_NAME:-air}"
ENV_FILE="${AIR_DEPLOY_ENV_FILE:-/etc/air/air.env}"

if [[ ! -r "$ENV_FILE" ]]; then
  echo "Required server environment file is missing or unreadable: $ENV_FILE" >&2
  exit 1
fi

# Preserve immutable image overrides supplied by the GitHub deployment workflow.
OVERRIDE_BACKEND_IMAGE="${AIR_BACKEND_IMAGE:-}"
OVERRIDE_PWA_IMAGE="${AIR_PWA_IMAGE:-}"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
if [[ -n "$OVERRIDE_BACKEND_IMAGE" ]]; then AIR_BACKEND_IMAGE="$OVERRIDE_BACKEND_IMAGE"; fi
if [[ -n "$OVERRIDE_PWA_IMAGE" ]]; then AIR_PWA_IMAGE="$OVERRIDE_PWA_IMAGE"; fi
unset OVERRIDE_BACKEND_IMAGE OVERRIDE_PWA_IMAGE

: "${AIR_BACKEND_IMAGE:?AIR_BACKEND_IMAGE must be supplied by the deployment workflow}"
: "${AIR_PWA_IMAGE:?AIR_PWA_IMAGE must be supplied by the deployment workflow}"
: "${AIR_OPERATOR_CUSTOMER_IDS:?Set AIR_OPERATOR_CUSTOMER_IDS in $ENV_FILE}"
: "${AIR_TELEGRAM_CHAT_IDS:?Set AIR_TELEGRAM_CHAT_IDS in $ENV_FILE}"
: "${AIR_APP_DOMAIN:?Set AIR_APP_DOMAIN in $ENV_FILE}"
: "${AIR_API_DOMAIN:?Set AIR_API_DOMAIN in $ENV_FILE}"
: "${AIR_TLS_EMAIL:?Set AIR_TLS_EMAIL in $ENV_FILE}"
: "${AIR_CORS_ORIGINS:?Set AIR_CORS_ORIGINS in $ENV_FILE}"

# Check every external secret declared by docker-stack.yml before image pulls or mutation.
REQUIRED_SECRETS=(
  air_jwt_secret air_credential_key air_admin_api_key air_admin_mfa_key
  air_postgres_password air_redis_password air_database_url air_redis_url air_rabbitmq_password air_rabbitmq_password
  air_telegram_bot_token air_smtp_password
)
state="$(docker info --format '{{.Swarm.LocalNodeState}}')"
if [[ "$state" != "active" ]]; then
  echo "Docker Swarm is not active on this host (state: $state)." >&2
  exit 1
fi

missing_secrets=()
for secret in "${REQUIRED_SECRETS[@]}"; do
  if ! docker secret inspect "$secret" >/dev/null 2>&1; then
    missing_secrets+=("$secret")
  fi
done
if (("${#missing_secrets[@]}")); then
  printf 'Missing required Docker Swarm secrets: %s\n' "${missing_secrets[*]}" >&2
  echo "Create the missing secrets using deploy/DOCKER_SWARM.md before deploying." >&2
  exit 1
fi

echo "Validating rendered Docker Swarm stack..."
docker stack config --compose-file docker-stack.yml >/dev/null

if [[ "${AIR_SKIP_IMAGE_PULL:-false}" == "true" ]]; then
  echo "Using locally built AIR images; image pulls are disabled for first-time installation."
else
  echo "Pulling immutable AIR images..."
  docker pull "$AIR_BACKEND_IMAGE"
  docker pull "$AIR_PWA_IMAGE"
fi

echo "Applying Docker Swarm stack '$STACK_NAME'..."
docker stack deploy --with-registry-auth --prune -c docker-stack.yml "$STACK_NAME"

for service in "${STACK_NAME}_rabbitmq" "${STACK_NAME}_air-api" "${STACK_NAME}_air-workflow-worker" "${STACK_NAME}_air-pwa"; do
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
