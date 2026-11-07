#!/usr/bin/env bash
set -Eeuo pipefail
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) RUNNER_ARCH="x64"; LABEL_ARCH="x64" ;;
  arm64|aarch64) RUNNER_ARCH="arm64"; LABEL_ARCH="ARM64" ;;
  *) echo "Unsupported CPU architecture: $ARCH" >&2; exit 1 ;;
esac
REPO_URL="https://github.com/Analyticsoneview/air-model-engine"
if [[ "$OS" == "Linux" ]]; then
  if [[ "$EUID" -ne 0 ]]; then echo "Run with sudo: sudo bash deploy/install-github-runner.sh" >&2; exit 1; fi
  . /etc/os-release
  RUNNER_USER="airrunner"; RUNNER_DIR="/opt/air-github-runner"
  if ! id "$RUNNER_USER" >/dev/null 2>&1; then useradd --create-home --shell /bin/bash "$RUNNER_USER"; fi
  case "$ID" in
    ubuntu|debian)
      command -v apt-get >/dev/null || { echo "apt-get is required for $ID." >&2; exit 1; }
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates jq openjdk-17-jdk python3 sudo
      ;;
    fedora|rhel|rocky|almalinux)
      if command -v dnf >/dev/null 2>&1; then
        dnf install -y curl ca-certificates jq java-17-openjdk-devel python3 sudo
      elif command -v yum >/dev/null 2>&1; then
        yum install -y curl ca-certificates jq java-17-openjdk-devel python3 sudo
      else echo "dnf or yum is required for $ID." >&2; exit 1; fi
      ;;
    *)
      echo "Unsupported Linux distribution: $ID. Supported: Ubuntu, Debian, Fedora, RHEL, Rocky Linux and AlmaLinux." >&2
      exit 1
      ;;
  esac
  command -v systemctl >/dev/null || { echo "systemd is required to install the runner as a service." >&2; exit 1; }
elif [[ "$OS" == "Darwin" ]]; then
  if [[ "$EUID" -eq 0 ]]; then echo "Do not run this macOS installer with sudo; run it as the signed-in user." >&2; exit 1; fi
  RUNNER_USER="$(id -un)"; RUNNER_DIR="$HOME/air-github-runner"
  command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }
  command -v python3 >/dev/null || { echo "Install Python 3 (for example with Homebrew) and retry." >&2; exit 1; }
else
  echo "Unsupported OS: $OS. Use deploy/install-github-runner.ps1 on Windows." >&2; exit 1
fi
if [[ -e "$RUNNER_DIR/.runner" ]]; then echo "A runner is already configured in $RUNNER_DIR."; exit 0; fi
RELEASE_JSON="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
if [[ "$OS" == "Linux" ]]; then ASSET_PREFIX="actions-runner-linux-${RUNNER_ARCH}-"; else ASSET_PREFIX="actions-runner-osx-${RUNNER_ARCH}-"; fi
ASSET_URL="$(printf '%s' "$RELEASE_JSON" | python3 -c 'import json,sys; j=json.load(sys.stdin); p=sys.argv[1]; print(next(a["browser_download_url"] for a in j["assets"] if a["name"].startswith(p) and a["name"].endswith(".tar.gz")))' "$ASSET_PREFIX")"
ASSET_DIGEST="$(printf '%s' "$RELEASE_JSON" | python3 -c 'import json,sys; j=json.load(sys.stdin); p=sys.argv[1]; a=next(a for a in j["assets"] if a["name"].startswith(p) and a["name"].endswith(".tar.gz")); print(a.get("digest") or "")' "$ASSET_PREFIX")"
if [[ "$OS" == "Linux" ]]; then install -d -o "$RUNNER_USER" -g "$RUNNER_USER" "$RUNNER_DIR"; else install -d "$RUNNER_DIR"; fi
curl -fsSL "$ASSET_URL" -o "$RUNNER_DIR/runner.tar.gz"
if [[ "$ASSET_DIGEST" == sha256:* ]]; then
  EXPECTED_DIGEST="${ASSET_DIGEST#sha256:}"
  if command -v sha256sum >/dev/null 2>&1; then echo "$EXPECTED_DIGEST  $RUNNER_DIR/runner.tar.gz" | sha256sum -c -
  else echo "$EXPECTED_DIGEST  $RUNNER_DIR/runner.tar.gz" | shasum -a 256 -c -; fi
else echo "GitHub release did not provide a SHA-256 digest; verify the downloaded runner package before production use." >&2; fi
tar -xzf "$RUNNER_DIR/runner.tar.gz" -C "$RUNNER_DIR"; rm -f "$RUNNER_DIR/runner.tar.gz"
if [[ "$OS" == "Linux" ]]; then
  chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_DIR"
  "$RUNNER_DIR/bin/installdependencies.sh"
  chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_DIR"
fi
RUNNER_TOKEN="${AIR_RUNNER_TOKEN:-}"
if [[ -z "$RUNNER_TOKEN" ]]; then
  read -r -s -p "Short-lived GitHub Actions runner registration token: " RUNNER_TOKEN
  echo
fi
if [[ -z "$RUNNER_TOKEN" ]]; then echo "A runner registration token is required." >&2; exit 1; fi
if [[ "$OS" == "Linux" ]]; then
  if [[ "$LABEL_ARCH" == "ARM64" ]]; then LABELS="air,linux,ARM64"; else LABELS="air,linux,x64"; fi
  sudo -u "$RUNNER_USER" "$RUNNER_DIR/config.sh" --url "$REPO_URL" --token "$RUNNER_TOKEN" --name "$(hostname)-air" --labels "$LABELS" --work _work --unattended
else
  if [[ "$LABEL_ARCH" == "ARM64" ]]; then LABELS="air,macOS,ARM64"; else LABELS="air,macOS,X64"; fi
  "$RUNNER_DIR/config.sh" --url "$REPO_URL" --token "$RUNNER_TOKEN" --name "$(hostname)-air" --labels "$LABELS" --work _work --unattended
fi
unset RUNNER_TOKEN
if [[ "$OS" == "Linux" ]]; then
  chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_DIR"
  "$RUNNER_DIR/svc.sh" install "$RUNNER_USER"; "$RUNNER_DIR/svc.sh" start
  echo 'Set AIR_CI_RUNNER_LABELS to ["self-hosted","linux","x64","air"] (or ARM64 for an ARM64 host). Linux-only PWA/Docker workflows remain on their existing runner unless configured separately.'
else
  "$RUNNER_DIR/svc.sh" install; "$RUNNER_DIR/svc.sh" start
  echo 'Set AIR_CI_RUNNER_LABELS to ["self-hosted","macOS","X64","air"] (or ARM64 for Apple Silicon). Keep AIR_RUNNER_LABELS unset; Linux-only workflows remain on ubuntu-latest.'
fi
echo
echo "AIR GitHub runner installed and started. Verify Online/Idle in repository Settings > Actions > Runners."
