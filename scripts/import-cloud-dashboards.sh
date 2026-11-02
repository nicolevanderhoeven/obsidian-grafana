#!/usr/bin/env bash
# Import the repo's dashboards into a Grafana Cloud stack (no provisioning needed).
#
# The dashboards reference the local datasource uids "loki" and "prometheus". Grafana
# Cloud's built-in datasources use different uids (default: grafanacloud-logs and
# grafanacloud-prom), so each dashboard is rewritten on the fly; files in
# grafana/dashboards/ are never modified.
#
# Required:
#   GRAFANA_CLOUD_STACK_URL   e.g. https://yourstack.grafana.net
#   GRAFANA_CLOUD_API_TOKEN   service account token (Editor role) for that stack,
#                             NOT the metrics/logs write token
# Optional:
#   CLOUD_LOKI_UID            default grafanacloud-logs
#   CLOUD_PROMETHEUS_UID      default grafanacloud-prom
#   GRAFANA_CLOUD_FOLDER_UID  put the dashboards in this folder
#   --dry-run DIR             write the rewritten JSON to DIR and call nothing
#
# The Word Cloud and Timeseries dashboards use the volkovlabs-echarts-panel and
# marcusolsson-calendar-panel plugins: install both in your Cloud stack first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)/grafana/dashboards"
LOKI_UID="${CLOUD_LOKI_UID:-grafanacloud-logs}"
PROM_UID="${CLOUD_PROMETHEUS_UID:-grafanacloud-prom}"

DRY_RUN_DIR=""
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN_DIR="${2:?usage: $0 --dry-run OUTPUT_DIR}"
  mkdir -p "$DRY_RUN_DIR"
fi

command -v jq >/dev/null 2>&1 || { echo "Error: jq is required." >&2; exit 1; }

if [ -z "$DRY_RUN_DIR" ]; then
  : "${GRAFANA_CLOUD_STACK_URL:?Set GRAFANA_CLOUD_STACK_URL (e.g. https://yourstack.grafana.net)}"
  : "${GRAFANA_CLOUD_API_TOKEN:?Set GRAFANA_CLOUD_API_TOKEN (stack service account token)}"
fi

# Rewrite every {"datasource": {"uid": "loki"|"prometheus"}} reference.
REWRITE='
  walk(
    if type == "object" and (.datasource? | type) == "object" then
      .datasource.uid |= (if . == "loki" then $loki elif . == "prometheus" then $prom else . end)
    else . end
  )'

count=0
for file in "${DASHBOARD_DIR}"/*.json; do
  name="$(basename "$file")"
  body="$(jq --arg loki "$LOKI_UID" --arg prom "$PROM_UID" "$REWRITE" "$file")"
  if [ -n "$DRY_RUN_DIR" ]; then
    printf '%s\n' "$body" > "${DRY_RUN_DIR}/${name}"
    echo "  ✓ ${name} (dry run)"
  else
    payload="$(jq -n --argjson d "$body" --arg folder "${GRAFANA_CLOUD_FOLDER_UID:-}" \
      '{dashboard: ($d | .id = null), overwrite: true}
       + (if $folder != "" then {folderUid: $folder} else {} end)')"
    if curl -sf -X POST "${GRAFANA_CLOUD_STACK_URL%/}/api/dashboards/db" \
        -H "Authorization: Bearer ${GRAFANA_CLOUD_API_TOKEN}" \
        -H "Content-Type: application/json" -d "$payload" >/dev/null; then
      echo "  ✓ ${name}"
    else
      echo "  ✗ ${name} failed to import" >&2
      exit 1
    fi
  fi
  count=$((count + 1))
done
echo "Imported ${count} dashboards."
