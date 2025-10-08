# Obsidian to Grafana Monitoring System

A monitoring system that parses your Obsidian Markdown notes and visualizes metadata in Grafana dashboards. This system tracks note statistics, frontmatter properties, tags, and relationships over time.

## Architecture

```
Python Parser → JSON Logs → Alloy → Loki → Grafana Dashboards
```

- **Python Parser**: Extracts metadata from Obsidian notes every 5 minutes
- **Alloy**: Collects JSON logs and forwards them to Loki with proper labels
- **Loki**: Stores timestamped log entries for querying
- **Grafana**: Visualizes the data with interactive dashboards

## Features

- **Basic Statistics**: Word count, line count, file size tracking over time
- **Frontmatter Analysis**: YAML frontmatter fields as Loki labels for filtering
- **Type Analysis**: Distribution and usage patterns of frontmatter types (NPC, PC, audio, etc.)
- **Tag Tracking**: Both frontmatter tags and inline `#tags`
- **Note Relationships**: Wikilinks (`[[note]]`) and backlink analysis
- **Time Series Visualization**: Track how your notes evolve over time
- **Interactive Dashboards**: Filter by tags, categories, note names, and types

## Quick Start

### 1. Set Up Configuration

First, copy the example configuration file and customize it for your setup:

```bash
cp config.yaml.example config.yaml
```

Then edit `config.yaml` and update the values:

```yaml
vault_path: "/path/to/your/obsidian/vault"  # Update this to your actual vault path
output_file: "./logs/obsidian_logs.json"
log_level: "INFO"  # Options: DEBUG, INFO, WARNING, ERROR
metrics_port: 8080
start_metrics_server: false  # Set to true to enable metrics collection
grafana_password: "your_grafana_password_here"  # Replace with your actual Grafana password
```

**Important**: The `config.yaml` file contains sensitive information (like your Grafana password) and is excluded from version control. Always use the `config.yaml.example` file as a template.

### 2. Install Python Dependencies

```bash
pip3 install -r requirements.txt
```

### 3. Start the System

Run the setup script to start everything:

```bash
./setup.sh
```

This will:
- Read the Grafana password from `config.yaml`
- Start all Docker containers
- Set up automated parsing every 5 minutes
- Display access URLs and credentials

Services available at:
- **Grafana** at http://localhost:3000 (admin/your_password)
- **Loki** at http://localhost:3100
- **Alloy** at http://localhost:12345
- **Prometheus** at http://localhost:9090
- **Metrics Exporter** at http://localhost:8080

The parser will run every 5 minutes automatically.

### 4. Test the System

Run the parser manually to generate initial data:

```bash
python3 parse_notes.py
```

Check that logs are being generated:

```bash
tail -f /tmp/obsidian_logs.json
```

### 6. View Dashboards

Open Grafana at http://localhost:3000 and explore the pre-configured dashboards:

- **Obsidian Overview**: High-level statistics and activity
- **Time Series**: Word count, line count, and file size trends
- **Tag Analysis**: Tag usage patterns and distributions
- **Note Relationships**: Wikilinks and backlink analysis
- **Frontmatter Types Analysis**: Distribution and usage of different frontmatter types

## Manual Usage

### Run Parser Manually

```bash
# Using config file
python3 parse_notes.py

# Override vault path
python3 parse_notes.py --vault-path /path/to/vault

# Override output file
python3 parse_notes.py --output /tmp/custom_logs.json

# Set log level
python3 parse_notes.py --log-level DEBUG
```

### View Alloy Status

Visit http://localhost:12345 to see Alloy's status and configuration.

## Dashboard Queries

The dashboards use LogQL queries to filter and aggregate data. See `.cursor/plan.md` for detailed query examples and implementation details.

## Configuration

### Python Parser

The parser extracts the following metadata:

- **Basic Stats**: `word_count`, `line_count`, `file_size`, `char_count`
- **Timestamps**: `created_at`, `modified_at`
- **Frontmatter**: All YAML frontmatter fields (prefixed with `frontmatter_`)
- **Tags**: Both frontmatter `tags` and inline `#tags`
- **Wikilinks**: `[[note]]` references for relationship analysis

### Alloy Configuration

Alloy is configured to:
- Watch `/tmp/obsidian_logs.json` for new entries
- Extract labels from JSON structure
- Forward to Loki with proper timestamps
- Handle log rotation and cleanup

### Grafana Dashboards

Five main dashboards are provided:

1. **Overview**: Total notes, processing rate, recent activity
2. **Time Series**: Individual note metrics over time
3. **Tag Analysis**: Tag usage patterns and distributions
4. **Relationships**: Wikilinks and note connections
5. **Frontmatter Types Analysis**: Distribution and usage of different frontmatter types

#### Frontmatter Types Analysis Dashboard

Analyzes the distribution and usage patterns of frontmatter types (NPC, PC, audio, etc.) with pie charts, time series, and vault breakdowns.

## Troubleshooting

### Parser Issues

```bash
# Check parser logs
tail -f /tmp/obsidian_parser.log

# Run with debug logging
python3 parse_notes.py --log-level DEBUG
```

### Docker Issues

```bash
# Check container status
docker-compose ps

# View logs
docker-compose logs -f

# Restart services
docker-compose restart
```

### Alloy Issues

- Visit http://localhost:12345 for Alloy UI
- Check that `/tmp/obsidian_logs.json` is being created
- Verify Loki connectivity in Alloy logs

### Grafana Issues

- Check datasource configuration at http://localhost:3000/datasources
- Verify Loki is accessible from Grafana
- Check dashboard queries in Explore view

## File Structure

```
obsidian-grafana/
├── parse_notes.py          # Main Python parser
├── requirements.txt        # Python dependencies
├── config.yaml            # Configuration file (create from example)
├── config.yaml.example    # Example configuration template
├── setup.sh               # Setup script (starts system + cron job)
├── docker-compose.yml     # Docker stack definition
├── alloy/
│   └── config.alloy       # Alloy configuration
├── grafana/
│   ├── provisioning/      # Grafana provisioning
│   └── dashboards/        # Dashboard JSON files
└── README.md             # This file
```

## Production Considerations

This setup is designed for personal use. For production deployment, consider:

1. **Security**: Change default passwords and enable authentication
2. **Persistence**: Ensure data volumes are properly backed up
3. **Monitoring**: Add health checks and alerting
4. **Scaling**: Consider using external databases for larger datasets
5. **Network**: Use proper networking and firewall rules

## Contributing

Feel free to submit issues and enhancement requests! Some ideas for improvements:

- More sophisticated relationship analysis
- Note similarity detection
- Writing pattern analysis
- Export capabilities
- Mobile-friendly dashboards

## License

This project is open source. Feel free to modify and distribute as needed.
