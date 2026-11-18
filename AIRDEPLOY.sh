#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${AIR_DEPLOYMENT_PROFILE:-onprem-single}"
ACTION=""
MANAGER_ARGS=()

while (($#)); do
  case "$1" in
    onprem-single|aws-private-single|aws-saas-multi)
      PROFILE="$1"; shift ;;
    validate|doctor|install|upgrade|status|diagnose|package)
      if [[ -n "$ACTION" ]]; then echo "Only one AIR Deployment Manager action may be selected." >&2; exit 2; fi
      ACTION="$1"; shift ;;
    --version|--output-dir)
      option="$1"; shift
      if (($# == 0)); then echo "$option requires a value." >&2; exit 2; fi
      MANAGER_ARGS+=("$option" "$1"); shift ;;
    --orchestrator)
      shift
      if [[ $# == 0 ]]; then echo "--orchestrator requires compose or swarm." >&2; exit 2; fi
      if [[ "$1" != "compose" && "$1" != "swarm" ]]; then echo "--orchestrator must be compose or swarm." >&2; exit 2; fi
      MANAGER_ARGS+=(--orchestrator "$1"); shift ;;
    --help|-h)
      exec python3 "$ROOT/scripts/air_manager.py" --help ;;
    *)
      echo "Unknown AIR deployment argument: $1" >&2
      echo "Usage: ./AIRDEPLOY.sh [profile] [action] [--version VERSION] [--output-dir DIR]" >&2
      exit 2 ;;
  esac
done

if [[ -z "$ACTION" ]]; then
  if [[ "$PROFILE" == "onprem-single" ]]; then ACTION="install"; else ACTION="validate"; fi
fi
exec python3 "$ROOT/scripts/air_manager.py" --profile "$PROFILE" "${MANAGER_ARGS[@]}" "$ACTION"
