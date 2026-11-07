#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Run with sudo: sudo bash deploy/install-github-runner.sh" >&2
  exit 1
fi
. /etc/os-release
if [[ "$ID" != "ubuntu" ]]; then
  echo "AIR self-hosted runner installer supports Ubuntu." >&2
  exit 1
fi

RUNNER_USER="airrunner"
RUNNER_DIR="/opt/air-github-runner"
REPO_URL="https://github.com/Analyticsoneview/air-model-engine"

if id "$RUNNER_USER" >/dev/null 2>&1; then
  echo "Runner account already exists."
else
  useradd --create-home --shell /bin/bash "$RUNNER_USER"
fi
usermod -aG docker "$RUNNER_USER"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates jq openjdk-17-jdk

if [[ -e "$RUNNER_DIR/.runner" ]]; then
  echo "A runner is already configured in $RUNNER_DIR."
  exit 0
fi

read -r -s -p "Short-lived GitHub Actions runner registration token (repo Settings > Actions > Runners > New self-hosted runner): " RUNNER_TOKEN
echo
if [[ -z "$RUNNER_TOKEN" ]]; then
  echo "A runner registration token is required." >&2
  exit 1
fi

RELEASE_JSON="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
ASSET_URL="$(printf '%s' "$RELEASE_JSON" | python3 -c 'import json,sys; j=json.load(sys.stdin); print(next(a["browser_download_url"] for a in j["assets"] if a["name"].startswith("actions-runner-linux-x64-") and a["name"].endswith(".tar.gz")))')"
ASSET_DIGEST="$(printf '%s' "$RELEASE_JSON" | python3 -c 'import json,sys; j=json.load(sys.stdin); a=next(a for a in j["assets"] if a["name"].startswith("actions-runner-linux-x64-") and a["name"].endswith(".tar.gz")); print(a.get("digest") or "")')"

install -d -o "$RUNNER_USER" -g "$RUNNER_USER" "$RUNNER_DIR"
curl -fsSL "$ASSET_URL" -o "$RUNNER_DIR/runner.tar.gz"
if [[ "$ASSET_DIGEST" == sha256:* ]]; then
  echo "${ASSET_DIGEST#sha256:}  $RUNNER_DIR/runner.tar.gz" | sha256sum -c -
else
  echo "GitHub release did not provide a SHA-256 digest; verify the downloaded runner package before production use." >&2
fi
tar -xzf "$RUNNER_DIR/runner.tar.gz" -C "$RUNNER_DIR"
rm -f "$RUNNER_DIR/runner.tar.gz"
chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_DIR"

sudo -u "$RUNNER_USER" "$RUNNER_DIR/config.sh" \
  --url "$REPO_URL" \
  --token "$RUNNER_TOKEN" \
  --name "$(hostname)-air" \
  --labels air,linux,x64 \
  --work _work \
  --unattended
unset RUNNER_TOKEN

"$RUNNER_DIR/svc.sh" install "$RUNNER_USER"
"$RUNNER_DIR/svc.sh" start

echo
echo "AIR GitHub runner installed and started."
echo "Set repository variable AIR_RUNNER_LABELS to:"
echo '["self-hosted","linux","x64","air"]'
echo "This grants the runner Docker access; protect the Ubuntu host as a privileged CI machine."
