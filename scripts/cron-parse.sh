#!/usr/bin/env bash
# Cron entry point: run the note parser and, on success, append a heartbeat
# line that Alloy ships to Loki as the "cron executed" log (job=obsidian-cron).
# Uses the repo's virtualenv (created by setup.sh) so cron does not depend on
# whatever Python packages the system interpreter happens to have.
#
# The parser log is size-rotated here so it cannot grow without bound: once it exceeds
# OBSIDIAN_PARSER_LOG_MAX_BYTES (default 10 MiB) it is moved to obsidian_parser.log.1,
# gzipped to .1.gz, and older generations shift up, keeping OBSIDIAN_PARSER_LOG_KEEP
# (default 3) compressed generations. Uses only mv/gzip/stat/date, no logrotate.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"
PARSER_LOG="${LOG_DIR}/obsidian_parser.log"
PYTHON="${REPO_DIR}/.venv/bin/python"

MAX_BYTES="${OBSIDIAN_PARSER_LOG_MAX_BYTES:-10485760}"
KEEP="${OBSIDIAN_PARSER_LOG_KEEP:-3}"

mkdir -p "$LOG_DIR"
cd "$REPO_DIR" || exit 1

# Rotate before running. Alloy tails the path, notices the new inode after the move and
# starts reading the fresh file from the top; the rotated generations are never read again.
rotate_log() {
  local size i
  size="$(stat -c %s "$PARSER_LOG" 2>/dev/null || stat -f %z "$PARSER_LOG" 2>/dev/null || echo 0)"
  [ "$size" -gt "$MAX_BYTES" ] || return 0
  i="$KEEP"
  rm -f "${PARSER_LOG}.${i}.gz"
  while [ "$i" -gt 1 ]; do
    [ -e "${PARSER_LOG}.$((i - 1)).gz" ] && mv -f "${PARSER_LOG}.$((i - 1)).gz" "${PARSER_LOG}.${i}.gz"
    i=$((i - 1))
  done
  mv -f "$PARSER_LOG" "${PARSER_LOG}.1" && gzip -f "${PARSER_LOG}.1"
}
[ -e "$PARSER_LOG" ] && rotate_log

if [ ! -x "$PYTHON" ]; then
  echo "cron-parse: ${PYTHON} not found; run ./setup.sh first" >> "$PARSER_LOG"
  exit 1
fi

if "$PYTHON" -m obsidian_grafana.parse_notes >> "$PARSER_LOG" 2>&1; then
  # The timestamp is computed on every run (not once at setup time)
  printf '{"timestamp": "%s", "level": "info", "message": "Cron job executed successfully", "source": "cron"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" >> "$PARSER_LOG"
fi
