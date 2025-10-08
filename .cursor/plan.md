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
- **Note Relationships Dashboard**: Wikilinks and backlink analysis
- **Frontmatter Types Analysis Dashboard**: Distribution and usage patterns of frontmatter types

Each dashboard uses LogQL queries to filter by Loki labels (tags, frontmatter properties, types).

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
│       ├── relationships.json
│       └── types.json
└── README.md             # Setup instructions
```

## Key Implementation Details

- Use `python-frontmatter` library for parsing YAML frontmatter
- Use `watchdog` or simple file scanning for note discovery
- Loki labels include: `note_name`, `vault`, `tags`, plus frontmatter fields (limited to reasonable cardinality)
- Frontmatter fields are prefixed with `frontmatter_` (e.g., `frontmatter_type`, `frontmatter_category`)
- Metadata changes create new timestamped entries (immutable log stream)
- Alloy configured with `loki.source.file` and `loki.write` components
- Prometheus metrics integration for real-time monitoring

## Frontmatter Types Implementation

### Python Parser (`parse_notes.py`)

The parser extracts all frontmatter fields and processes them as labels:

```python
# Extract frontmatter fields
for key, value in post.metadata.items():
    if isinstance(value, (str, int, float, bool)):
        metadata[f"frontmatter_{key}"] = str(value)
    elif isinstance(value, list):
        metadata[f"frontmatter_{key}"] = ",".join(str(item) for item in value)

# Create Loki labels
labels = {
    'note_name': note_name,
    'vault': vault_name,
    'job': 'obsidian-parser'
}

# Add frontmatter fields as labels
for key, value in metadata.items():
    if key.startswith('frontmatter_') and len(str(value)) < 100:
        labels[key] = str(value)
```

### Alloy Configuration (`alloy/config.alloy`)

Alloy extracts frontmatter fields and creates Loki labels:

```alloy
stage.json {
  expressions = {
    timestamp = "timestamp",
    vault = "labels.vault",
    job = "labels.job",
    tags = "labels.tags",
    frontmatter_status = "labels.frontmatter_status",
    frontmatter_category = "labels.frontmatter_category",
    frontmatter_priority = "labels.frontmatter_priority",
    frontmatter_type = "labels.frontmatter_type",
  }
}

stage.labels {
  values = {
    vault = "",
    job = "",
    tags = "",
    frontmatter_status = "",
    frontmatter_category = "",
    frontmatter_priority = "",
    frontmatter_type = "",
  }
}
```

## LogQL Query Examples

### Basic Queries

```logql
# All notes
{job="obsidian-parser"}

# Notes with specific tag
{job="obsidian-parser"} | json | tags=~".*research.*"

# Notes by category
{job="obsidian-parser"} | json | frontmatter_category="work"

# Notes by type
{job="obsidian-parser"} | json | frontmatter_type="NPC"
```

### Time Series Queries

```logql
# Word count over time
sum by (note_name) (avg_over_time({job="obsidian-parser"} | json | unwrap word_count [5m]))

# Tag usage trends
sum by (tags) (count_over_time({job="obsidian-parser"} | json | tags != "" [1h]))

# Type distribution over time
sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [1h]))
```

### Frontmatter Type Analysis Queries

```logql
# All notes with frontmatter types
{job="obsidian-parser"} | json | frontmatter_type != ""

# Type distribution (for pie charts)
sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [1h]))

# Types by vault
sum by (frontmatter_type, vault) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [1d]))

# Most common types
topk(10, sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [7d])))
```

### Dashboard-Specific Queries

#### Overview Dashboard
```logql
# Total notes processed
sum(count_over_time({job="obsidian-parser"}[1h]))

# Processing rate
rate({job="obsidian-parser"}[5m])
```

#### Types Analysis Dashboard
```logql
# Type distribution (1 hour)
sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [1h]))

# Type distribution (1 day)
sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [1d]))

# Type distribution (7 days)
sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [7d]))

# Types over time
sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [1d]))

# Types by vault
sum by (frontmatter_type, vault) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [7d]))
```

## Frontmatter Types Dashboard Architecture

### Dashboard Panels

1. **Pie Chart (Last Hour)**: `sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [1h]))`
2. **Time Series (Last Day)**: `sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [1d]))`
3. **Bar Chart (Last Hour)**: Same as pie chart but with bar visualization
4. **Donut Chart (Last Day)**: Same as time series but with donut visualization
5. **Time Series by Vault (7 Days)**: `sum by (frontmatter_type, vault) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [7d]))`
6. **Pie Chart (7 Days)**: `sum by (frontmatter_type) (count_over_time({job="obsidian-parser"} | json | frontmatter_type != "" [7d]))`
7. **Bar Chart (7 Days)**: Same as 7-day pie chart but with bar visualization

### Dashboard Features

- **Multiple Time Ranges**: 1 hour, 1 day, 7 days
- **Visualization Types**: Pie charts, donut charts, bar charts, time series
- **Vault Breakdown**: Compare types across different vaults
- **Real-time Updates**: 5-second refresh rate
- **Responsive Layout**: 24-column grid system

### To-dos

- [x] Create Python script with Obsidian note parsing, metadata extraction, and JSON output
- [x] Set up Docker Compose with Grafana, Loki, and Alloy services
- [x] Configure Alloy to read JSON metrics and forward to Loki with proper labels
- [x] Create Grafana dashboard JSONs for overview, time series, tags, and relationships
- [x] Set up cron job or provide instructions for 5-minute scheduling
- [x] Write README with setup instructions and configuration guide
- [x] Add frontmatter types as Loki labels for filtering and analysis
- [x] Create Frontmatter Types Analysis dashboard with pie charts and time series
- [x] Update Alloy configuration to extract frontmatter_type labels
- [x] Add comprehensive LogQL query examples and implementation details
