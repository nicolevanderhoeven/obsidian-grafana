#!/bin/bash

# Setup script for Obsidian to Grafana monitoring
# This script sets up a cron job to run the parser every 5 minutes

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/parse_notes.py"
CRON_JOB="*/5 * * * * cd $SCRIPT_DIR && python3 $PYTHON_SCRIPT >> /tmp/obsidian_parser.log 2>&1"

echo "Setting up cron job for Obsidian parser..."
echo "Cron job: $CRON_JOB"

# Add the cron job (this will add it to the current user's crontab)
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo "Cron job added successfully!"
echo "The parser will run every 5 minutes."
echo "Logs will be written to /tmp/obsidian_parser.log"
echo ""
echo "To view the cron job: crontab -l"
echo "To remove the cron job: crontab -e (then delete the line)"
