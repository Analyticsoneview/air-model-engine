#!/usr/bin/env bash
# AIR-SETUP: one-command registration, repository routing, and CI verification.
set -Eeuo pipefail
REPO="Analyticsoneview/air-model-engine"
BRANCH="feat/air-telegram-alerts"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
fail(){ echo "AIR-SETUP: $*" >&2; exit 1; }
[[ "$(git branch --show-current)" == "$BRANCH" ]] || fail "Check out branch $BRANCH first."
command -v git >/dev/null || fail "Git is required to run AIR-SETUP. Install Git, clone the AIR repository, and rerun."
OS="$(uname -s)"
if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is missing. Installing it now..."
  [[ "$OS" == "Linux" ]] || fail "Automatic GitHub CLI installation is supported on Linux. Install from https://cli.github.com/."
  . /etc/os-release
  case "$ID" in
    ubuntu|debian) sudo apt-get update && sudo apt-get install -y gh ;;
    fedora) sudo dnf install -y gh ;;
    rhel|rocky|almalinux) sudo dnf install -y gh || fail "GitHub CLI package unavailable. Enable the official gh repository and rerun." ;;
    *) fail "Unsupported distribution for automatic GitHub CLI installation: $ID" ;;
  esac
fi
command -v gh >/dev/null 2>&1 || fail "GitHub CLI installed but not on PATH. Open a new terminal and rerun."
if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "Opening GitHub browser authentication. Sign in and grant repository access."
  gh auth login --web -h github.com -p https -s repo,workflow
fi
gh auth status -h github.com >/dev/null 2>&1 || fail "GitHub CLI authentication is required."
ARCH="$(uname -m)"
case "$ARCH" in x86_64|amd64) LABEL_ARCH="x64";; aarch64|arm64) LABEL_ARCH="ARM64";; *) fail "Unsupported CPU architecture: $ARCH";; esac
if [[ "$OS" == "Linux" ]]; then
  [[ -f /etc/os-release ]] || fail "Cannot identify Linux distribution."
  . /etc/os-release
  case "$ID" in ubuntu|debian|fedora|rhel|rocky|almalinux) ;; *) fail "Unsupported Linux distribution: $ID. Supported: Ubuntu, Debian, Fedora, RHEL, Rocky Linux and AlmaLinux." ;; esac
  LABELS='["self-hosted","linux","'"${LABEL_ARCH}"'","air"]'
  RUNNER_NAME="$(hostname)-air"
elif [[ "$OS" == "Darwin" ]]; then
  fail "macOS is not in the requested PC target set for this one-command installer."
else
  fail "Unsupported OS: $OS. Use AIR-SETUP.ps1 on Windows 10/11."
fi
echo "Requesting a short-lived runner token directly from GitHub (it will not be displayed)..."
TOKEN="$(gh api --method POST "repos/$REPO/actions/runners/registration-token" --jq .token)" || fail "Could not create runner token. Your GitHub login needs repository administration permission."
[[ -n "$TOKEN" ]] || fail "GitHub returned an empty runner token."
if [[ ! -e /opt/air-github-runner/.runner ]]; then
  sudo env AIR_RUNNER_TOKEN="$TOKEN" bash deploy/install-github-runner.sh
else
  echo "Runner already configured; ensuring its service is started."
  sudo /opt/air-github-runner/svc.sh start
fi
unset TOKEN
gh variable set AIR_CI_RUNNER_LABELS --repo "$REPO" --body "$LABELS"
echo "Waiting for runner '$RUNNER_NAME' to report Online..."
ONLINE=0
for _ in $(seq 1 60); do
  STATUS="$(gh api "repos/$REPO/actions/runners" --jq '.runners[] | select(.name == "'"$RUNNER_NAME"'") | .status' 2>/dev/null | tail -n 1 || true)"
  if [[ "$STATUS" == "online" ]]; then ONLINE=1; break; fi
  sleep 5
done
[[ "$ONLINE" -eq 1 ]] || fail "Runner did not become Online within five minutes. Check GitHub Actions Runners settings and the local runner service."
run_workflow(){
  local workflow="$1" previous="" run_id=""
  previous="$(gh run list --repo "$REPO" --workflow "$workflow" --branch "$BRANCH" --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId // empty' 2>/dev/null || true)"
  echo "Dispatching $workflow on $BRANCH..."
  gh workflow run "$workflow" --repo "$REPO" --ref "$BRANCH"
  for _ in $(seq 1 60); do
    run_id="$(gh run list --repo "$REPO" --workflow "$workflow" --branch "$BRANCH" --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId // empty' 2>/dev/null || true)"
    if [[ -n "$run_id" && "$run_id" != "$previous" ]]; then break; fi
    sleep 5
  done
  [[ -n "$run_id" && "$run_id" != "$previous" ]] || fail "Could not locate the dispatched run for $workflow."
  gh run watch "$run_id" --repo "$REPO" --exit-status
}
run_workflow backend-tests.yml
run_workflow android-lab.yml
echo "AIR-SETUP completed: runner online; backend and Android workflows passed."
echo "Review the Android APK artifact and PR checks at https://github.com/$REPO/pull/7"
