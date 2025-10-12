#!/usr/bin/env python3
"""
Obsidian Note Parser for Grafana Monitoring

This script parses Obsidian Markdown notes and extracts metadata
for visualization in Grafana via Loki.
"""

import os
import json
import yaml
import logging
import argparse
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict
import frontmatter
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Prometheus metrics
obsidian_note_total = Counter('obsidian_note_total', 'Total number of unique notes', ['vault', 'note_name'])
obsidian_word_count_total = Counter('obsidian_word_count_total', 'Total word count across all notes', ['vault', 'note_name'])
obsidian_tags_total = Counter('obsidian_tags_total', 'Total number of unique tags', ['vault', 'note_name'])

# Gauges for current state
obsidian_notes_gauge = Gauge('obsidian_notes_count', 'Current number of unique notes', ['vault'])
obsidian_words_gauge = Gauge('obsidian_words_total', 'Current total word count', ['vault'])
obsidian_tags_gauge = Gauge('obsidian_tags_count', 'Current number of unique tags', ['vault'])
obsidian_wikilinks_gauge = Gauge('obsidian_wikilinks_total', 'Current total number of wikilinks', ['vault'])

# Global state for metrics
metrics_data = {
    'unique_notes': set(),
    'unique_tags': set(),
    'total_words': 0,
    'vault_counts': defaultdict(lambda: {'notes': set(), 'tags': set(), 'words': 0, 'wikilinks': 0})
}


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-Type', CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(generate_latest())
        else:
            self.send_response(404)
            self.end_headers()


def start_metrics_server(port: int = 8080):
    """Start the Prometheus metrics HTTP server."""
    server = HTTPServer(('0.0.0.0', port), MetricsHandler)
    logging.info(f"Starting metrics server on port {port}")
    
    def run_server():
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logging.info("Shutting down metrics server")
            server.shutdown()
    
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    return server


def update_metrics(note_name: str, vault: str, word_count: int, tags: List[str], wikilinks_count: int = 0):
    """Update Prometheus metrics with new note data."""
    global metrics_data
    
    # Update global state
    metrics_data['unique_notes'].add(note_name)
    metrics_data['total_words'] += word_count
    metrics_data['vault_counts'][vault]['notes'].add(note_name)
    metrics_data['vault_counts'][vault]['words'] += word_count
    metrics_data['vault_counts'][vault]['wikilinks'] += wikilinks_count
    
    # Add tags
    for tag in tags:
        metrics_data['unique_tags'].add(tag)
        metrics_data['vault_counts'][vault]['tags'].add(tag)
    
    # Update counters
    obsidian_note_total.labels(vault=vault, note_name=note_name).inc()
    obsidian_word_count_total.labels(vault=vault, note_name=note_name).inc(word_count)
    for tag in tags:
        obsidian_tags_total.labels(vault=vault, note_name=note_name).inc()
    
    # Update gauges
    obsidian_notes_gauge.labels(vault=vault).set(len(metrics_data['vault_counts'][vault]['notes']))
    obsidian_words_gauge.labels(vault=vault).set(metrics_data['vault_counts'][vault]['words'])
    obsidian_tags_gauge.labels(vault=vault).set(len(metrics_data['vault_counts'][vault]['tags']))
    obsidian_wikilinks_gauge.labels(vault=vault).set(metrics_data['vault_counts'][vault]['wikilinks'])


def setup_logging(log_level: str = "INFO") -> None:
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )


def extract_basic_stats(file_path: Path) -> Dict[str, Any]:
    """Extract basic statistics from a markdown file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        words = content.split()
        
        return {
            'word_count': len(words),
            'line_count': len(lines),
            'file_size': file_path.stat().st_size,
            'char_count': len(content)
        }
    except Exception as e:
        logging.warning(f"Error reading {file_path}: {e}")
        return {}


def extract_frontmatter_metadata(file_path: Path) -> Dict[str, Any]:
    """Extract YAML frontmatter and other metadata from a markdown file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
        
        metadata = {}
        
        # Extract frontmatter fields
        for key, value in post.metadata.items():
            # Convert to string for Loki labels (avoid complex types)
            if isinstance(value, (str, int, float, bool)):
                metadata[f"frontmatter_{key}"] = str(value)
            elif isinstance(value, list):
                # Join list items with comma for labels
                metadata[f"frontmatter_{key}"] = ",".join(str(item) for item in value)
        
        # Extract tags from frontmatter
        if 'tags' in post.metadata:
            tags = post.metadata['tags']
            if isinstance(tags, list):
                metadata['tags'] = ",".join(tags)
            else:
                metadata['tags'] = str(tags)
        
        # Extract inline tags from content
        content = post.content
        import re
        inline_tags = re.findall(r'#(\w+)', content)
        if inline_tags:
            metadata['inline_tags'] = ",".join(inline_tags)
        
        # Extract wikilinks for future backlink analysis
        wikilinks = re.findall(r'\[\[([^\]]+)\]\]', content)
        if wikilinks:
            metadata['wikilinks'] = ",".join(wikilinks)
        
        return metadata
    except Exception as e:
        logging.warning(f"Error parsing frontmatter for {file_path}: {e}")
        return {}


def get_file_timestamps(file_path: Path) -> Dict[str, Any]:
    """Get file creation and modification timestamps."""
    try:
        stat = file_path.stat()
        return {
            'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'modified_at': datetime.fromtimestamp(stat.st_mtime).isoformat()
        }
    except Exception as e:
        logging.warning(f"Error getting timestamps for {file_path}: {e}")
        return {}


def create_loki_labels(note_name: str, vault_name: str, metadata: Dict[str, Any]) -> Dict[str, str]:
    """Create Loki labels from metadata."""
    labels = {
        'note_name': note_name,
        'vault': vault_name,
        'job': 'obsidian-parser'
    }
    
    # Add tags as labels
    if 'tags' in metadata:
        labels['tags'] = metadata['tags']
    
    # Add frontmatter fields as labels (limit cardinality)
    for key, value in metadata.items():
        if key.startswith('frontmatter_') and len(str(value)) < 100:  # Avoid very long labels
            labels[key] = str(value)
    
    return labels


def parse_obsidian_vault_metrics_only(vault_path: str) -> None:
    """Parse all markdown files in the Obsidian vault and update metrics only (no file output)."""
    vault_path = Path(vault_path)
    if not vault_path.exists():
        raise ValueError(f"Vault path does not exist: {vault_path}")
    
    vault_name = vault_path.name
    
    # Find all markdown files
    md_files = list(vault_path.rglob("*.md"))
    logging.info(f"Found {len(md_files)} markdown files in {vault_path}")
    
    for file_path in md_files:
        try:
            # Skip hidden files and directories
            if any(part.startswith('.') for part in file_path.parts):
                continue
            
            note_name = file_path.stem
            relative_path = str(file_path.relative_to(vault_path))
            
            # Extract all metadata
            basic_stats = extract_basic_stats(file_path)
            frontmatter_metadata = extract_frontmatter_metadata(file_path)
            timestamps = get_file_timestamps(file_path)
            
            # Combine all metadata
            all_metadata = {
                **basic_stats,
                **frontmatter_metadata,
                **timestamps,
                'file_path': relative_path,
                'note_name': note_name
            }
            
            # Update Prometheus metrics
            tags = []
            if 'tags' in all_metadata:
                tags = [tag.strip() for tag in all_metadata['tags'].split(',') if tag.strip()]
            if 'inline_tags' in all_metadata:
                tags.extend([tag.strip() for tag in all_metadata['inline_tags'].split(',') if tag.strip()])
            
            # Count wikilinks
            wikilinks_count = 0
            if 'wikilinks' in all_metadata:
                wikilinks_count = len([link.strip() for link in all_metadata['wikilinks'].split(',') if link.strip()])
            
            update_metrics(note_name, vault_name, basic_stats.get('word_count', 0), tags, wikilinks_count)
            
            logging.debug(f"Processed: {relative_path}")
            
        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            continue
    
    logging.info(f"Processed {len(md_files)} files for metrics")


def parse_obsidian_vault(vault_path: str, output_file: str) -> None:
    """Parse all markdown files in the Obsidian vault and output to JSON.
    
    Uses event-based logging: only logs notes that were modified since the last run.
    """
    vault_path = Path(vault_path)
    if not vault_path.exists():
        raise ValueError(f"Vault path does not exist: {vault_path}")
    
    vault_name = vault_path.name
    entries = []
    
    # Get the last run timestamp
    last_run_file = Path(output_file).parent / '.last_run'
    last_run_time = None
    if last_run_file.exists():
        try:
            with open(last_run_file, 'r') as f:
                last_run_str = f.read().strip()
                last_run_time = datetime.fromisoformat(last_run_str)
                logging.info(f"Last run was at: {last_run_time}")
        except Exception as e:
            logging.warning(f"Could not read last run time: {e}. Processing all files.")
    else:
        logging.info("No last run file found. Processing all files.")
    
    # Find all markdown files
    md_files = list(vault_path.rglob("*.md"))
    logging.info(f"Found {len(md_files)} markdown files in {vault_path}")
    
    for file_path in md_files:
        try:
            # Skip hidden files and directories
            if any(part.startswith('.') for part in file_path.parts):
                continue
            
            note_name = file_path.stem
            relative_path = str(file_path.relative_to(vault_path))
            
            # Extract all metadata
            basic_stats = extract_basic_stats(file_path)
            frontmatter_metadata = extract_frontmatter_metadata(file_path)
            timestamps = get_file_timestamps(file_path)
            
            # Check if note was modified since last run (event-based logging)
            if last_run_time is not None:
                modified_at_str = timestamps.get('modified_at')
                if modified_at_str:
                    try:
                        modified_at = datetime.fromisoformat(modified_at_str)
                        if modified_at <= last_run_time:
                            # Skip this file - not modified since last run
                            continue
                    except Exception as e:
                        logging.debug(f"Could not parse modified_at for {relative_path}: {e}")
            
            # Combine all metadata
            all_metadata = {
                **basic_stats,
                **frontmatter_metadata,
                **timestamps,
                'file_path': relative_path,
                'note_name': note_name
            }
            
            # Create Loki labels
            labels = create_loki_labels(note_name, vault_name, all_metadata)
            
            # Create log entry
            entry = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'labels': labels,
                'line': json.dumps(all_metadata)
            }
            
            entries.append(entry)
            
            # Update Prometheus metrics
            tags = []
            if 'tags' in all_metadata:
                tags = [tag.strip() for tag in all_metadata['tags'].split(',') if tag.strip()]
            if 'inline_tags' in all_metadata:
                tags.extend([tag.strip() for tag in all_metadata['inline_tags'].split(',') if tag.strip()])
            
            # Count wikilinks
            wikilinks_count = 0
            if 'wikilinks' in all_metadata:
                wikilinks_count = len([link.strip() for link in all_metadata['wikilinks'].split(',') if link.strip()])
            
            update_metrics(note_name, vault_name, basic_stats.get('word_count', 0), tags, wikilinks_count)
            
            logging.debug(f"Processed: {relative_path}")
            
        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            continue
    
    # Record the current time before writing (for next run)
    current_run_time = datetime.utcnow()
    
    # Write to output file (event-based logging: only append changes)
    try:
        if entries:
            # Append to output file
            with open(output_file, 'a', encoding='utf-8') as f:
                for entry in entries:
                    f.write(json.dumps(entry) + '\n')
            
            logging.info(f"Appended {len(entries)} new/modified entries to {output_file}")
        else:
            logging.info("No new or modified notes to log")
        
        # Update the last run timestamp
        with open(last_run_file, 'w') as f:
            f.write(current_run_time.isoformat())
        logging.info(f"Updated last run time to {current_run_time}")
        
        # Optional: Rotate log file if it gets too large (keep last 50MB)
        max_file_size = 50 * 1024 * 1024  # 50MB
        if os.path.exists(output_file) and os.path.getsize(output_file) > max_file_size:
            timestamp = current_run_time.strftime('%Y%m%d_%H%M%S')
            rotated_file = f"{output_file}.{timestamp}"
            os.rename(output_file, rotated_file)
            logging.info(f"Rotated log file to {rotated_file}")
            
    except Exception as e:
        logging.error(f"Error writing to output file: {e}")
        raise


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Parse Obsidian notes for Grafana monitoring')
    parser.add_argument('--config', default='config.yaml', help='Configuration file path')
    parser.add_argument('--vault-path', help='Override vault path from config')
    parser.add_argument('--output', help='Override output file from config')
    parser.add_argument('--log-level', default='INFO', help='Log level')
    parser.add_argument('--metrics-port', type=int, default=8080, help='Port for Prometheus metrics server')
    parser.add_argument('--start-metrics-server', action='store_true', help='Start the Prometheus metrics server')
    
    args = parser.parse_args()
    
    # Load configuration
    config = {}
    if os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
    
    # Override with command line arguments
    vault_path = args.vault_path or config.get('vault_path')
    output_file = args.output or config.get('output_file', '/tmp/obsidian_logs.json')
    log_level = args.log_level or config.get('log_level', 'INFO')
    metrics_port = args.metrics_port or config.get('metrics_port', 8080)
    start_metrics_server_flag = args.start_metrics_server or config.get('start_metrics_server', False)
    
    if not vault_path:
        raise ValueError("Vault path must be specified in config file or --vault-path argument")
    
    setup_logging(log_level)
    
    # Start metrics server if requested
    if start_metrics_server_flag:
        start_metrics_server(metrics_port)
        logging.info(f"Metrics server started on port {metrics_port}")
    
    try:
        if start_metrics_server_flag:
            # In metrics-only mode, don't write to file, just parse for metrics
            parse_obsidian_vault_metrics_only(vault_path)
            logging.info("Metrics parsing completed successfully")
            logging.info("Metrics server is running. Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logging.info("Shutting down...")
        else:
            parse_obsidian_vault(vault_path, output_file)
            logging.info("Parsing completed successfully")
    except Exception as e:
        logging.error(f"Parsing failed: {e}")
        exit(1)


if __name__ == "__main__":
    main()
