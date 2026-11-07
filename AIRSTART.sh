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
if [[ ! -s .air-secrets/jwt_secret || ! -s .air-secrets/credential_key || ! -s .air-secrets/admin_api_key ]]; then
  echo "Generating local-only AIR secrets..."
  { read -r jwt_secret; read -r credential_key; read -r admin_api_key; } < <(docker run --rm python:3.12-slim python -c 'import secrets,base64; print(secrets.token_urlsafe(48)); print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()); print(secrets.token_urlsafe(48))')
  [[ -n "${jwt_secret:-}" && -n "${credential_key:-}" && -n "${admin_api_key:-}" ]] || { echo "Secret generation failed." >&2; exit 1; }
  printf '%s' "$jwt_secret" > .air-secrets/jwt_secret
  printf '%s' "$credential_key" > .air-secrets/credential_key
  printf '%s' "$admin_api_key" > .air-secrets/admin_api_key
  chmod 600 .air-secrets/*
fi

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
for attempt in $(seq 1 36); do
  if curl -fsS http://localhost:8000/health >/dev/null; then
    echo "AIR API is healthy."
    break
  fi
  if [[ "$attempt" -eq 36 ]]; then
    docker compose -f compose.local.yml ps
    docker compose -f compose.local.yml logs --tail 100
    echo "AIR did not become healthy. Do not use the app until the reported issue is fixed." >&2
    exit 1
  fi
  sleep 5
done

if command -v open >/dev/null 2>&1; then open http://localhost:8080
elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:8080
fi
docker compose -f compose.local.yml ps

PROFILE_FILE="$HOME/.bashrc"
[[ -n "${ZSH_VERSION:-}" ]] && PROFILE_FILE="$HOME/.zshrc"
if ! grep -q 'function AIRSTART' "$PROFILE_FILE" 2>/dev/null; then
  printf '\n# AIR one-command local startup\nfunction AIRSTART(){ bash "%s/AIRSTART.sh"; }\n' "$ROOT" >> "$PROFILE_FILE"
fi
echo "Next time, open a new terminal in this repository and type: AIRSTART"
