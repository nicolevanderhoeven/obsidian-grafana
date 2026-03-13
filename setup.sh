#!/bin/bash

# Setup script for Obsidian to Grafana monitoring
# This script starts the Docker stack and sets up a cron job to run the parser every 5 minutes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/parse_notes.py"
INDEX_SCRIPT="$SCRIPT_DIR/export_vault_index.py"
LOG_DIR="$SCRIPT_DIR/logs"
PARSER_LOG="$LOG_DIR/obsidian_parser.log"
INDEX_LOG="$LOG_DIR/vault_index.log"

echo "🚀 Setting up Obsidian to Grafana monitoring system..."

# Check if config.yaml exists
if [ ! -f "$SCRIPT_DIR/config.yaml" ]; then
    echo "❌ Error: config.yaml not found!"
    echo "Please create config.yaml with your vault path and other settings."
    exit 1
fi

# Extract configuration from config.yaml
echo "📋 Reading configuration from config.yaml..."
GRAFANA_PASSWORD=$(python3 -c "
import yaml
try:
    with open('$SCRIPT_DIR/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    print(config.get('grafana_password', 'admin'))
except Exception as e:
    print('admin')
")

VAULT_PATH=$(python3 -c "
import yaml
try:
    with open('$SCRIPT_DIR/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    print(config.get('vault_path', ''))
except Exception as e:
    print('')
")

if [ -z "$VAULT_PATH" ] || [ ! -d "$VAULT_PATH" ]; then
    echo "❌ Error: vault_path in config.yaml is missing or does not exist: $VAULT_PATH"
    exit 1
fi

# Export for docker-compose
export GRAFANA_PASSWORD
export VAULT_PATH

# Start the Docker stack
echo "🐳 Starting Docker containers..."
cd "$SCRIPT_DIR"
docker-compose up -d

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Get the full path to python3
PYTHON_PATH=$(which python3)

# Create a simple log entry that will be picked up by Alloy
CRON_JOB="*/5 * * * * cd $SCRIPT_DIR && $PYTHON_PATH $PYTHON_SCRIPT >> $PARSER_LOG 2>&1 && echo '{\"timestamp\": \"'$(date -u +%Y-%m-%dT%H:%M:%S.000Z)'\", \"level\": \"info\", \"message\": \"Cron job executed successfully\", \"source\": \"cron\"}' >> $PARSER_LOG"

INDEX_CRON_JOB="*/5 * * * * cd $SCRIPT_DIR && $PYTHON_PATH $INDEX_SCRIPT >> $INDEX_LOG 2>&1"

echo "⏰ Setting up cron jobs for Obsidian parser and vault index..."

# Add both cron jobs (this will add them to the current user's crontab)
(crontab -l 2>/dev/null; echo "$CRON_JOB"; echo "$INDEX_CRON_JOB") | crontab -

echo ""
echo "✅ Setup complete!"
echo ""
echo "🌐 Access your services:"
echo "   • Grafana: http://localhost:3000 (admin/$GRAFANA_PASSWORD)"
echo "   • Prometheus: http://localhost:9090"
echo "   • Loki: http://localhost:3100"
echo "   • Metrics Exporter: http://localhost:8080"
echo ""
echo "📊 The parser and vault index will run every 5 minutes automatically"
echo "📝 Parser logs: $PARSER_LOG"
echo "📝 Index logs: $INDEX_LOG"
echo ""
echo "🔧 Management commands:"
echo "   • View logs: docker-compose logs -f"
echo "   • Stop system: docker-compose down"
echo "   • View cron job: crontab -l"
echo "   • Remove cron job: crontab -e (then delete the line)"
