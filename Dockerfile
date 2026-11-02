FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so this layer is cached across code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application package (the only code the exporter needs)
COPY obsidian_grafana ./obsidian_grafana

# Expose the metrics port
EXPOSE 8080

# Default command (overridden in docker-compose.yml)
CMD ["python3", "-m", "obsidian_grafana.parse_notes", "--help"]
