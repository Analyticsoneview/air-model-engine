#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${AIR_DEPLOY_ENV_FILE:-/etc/air/air.env}"
KEY_FILE="${AIR_ADMIN_KEY_FILE:-/etc/air/admin-api-key}"
if [[ ! -r "$ENV_FILE" || ! -r "$KEY_FILE" ]]; then
  echo "AIR environment or administrator key file is missing." >&2
  exit 1
fi
set -a
. "$ENV_FILE"
set +a
: "${AIR_API_BASE_URL:?AIR_API_BASE_URL is not configured}"
ADMIN_KEY="$(cat "$KEY_FILE")"

usage() {
  echo "Usage:"
  echo "  sudo bash deploy/air-admin-cli.sh list [PENDING|APPROVED|REJECTED|BLOCKED]"
  echo "  sudo bash deploy/air-admin-cli.sh approve <request-id>"
  echo "  sudo bash deploy/air-admin-cli.sh reject <request-id>"
  echo "  sudo bash deploy/air-admin-cli.sh block <request-id>"
}
ACTION="${1:-}"
case "$ACTION" in
  list)
    STATUS="${2:-PENDING}"
    if [[ "$STATUS" == "ALL" ]]; then
      curl --fail-with-body -fsS -H "X-AIR-ADMIN-KEY: $ADMIN_KEY" \
        "${AIR_API_BASE_URL}/api/v1/admin/access-requests"
    else
      curl --fail-with-body -fsS -G -H "X-AIR-ADMIN-KEY: $ADMIN_KEY" \
        --data-urlencode "status=$STATUS" \
        "${AIR_API_BASE_URL}/api/v1/admin/access-requests"
    fi
    echo
    ;;
  approve|reject|block)
    REQUEST_ID="${2:-}"
    if [[ -z "$REQUEST_ID" ]]; then usage; exit 2; fi
    case "$ACTION" in
      approve) STATUS="APPROVED" ;;
      reject) STATUS="REJECTED" ;;
      block) STATUS="BLOCKED" ;;
    esac
    curl --fail-with-body -fsS -X PUT \
      -H "X-AIR-ADMIN-KEY: $ADMIN_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"status\":\"$STATUS\",\"note\":\"Reviewed by AIR operator\"}" \
      "${AIR_API_BASE_URL}/api/v1/admin/access-requests/${REQUEST_ID}"
    echo
    ;;
  *)
    usage
    exit 2
    ;;
esac
