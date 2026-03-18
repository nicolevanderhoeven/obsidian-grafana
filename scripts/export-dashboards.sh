#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DASHBOARD_DIR="${REPO_DIR}/grafana/dashboards"

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"

if [ -z "${GRAFANA_PASSWORD:-}" ]; then
  CONFIG_FILE="${REPO_DIR}/config.yaml"
  if [ -f "$CONFIG_FILE" ]; then
    GRAFANA_PASSWORD=$(sed -n 's/^grafana_password:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' "$CONFIG_FILE" 2>/dev/null || true)
  fi
  GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-${GF_SECURITY_ADMIN_PASSWORD:-admin}}"
fi

if ! command -v jq &>/dev/null; then
  echo "Error: jq is required but not installed. Install with: brew install jq" >&2
  exit 1
fi

if ! curl -sf "${GRAFANA_URL}/api/health" &>/dev/null; then
  echo "Warning: Grafana is not reachable at ${GRAFANA_URL} — skipping dashboard export." >&2
  exit 0
fi

uid_to_filename() {
  local uid="$1"
  for file in "${DASHBOARD_DIR}"/*.json; do
    [ -f "$file" ] || continue
    file_uid=$(jq -r '.uid // empty' "$file" 2>/dev/null)
    if [ "$file_uid" = "$uid" ]; then
      echo "$file"
      return
    fi
  done
  echo "${DASHBOARD_DIR}/${uid}.json"
}

echo "Fetching dashboards from ${GRAFANA_URL}..."

dashboards=$(curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASSWORD}" \
  "${GRAFANA_URL}/api/search?type=dash-db" 2>/dev/null)

if [ -z "$dashboards" ] || [ "$dashboards" = "[]" ]; then
  echo "No dashboards found."
  exit 0
fi

count=$(echo "$dashboards" | jq length)
exported=0

for i in $(seq 0 $((count - 1))); do
  uid=$(echo "$dashboards" | jq -r ".[$i].uid")
  title=$(echo "$dashboards" | jq -r ".[$i].title")

  raw=$(curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASSWORD}" \
    "${GRAFANA_URL}/api/dashboards/uid/${uid}" 2>/dev/null)

  if [ -z "$raw" ]; then
    echo "  ✗ Failed to fetch: ${title} (${uid})" >&2
    continue
  fi

  outfile=$(uid_to_filename "$uid")

  echo "$raw" | jq '.dashboard | .id = null | del(.version)' > "$outfile"

  echo "  ✓ ${title} → $(basename "$outfile")"
  exported=$((exported + 1))
done

echo "Exported ${exported}/${count} dashboards to ${DASHBOARD_DIR}"
