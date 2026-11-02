#!/usr/bin/env bash
# Cron entry point: run the note parser and, on success, append a heartbeat
# line that Alloy ships to Loki as the "cron executed" log (job=obsidian-cron).
# Uses the repo's virtualenv (created by setup.sh) so cron does not depend on
# whatever Python packages the system interpreter happens to have.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"
PARSER_LOG="${LOG_DIR}/obsidian_parser.log"
PYTHON="${REPO_DIR}/.venv/bin/python"

mkdir -p "$LOG_DIR"
cd "$REPO_DIR" || exit 1

if [ ! -x "$PYTHON" ]; then
  echo "cron-parse: ${PYTHON} not found; run ./setup.sh first" >> "$PARSER_LOG"
  exit 1
fi

if "$PYTHON" -m obsidian_grafana.parse_notes >> "$PARSER_LOG" 2>&1; then
  # The timestamp is computed on every run (not once at setup time)
  printf '{"timestamp": "%s", "level": "info", "message": "Cron job executed successfully", "source": "cron"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" >> "$PARSER_LOG"
fi
