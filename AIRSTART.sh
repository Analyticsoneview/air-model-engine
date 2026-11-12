#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is missing. Install Docker Desktop (macOS/Windows) or Docker Engine + Compose v2 (Linux), then retry." >&2
  exit 1
fi
docker compose version >/dev/null
docker info >/dev/null 2>&1 || { echo "Docker daemon is not running. Start Docker Desktop/Engine and retry." >&2; exit 1; }

mkdir -p .air-secrets
chmod 700 .air-secrets
echo "Checking and generating all required local-only AIR secrets..."
docker run --rm --mount "type=bind,source=$ROOT/.air-secrets,target=/secrets" --mount "type=bind,source=$ROOT/scripts,target=/scripts,readonly" python:3.12-slim python /scripts/generate_local_secrets.py
chmod 600 .air-secrets/*

if [[ ! -f .air-local.env ]]; then
  cat > .air-local.env <<'EOF'
AIR_OPERATOR_CUSTOMER_IDS=
AIR_MARKET_DATA_POLL_SECONDS=3
AIR_SMTP_PORT=587
EOF
  chmod 600 .air-local.env
fi

echo "Building and starting AIR API + PWA..."
docker compose -f compose.local.yml up -d --build
services=(postgres redis air-api air-pwa)
all_healthy=false
for attempt in $(seq 1 36); do
  all_healthy=true
  for service in "${services[@]}"; do
    container_id="$(docker compose -f compose.local.yml ps -q "$service")"
    if [[ -z "$container_id" ]]; then all_healthy=false; break; fi
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
    if [[ "$health" != "healthy" ]]; then all_healthy=false; break; fi
  done
  if [[ "$all_healthy" == true ]] && curl -fsS http://localhost:8000/health >/dev/null && curl -fsS http://localhost:8080/health >/dev/null; then
    break
  fi
  all_healthy=false
  sleep 5
done

if [[ "$all_healthy" != true ]]; then
  docker compose -f compose.local.yml ps
  docker compose -f compose.local.yml logs --tail 100
  echo "PostgreSQL, Redis, AIR API and PWA did not all become healthy. Do not use the app until the reported issue is fixed." >&2
  exit 1
fi
echo "PostgreSQL, Redis, FastAPI and PWA are healthy."
docker compose -f compose.local.yml ps
if command -v open >/dev/null 2>&1; then open http://localhost:8080
elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:8080
fi

PROFILE_FILE="$HOME/.bashrc"
if [[ "$(uname -s)" == "Darwin" ]]; then PROFILE_FILE="$HOME/.zshrc"; fi
if ! grep -q 'function AIRSTART' "$PROFILE_FILE" 2>/dev/null; then
  printf '\n# AIR one-command local startup\nfunction AIRSTART(){ bash "%s/AIRSTART.sh"; }\n' "$ROOT" >> "$PROFILE_FILE"
fi
echo "Next time, open a new terminal in this repository and type: AIRSTART"
