#!/usr/bin/env bash
# Cron entry point: regenerate the OpenClaw vault index using the repo's virtualenv.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"
INDEX_LOG="${LOG_DIR}/vault_index.log"
PYTHON="${REPO_DIR}/.venv/bin/python"

mkdir -p "$LOG_DIR"
cd "$REPO_DIR" || exit 1

if [ ! -x "$PYTHON" ]; then
  echo "cron-index: ${PYTHON} not found; run ./setup.sh first" >> "$INDEX_LOG"
  exit 1
fi

exec "$PYTHON" -m obsidian_grafana.export_vault_index >> "$INDEX_LOG" 2>&1
