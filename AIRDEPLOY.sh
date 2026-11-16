#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${1:-onprem-single}"
case "$PROFILE" in
  onprem-single|aws-private-single|aws-saas-multi) ;;
  *) echo "Usage: ./AIRDEPLOY.sh [onprem-single|aws-private-single|aws-saas-multi]" >&2; exit 2 ;;
esac

command -v docker >/dev/null 2>&1 || { echo "Docker is required for AIR deployment." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is not running." >&2; exit 1; }
PROFILE_FILE="$ROOT/backend/config/deployment_profiles/$PROFILE.json"
[[ -f "$PROFILE_FILE" ]] || { echo "AIR deployment profile not found: $PROFILE_FILE" >&2; exit 1; }

echo "Validating AIR deployment profile: $PROFILE"
docker run --rm --mount "type=bind,source=$ROOT/backend,target=/app" -w /app python:3.12-slim python -m app.deployment_profiles --profile "$PROFILE" --require-cloud-env
export AIR_DEPLOYMENT_PROFILE="$PROFILE"
case "$PROFILE" in
  onprem-single) export AIR_DEPLOYMENT_MODE="on_prem"; export AIR_TENANCY_MODE="single" ;;
  aws-private-single) export AIR_DEPLOYMENT_MODE="aws"; export AIR_TENANCY_MODE="single" ;;
  aws-saas-multi) export AIR_DEPLOYMENT_MODE="aws"; export AIR_TENANCY_MODE="multi" ;;
esac

if [[ "$PROFILE" == "onprem-single" ]]; then
  exec bash "$ROOT/AIRSTART.sh"
fi

AWS_SCRIPT="$ROOT/deploy/aws/AIRDEPLOY.sh"
if [[ ! -f "$AWS_SCRIPT" ]]; then
  echo "The profile is valid, but its AWS provisioning adapter is delivered in the subsequent AWS deployment gate. No AWS resources were created." >&2
  exit 2
fi
exec bash "$AWS_SCRIPT" "$PROFILE"
