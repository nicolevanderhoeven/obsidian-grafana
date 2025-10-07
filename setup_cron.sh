#!/bin/bash

# Setup script for Obsidian to Grafana monitoring
# This script sets up a cron job to run the parser every 5 minutes

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/parse_notes.py"
LOG_DIR="$SCRIPT_DIR/logs"
PARSER_LOG="$LOG_DIR/obsidian_parser.log"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Get the full path to python3
PYTHON_PATH=$(which python3)

# Create a simple log entry that will be picked up by Alloy
CRON_JOB="*/5 * * * * cd $SCRIPT_DIR && $PYTHON_PATH $PYTHON_SCRIPT >> $PARSER_LOG 2>&1 && echo '{\"timestamp\": \"'$(date -u +%Y-%m-%dT%H:%M:%S.000Z)'\", \"level\": \"info\", \"message\": \"Cron job executed successfully\", \"source\": \"cron\"}' >> $PARSER_LOG"

echo "Setting up cron job for Obsidian parser..."
echo "Cron job: $CRON_JOB"

# Add the cron job (this will add it to the current user's crontab)
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo "Cron job added successfully!"
echo "The parser will run every 5 minutes."
echo "Parser logs will be written to: $PARSER_LOG"
echo "All logs will be sent to Loki via Alloy"
echo ""
echo "To view the cron job: crontab -l"
echo "To remove the cron job: crontab -e (then delete the line)"
echo "To monitor logs: tail -f $PARSER_LOG"
