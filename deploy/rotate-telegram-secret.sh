#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="/etc/air/air.env"
if [[ "$EUID" -ne 0 || ! -r "$ENV_FILE" ]]; then
  echo "Run as root on the AIR Swarm manager." >&2
  exit 1
fi
set -a
. "$ENV_FILE"
set +a

OLD_SECRET="${AIR_TELEGRAM_SECRET_NAME:-air_telegram_bot_token}"
NEW_SECRET="air_telegram_bot_token_$(date -u +%Y%m%d%H%M%S)"
read -r -s -p "New Telegram bot token from BotFather: " NEW_TOKEN
echo
if [[ -z "$NEW_TOKEN" ]]; then
  echo "A non-empty bot token is required." >&2
  exit 1
fi
if docker secret inspect "$NEW_SECRET" >/dev/null 2>&1; then
  echo "Secret name collision; retry the rotation." >&2
  exit 1
fi

printf '%s' "$NEW_TOKEN" | docker secret create "$NEW_SECRET" - >/dev/null
unset NEW_TOKEN

sed -i "s/^AIR_TELEGRAM_SECRET_NAME=.*/AIR_TELEGRAM_SECRET_NAME=$NEW_SECRET/" "$ENV_FILE"
cd /opt/air-model-engine
set -a
. "$ENV_FILE"
set +a
if ! docker stack deploy -c docker-stack.yml air; then
  sed -i "s/^AIR_TELEGRAM_SECRET_NAME=.*/AIR_TELEGRAM_SECRET_NAME=$OLD_SECRET/" "$ENV_FILE"
  exit 1
fi

ready=0
for attempt in $(seq 1 36); do
  replicas="$(docker service ls --filter name=air_air-api --format '{{.Replicas}}' | head -n1)"
  if [[ "$replicas" == "1/1" ]]; then ready=1; break; fi
  sleep 5
done
if [[ "$ready" -ne 1 ]]; then
  echo "API did not converge. The previous secret remains available: $OLD_SECRET" >&2
  sed -i "s/^AIR_TELEGRAM_SECRET_NAME=.*/AIR_TELEGRAM_SECRET_NAME=$OLD_SECRET/" "$ENV_FILE"
  exit 1
fi

if [[ "$OLD_SECRET" != "$NEW_SECRET" ]] && docker secret inspect "$OLD_SECRET" >/dev/null 2>&1; then
  docker secret rm "$OLD_SECRET"
fi
echo "Telegram secret rotated to $NEW_SECRET."
echo "Send a test message through the AIR operator Telegram test endpoint before enabling scheduled delivery."
