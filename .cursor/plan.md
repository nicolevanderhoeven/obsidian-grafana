<!-- f2d8689d-a443-420e-b10f-e565900cbe30 9fc4dd50-d8cf-4e5d-aa41-275a75104f25 -->
# Obsidian to Grafana Monitoring System

## Architecture Overview

Python script → JSON output → Alloy → Loki → Grafana dashboards

## Implementation Steps

### 1. Python Parser Script (`parse_notes.py`)

Create a script that:

- Accepts a directory path as configuration
- Recursively scans for `.md` files
- Extracts metadata from each note:
  - Basic stats: word count, line count, file size
  - File timestamps: created, modified
  - YAML frontmatter fields (all key-value pairs)
  - Tags (both frontmatter tags and inline `#tags`)
  - Future: backlinks/wikilinks (parse `[[note]]` syntax)
- Outputs JSON to a file (`/tmp/obsidian_logs.json`) with:
  - Timestamp for each entry
  - Loki labels: note name, tags, frontmatter properties
  - Log line: JSON with all metadata
- Include configuration for: vault path, output location

### 2. Docker Compose Stack (`docker-compose.yml`)

Set up services:

- **Grafana** (latest): exposed on port 3000
- **Loki** (latest): log aggregation backend
- **Alloy**: configured to read JSON files and ship to Loki
- Volumes for persistence: grafana data, loki data
- Network configuration for service communication

### 3. Alloy Configuration (`alloy/config.alloy`)

Configure Alloy to:

- Watch `/tmp/obsidian_logs.json` for new entries
- Parse JSON and extract labels (note name, tags, frontmatter fields)
- Forward to Loki with proper timestamp preservation
- Handle log rotation/cleanup

### 4. Scheduler Setup

Create a cron job or systemd timer to run `parse_notes.py` every 5 minutes

### 5. Grafana Dashboards

Create JSON dashboard files in `grafana/dashboards/`:

- **Overview Dashboard**: Total notes, recent activity, writing velocity
- **Time Series Dashboard**: Note creation over time, word count growth per note
- **Tag Analysis Dashboard**: Tag distribution, most used tags, tag trends
- **Note Relationships Dashboard**: Future - link graph visualization

Each dashboard will use LogQL queries to filter by Loki labels (tags, frontmatter properties).

## File Structure

```
obsidian-grafana/
├── parse_notes.py          # Main Python script
├── requirements.txt        # Python dependencies
├── config.yaml            # Configuration (vault path, etc.)
├── docker-compose.yml     # Docker stack definition
├── alloy/
│   └── config.alloy       # Alloy configuration
├── grafana/
│   └── dashboards/        # Dashboard JSON files
│       ├── overview.json
│       ├── timeseries.json
│       ├── tags.json
│       └── relationships.json
└── README.md             # Setup instructions
```

## Key Implementation Details

- Use `python-frontmatter` library for parsing YAML frontmatter
- Use `watchdog` or simple file scanning for note discovery
- Loki labels will include: `note_name`, `vault`, plus any frontmatter keys (limited to reasonable cardinality)
- Metadata changes create new timestamped entries (immutable log stream)
- Alloy configured with `loki.source.file` and `loki.write` components

### To-dos

- [x] Create Python script with Obsidian note parsing, metadata extraction, and JSON output
- [x] Set up Docker Compose with Grafana, Loki, and Alloy services
- [x] Configure Alloy to read JSON metrics and forward to Loki with proper labels
- [x] Create Grafana dashboard JSONs for overview, time series, tags, and relationships
- [x] Set up cron job or provide instructions for 5-minute scheduling
- [x] Write README with setup instructions and configuration guide
