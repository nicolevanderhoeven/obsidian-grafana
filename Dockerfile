FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the parse_notes.py script
COPY parse_notes.py .

# Expose the metrics port
EXPOSE 8080

# Default command (can be overridden in docker-compose.yml)
CMD ["python3", "parse_notes.py", "--help"]
