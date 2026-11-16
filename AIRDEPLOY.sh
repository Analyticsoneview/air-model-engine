#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${AIR_DEPLOYMENT_PROFILE:-onprem-single}"
ACTION=""

if [[ $# -gt 0 ]]; then
  case "$1" in
    validate|doctor|install|upgrade|status|diagnose|package)
      ACTION="$1"
      shift
      ;;
    onprem-single|aws-private-single|aws-saas-multi)
      PROFILE="$1"
      shift
      ;;
    --help|-h)
      exec python3 "$ROOT/scripts/air_manager.py" --help
      ;;
    *)
      echo "Usage: ./AIRDEPLOY.sh [onprem-single|aws-private-single|aws-saas-multi] [validate|doctor|install|upgrade|status|diagnose|package]" >&2
      exit 2
      ;;
  esac
fi
if [[ $# -gt 0 ]]; then
  if [[ -n "$ACTION" || $# -gt 1 ]]; then
    echo "Usage: ./AIRDEPLOY.sh [profile] [action]" >&2
    exit 2
  fi
  ACTION="$1"
fi
if [[ -z "$ACTION" ]]; then
  if [[ "$PROFILE" == "onprem-single" ]]; then ACTION="install"; else ACTION="validate"; fi
fi

exec python3 "$ROOT/scripts/air_manager.py" --profile "$PROFILE" "$ACTION"
