#!/usr/bin/env bash
set -Eeuo pipefail

# AIR single-node Ubuntu installer. Run as root on Ubuntu 22.04/24.04.
# DNS A/AAAA records for both hostnames must already point to this host.

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash deploy/install-air-ubuntu.sh" >&2
  exit 1
fi
if [[ ! -r /etc/os-release ]]; then
  echo "Cannot identify the operating system." >&2
  exit 1
fi
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" || ! "${VERSION_ID:-}" =~ ^(22\.04|24\.04)$ ]]; then
  echo "AIR installer supports Ubuntu 22.04 and 24.04 only." >&2
  exit 1
fi

SCRIPT_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -d "${SCRIPT_REPO_ROOT}/.git" ]]; then
  DEFAULT_REPO_DIR="$SCRIPT_REPO_ROOT"
else
  DEFAULT_REPO_DIR="/opt/air-model-engine"
fi
REPO_DIR="${AIR_INSTALL_DIR:-$DEFAULT_REPO_DIR}"
ENV_DIR="/etc/air"
ENV_FILE="${ENV_DIR}/air.env"
ADMIN_KEY_FILE="${ENV_DIR}/admin-api-key"

echo "== AIR: installing host prerequisites =="
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl git gnupg openssl python3 python3-venv

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
docker version >/dev/null

if [[ "$(docker info --format '{{.Swarm.LocalNodeState}}')" != "active" ]]; then
  PUBLIC_IP="$(curl -4fsS https://api.ipify.org || true)"
  if [[ -n "$PUBLIC_IP" ]]; then
    docker swarm init --advertise-addr "$PUBLIC_IP"
  else
    docker swarm init
  fi
fi

echo "== AIR: obtaining the private repository =="
if [[ ! -d "${REPO_DIR}/.git" ]]; then
  read -r -p "GitHub username with read access to Analyticsoneview/air-model-engine: " GH_USER
  read -r -s -p "GitHub fine-grained token (Contents: read-only): " GH_TOKEN
  echo
  if [[ -z "$GH_USER" || -z "$GH_TOKEN" ]]; then
    echo "GitHub username and token are required for the private repository." >&2
    exit 1
  fi
  ASKPASS="$(mktemp)"
  chmod 700 "$ASKPASS"
  cat > "$ASKPASS" <<'ASKPASS_EOF'
#!/usr/bin/env sh
case "$1" in
  *Username*) printf '%s' "$AIR_GH_USER" ;;
  *Password*) printf '%s' "$AIR_GH_TOKEN" ;;
  *) exit 1 ;;
esac
ASKPASS_EOF
  AIR_GH_USER="$GH_USER" AIR_GH_TOKEN="$GH_TOKEN" GIT_ASKPASS="$ASKPASS" \
    GIT_TERMINAL_PROMPT=0 git clone \
      --branch "${AIR_INSTALL_REF:-feat/air-telegram-alerts}" \
      https://github.com/Analyticsoneview/air-model-engine.git "$REPO_DIR"
  rm -f "$ASKPASS"
  unset GH_TOKEN
else
  echo "Using existing checkout at ${REPO_DIR}"
  if [[ -n "$(git -C "$REPO_DIR" status --porcelain)" ]]; then
    echo "Existing checkout has local changes. Commit or back them up before updating." >&2
    exit 1
  fi
  INSTALL_REF="${AIR_INSTALL_REF:-feat/air-telegram-alerts}"
  git -C "$REPO_DIR" fetch origin "$INSTALL_REF"
  git -C "$REPO_DIR" checkout -B "$INSTALL_REF" "origin/$INSTALL_REF"
fi

cd "$REPO_DIR"
git status --short

echo "== AIR: collecting deployment settings =="
read -r -p "AIR app hostname (DNS must point here, e.g. air.example.com): " APP_DOMAIN
read -r -p "AIR API hostname (DNS must point here, e.g. api.example.com): " API_DOMAIN
read -r -p "TLS certificate contact email: " TLS_EMAIL
read -r -p "AIR operator mobile in E.164 format (e.g. +919876543210): " OPERATOR_MOBILE
if [[ ! "$APP_DOMAIN" =~ ^[A-Za-z0-9.-]+$ || ! "$API_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "Invalid app/API hostname." >&2; exit 1
fi
if [[ ! "$TLS_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
  echo "Invalid TLS contact email." >&2; exit 1
fi
if [[ ! "$OPERATOR_MOBILE" =~ ^\+[1-9][0-9]{7,14}$ ]]; then
  echo "Operator mobile must be E.164 format, e.g. +919876543210." >&2; exit 1
fi

read -r -p "Telegram chat IDs (private,group; leave blank to keep alerts disabled): " CHAT_IDS
read -r -s -p "Telegram bot token (leave blank to configure later): " TELEGRAM_TOKEN
echo
if [[ -z "$CHAT_IDS" ]]; then CHAT_IDS="disabled"; fi
if [[ -z "$TELEGRAM_TOKEN" ]]; then TELEGRAM_TOKEN="$(openssl rand -hex 32)"; fi

install -d -m 700 "$ENV_DIR"

create_secret_if_missing() {
  local name="$1" value="$2"
  if docker secret inspect "$name" >/dev/null 2>&1; then
    echo "Preserving existing Docker secret: $name"
  else
    printf '%s' "$value" | docker secret create "$name" - >/dev/null
    echo "Created Docker secret: $name"
  fi
}

JWT_SECRET="$(openssl rand -hex 48)"
CREDENTIAL_KEY="$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
if docker secret inspect air_admin_api_key >/dev/null 2>&1 && [[ ! -s "$ADMIN_KEY_FILE" ]]; then
  echo "air_admin_api_key already exists but $ADMIN_KEY_FILE is missing. Restore the matching key file before rerunning." >&2
  exit 1
fi
if [[ ! -s "$ADMIN_KEY_FILE" ]]; then
  openssl rand -hex 48 > "$ADMIN_KEY_FILE"
  chmod 600 "$ADMIN_KEY_FILE"
fi
ADMIN_KEY="$(cat "$ADMIN_KEY_FILE")"
ADMIN_MFA_KEY="$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"

create_secret_if_missing air_jwt_secret "$JWT_SECRET"
create_secret_if_missing air_credential_key "$CREDENTIAL_KEY"
create_secret_if_missing air_admin_api_key "$ADMIN_KEY"
create_secret_if_missing air_admin_mfa_key "$ADMIN_MFA_KEY"
create_secret_if_missing air_telegram_bot_token "$TELEGRAM_TOKEN"
unset JWT_SECRET CREDENTIAL_KEY ADMIN_KEY ADMIN_MFA_KEY TELEGRAM_TOKEN

cat > "$ENV_FILE" <<ENV_EOF
AIR_BACKEND_IMAGE=air-model-engine-api:lab
AIR_PWA_IMAGE=air-model-engine-pwa:lab
AIR_API_BASE_URL=https://${API_DOMAIN}
AIR_APP_DOMAIN=${APP_DOMAIN}
AIR_API_DOMAIN=${API_DOMAIN}
AIR_TLS_EMAIL=${TLS_EMAIL}
AIR_CORS_ORIGINS=https://${APP_DOMAIN}
AIR_OPERATOR_CUSTOMER_IDS="${OPERATOR_MOBILE}"
AIR_API_PORT=8000
AIR_TELEGRAM_CHAT_IDS="${CHAT_IDS}"
AIR_TELEGRAM_SECRET_NAME=air_telegram_bot_token
AIR_TELEGRAM_SCHEDULER_ENABLED=false
AIR_QOC_SCHEDULER_ENABLED=false
AIR_QOC_DHAN_AUTO_RENEW_ENABLED=false
AIR_QOC_DHAN_ACCOUNT_ID=""
AIR_QOC_DHAN_UNDERLYINGS='[]'
AIR_EXPIRYSCAN_MAX_DTE=45
AIR_EXPIRYSCAN_MAX_ROWS=2000
ENV_EOF
chmod 600 "$ENV_FILE"

echo "== AIR: building API and Flutter web app =="
docker build -t air-model-engine-api:lab ./backend
docker build \
  --build-arg "AIR_API_BASE_URL=https://${API_DOMAIN}" \
  -f deploy/pwa.Dockerfile \
  -t air-model-engine-pwa:lab .

echo "== AIR: deploying Docker Swarm stack =="
set -a
. "$ENV_FILE"
set +a
docker stack deploy -c docker-stack.yml air

echo "== AIR: waiting for Swarm services =="
for service in air_air-api air_air-pwa air_air-caddy; do
  ready=0
  replicas=""
  for attempt in $(seq 1 48); do
    replicas="$(docker service ls --filter "name=${service}" --format '{{.Replicas}}' | head -n1)"
    if [[ "$replicas" == "1/1" ]]; then ready=1; break; fi
    sleep 5
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "Service did not converge: ${service} (${replicas:-not found})" >&2
    docker service ps "$service" --no-trunc || true
    exit 1
  fi
done

echo
echo "AIR stack deployed. Check DNS and TLS issuance before customer use:"
echo "  App: https://${APP_DOMAIN}"
echo "  API: https://${API_DOMAIN}/health"
echo
echo "Admin API key is stored root-only at: ${ADMIN_KEY_FILE}"
echo "First operator device must submit an AIR access request in the app."
echo "Approve it with: sudo bash deploy/air-admin-cli.sh approve <REQUEST_ID>"
echo "Then use the in-app Admin tab to review subsequent customer requests."
echo "Telegram polling and QOC capture remain disabled until separately configured."
echo "This installer does not enable live broker orders."
