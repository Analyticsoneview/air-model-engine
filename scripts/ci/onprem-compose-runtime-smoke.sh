#!/usr/bin/env bash
# Ephemeral GitHub Actions runtime smoke test for the on-prem Compose stack.
# This deliberately disables the long NSE history bootstrap; it verifies service
# startup and workflow infrastructure, not the full installation /ready gate.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

cleanup() {
  docker compose -f compose.local.yml logs --no-color --tail 120 || true
  docker compose -f compose.local.yml down --volumes --remove-orphans || true
  rm -rf .air-secrets .air-local.env
}
trap cleanup EXIT

mkdir -p .air-secrets
chmod 700 .air-secrets
python3 - <<'PY'
from pathlib import Path
import base64
import secrets

root = Path(".air-secrets")
pg = secrets.token_urlsafe(32)
redis = secrets.token_urlsafe(32)
rabbit = secrets.token_urlsafe(32)
values = {
    "jwt_secret": secrets.token_urlsafe(48),
    "credential_key": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "admin_api_key": secrets.token_urlsafe(48),
    "admin_mfa_key": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "postgres_password": pg,
    "redis_password": redis,
    "rabbitmq_password": rabbit,
    "database_url": f"postgresql+psycopg://air:{pg}@postgres:5432/air",
    "redis_url": f"redis://:{redis}@redis:6379/0",
    "telegram_bot_token": "",
}
for name, value in values.items():
    path = root / name
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
Path(".air-local.env").write_text(
    "AIR_OPERATOR_CUSTOMER_IDS=\nAIR_MARKET_DATA_POLL_SECONDS=3\nAIR_SMTP_PORT=587\n",
    encoding="utf-8",
)
PY

export AIR_NSE_BOOTSTRAP_ENABLED=false
export AIR_NSE_HISTORY_MONTHS=12
docker compose -f compose.local.yml config --quiet
docker compose -f compose.local.yml up -d --build --wait --wait-timeout 600

for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:8000/health >/dev/null \
    && curl --fail --silent http://127.0.0.1:8080/health >/dev/null; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "Compose API/PWA health endpoints did not become ready." >&2
    exit 1
  fi
  sleep 5
done

heartbeat_sql="SELECT 1 FROM air_workflow_worker_heartbeats WHERE component='workflow-runtime' AND status='RUNNING' AND last_seen::timestamptz > now() - interval '90 seconds' AND details_json::jsonb ->> 'rabbitmq_connected' = 'true' LIMIT 1"
heartbeat_ready=false
for attempt in $(seq 1 60); do
  if result="$(docker compose -f compose.local.yml exec -T postgres sh -ec \
    'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; psql -U air -d air -Atqc "$1"' \
    sh "$heartbeat_sql" 2>/dev/null)" && [[ "$result" == "1" ]]; then
    heartbeat_ready=true
    break
  fi
  sleep 5
done
if [[ "$heartbeat_ready" != true ]]; then
  echo "Compose workflow worker did not publish a fresh RabbitMQ-connected heartbeat." >&2
  exit 1
fi

echo "PASS: Compose PostgreSQL, Redis, RabbitMQ, API, worker and PWA runtime smoke test."
echo "NOTE: NSE history bootstrap and full /ready acceptance are intentionally tested separately."
