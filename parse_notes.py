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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict
import frontmatter
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
import re

# Stopwords for word cloud filtering (common English words + markdown/URL artifacts)
STOPWORDS = frozenset([
    # Articles and determiners
    'a', 'an', 'the', 'this', 'that', 'these', 'those', 'my', 'your', 'his', 'her',
    'its', 'our', 'their', 'some', 'any', 'no', 'every', 'each', 'all', 'both',
    'few', 'more', 'most', 'other', 'such', 'own',
    # Pronouns
    'i', 'me', 'we', 'us', 'you', 'he', 'him', 'she', 'it', 'they', 'them',
    'what', 'which', 'who', 'whom', 'whose', 'myself', 'yourself', 'himself',
    'herself', 'itself', 'ourselves', 'themselves',
    # Prepositions
    'in', 'on', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into',
    'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up',
    'down', 'out', 'off', 'over', 'under', 'again', 'further', 'then', 'once',
    'of', 'as', 'until', 'while', 'upon', 'across', 'along', 'around', 'behind',
    'beside', 'beyond', 'near', 'toward', 'within', 'without',
    # Conjunctions
    'and', 'but', 'or', 'nor', 'so', 'yet', 'both', 'either', 'neither',
    'not', 'only', 'than', 'when', 'where', 'why', 'how', 'because', 'although',
    'though', 'if', 'unless', 'since', 'whether',
    # Common verbs
    'be', 'is', 'am', 'are', 'was', 'were', 'been', 'being',
    'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing', 'done',
    'will', 'would', 'shall', 'should', 'may', 'might', 'must', 'can', 'could',
    'get', 'got', 'getting', 'make', 'made', 'making', 'go', 'goes', 'went', 'going', 'gone',
    'see', 'saw', 'seen', 'know', 'knew', 'known', 'take', 'took', 'taken',
    'come', 'came', 'coming', 'want', 'use', 'used', 'using', 'find', 'found',
    'give', 'gave', 'given', 'tell', 'told', 'say', 'said', 'think', 'thought',
    'let', 'put', 'keep', 'kept', 'set', 'seem', 'seemed', 'try', 'tried',
    'leave', 'left', 'call', 'called', 'need', 'feel', 'felt', 'become', 'became',
    # Adverbs and other common words
    'here', 'there', 'now', 'just', 'also', 'very', 'too', 'well', 'back',
    'even', 'still', 'already', 'always', 'never', 'ever', 'often', 'sometimes',
    'usually', 'really', 'actually', 'probably', 'maybe', 'perhaps', 'quite',
    'rather', 'almost', 'enough', 'much', 'many', 'little', 'less', 'least',
    'first', 'last', 'next', 'new', 'old', 'good', 'bad', 'great', 'long',
    'high', 'low', 'big', 'small', 'large', 'right', 'wrong', 'true', 'false',
    'same', 'different', 'able', 'like', 'way', 'thing', 'things', 'something',
    'anything', 'everything', 'nothing', 'someone', 'anyone', 'everyone',
    'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
    # Markdown/URL artifacts
    'http', 'https', 'www', 'com', 'org', 'net', 'io', 'html', 'htm', 'php',
    'png', 'jpg', 'jpeg', 'gif', 'svg', 'pdf', 'md', 'css', 'js',
    # Common markdown elements
    'image', 'link', 'file', 'alt', 'src', 'href', 'nbsp', 'amp', 'quot',
    # JSON/code artifacts
    'null', 'true', 'false', 'undefined', 'none', 'nan',
    # Excalidraw and drawing tool properties
    'type', 'version', 'source', 'elements', 'appstate', 'files',
    'id', 'fillstyle', 'strokewidth', 'strokestyle', 'roughness', 'opacity',
    'angle', 'strokecolor', 'backgroundcolor', 'width', 'height', 'seed',
    'groupids', 'frameid', 'roundness', 'boundelements', 'updated', 'locked',
    'status', 'fileid', 'scale', 'points', 'pressures', 'simulatepressure',
    'lastcommittedpoint', 'startbinding', 'endbinding', 'startarrowhead',
    'endarrowhead', 'solid', 'transparent', 'hachure', 'crosshatch',
    'containerId', 'originaltext', 'lineheight', 'baseline', 'textalign',
    'verticalalign', 'fontsize', 'fontfamily', 'scrollx', 'scrolly', 'zoom',
    'offsetleft', 'offsettop', 'gridsize', 'viewbackgroundcolor', 'location',
    # Common CSS/styling terms that leak from embedded content
    'color', 'background', 'border', 'margin', 'padding', 'font', 'size',
    'style', 'class', 'display', 'position', 'top', 'bottom', 'center',
    # Transcript filler words
    'yeah', 'okay', 'um', 'uh', 'hmm', 'like', 'right', 'sure', 'yes', 'no',
    'gonna', 'wanna', 'gotta', 'kinda', 'sorta', 'dunno', 'alright', 'yep', 'nope',
    # Contraction fragments (when apostrophe splits the word)
    'don', 'doesn', 'didn', 'isn', 'wasn', 'aren', 'weren', 'won', 'wouldn',
    'couldn', 'shouldn', 'haven', 'hadn', 'hasn', 'ain', 'll', 've', 're',
    # URL/ID artifacts
    'asin', 'isbn', 'doi', 'ref', 'utm', 'param', 'query', 'index',
])

# Prometheus metrics
obsidian_note_total = Counter('obsidian_note_total', 'Total number of unique notes', ['vault', 'note_name', 'file_path'])
obsidian_word_count_total = Counter('obsidian_word_count_total', 'Total word count across all notes', ['vault', 'note_name', 'file_path'])
obsidian_tags_total = Counter('obsidian_tags_total', 'Total number of unique tags', ['vault', 'note_name', 'file_path'])

# Gauges for current state
obsidian_notes_gauge = Gauge('obsidian_notes_count', 'Current number of unique notes', ['vault'])
obsidian_words_gauge = Gauge('obsidian_words_total', 'Current total word count', ['vault'])
obsidian_tags_gauge = Gauge('obsidian_tags_count', 'Current number of unique tags', ['vault'])
obsidian_wikilinks_gauge = Gauge('obsidian_wikilinks_total', 'Current total number of wikilinks', ['vault'])
obsidian_note_wikilinks = Gauge('obsidian_note_wikilinks', 'Number of wikilinks in each note', ['vault', 'note_name', 'file_path'])
obsidian_word_frequency = Gauge('obsidian_word_frequency', 'Word frequency in vault (top 100 words)', ['vault', 'word'])

# Global state for metrics
metrics_data = {
    'unique_notes': set(),
    'unique_tags': set(),
    'total_words': 0,
    'vault_counts': defaultdict(lambda: {'notes': set(), 'tags': set(), 'words': 0, 'wikilinks': 0}),
    'word_frequencies': defaultdict(lambda: defaultdict(int))  # vault -> word -> count
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


def update_metrics(note_name: str, vault: str, word_count: int, tags: List[str], wikilinks_count: int = 0, file_path: str = ""):
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
    obsidian_note_total.labels(vault=vault, note_name=note_name, file_path=file_path).inc()
    obsidian_word_count_total.labels(vault=vault, note_name=note_name, file_path=file_path).inc(word_count)
    for tag in tags:
        obsidian_tags_total.labels(vault=vault, note_name=note_name, file_path=file_path).inc()
    
    # Update gauges
    obsidian_notes_gauge.labels(vault=vault).set(len(metrics_data['vault_counts'][vault]['notes']))
    obsidian_words_gauge.labels(vault=vault).set(metrics_data['vault_counts'][vault]['words'])
    obsidian_tags_gauge.labels(vault=vault).set(len(metrics_data['vault_counts'][vault]['tags']))
    obsidian_wikilinks_gauge.labels(vault=vault).set(metrics_data['vault_counts'][vault]['wikilinks'])
    obsidian_note_wikilinks.labels(vault=vault, note_name=note_name, file_path=file_path).set(wikilinks_count)


def setup_logging(log_level: str = "INFO") -> None:
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )


def extract_word_frequencies(content: str) -> Dict[str, int]:
    """Extract word frequencies from content, filtering stopwords.
    
    Args:
        content: The text content to analyze (should exclude frontmatter)
        
    Returns:
        Dictionary mapping words to their frequency counts
    """
    # Remove code blocks (including Excalidraw JSON data, code snippets, etc.)
    # Matches both fenced code blocks (```...```) and indented code blocks
    content = re.sub(r'```[\s\S]*?```', '', content)  # Fenced code blocks
    content = re.sub(r'`[^`]+`', '', content)  # Inline code
    
    # Remove Excalidraw drawing data (JSON embedded in special comments)
    content = re.sub(r'%%\s*\[\[drawing\]\][\s\S]*?%%', '', content, flags=re.IGNORECASE)
    
    # Remove any remaining JSON-like structures (arrays/objects)
    content = re.sub(r'\{[^{}]*\}', '', content)  # Simple objects
    content = re.sub(r'\[[^\[\]]*\]', '', content)  # Simple arrays
    
    # Extract words: only alphabetic characters, convert to lowercase
    words = re.findall(r'\b[a-zA-Z]+\b', content.lower())
    
    # Count frequencies, filtering stopwords and short words
    word_counts: Dict[str, int] = defaultdict(int)
    for word in words:
        # Skip stopwords, single characters, and very short words
        if word not in STOPWORDS and len(word) > 2:
            word_counts[word] += 1
    
    return dict(word_counts)


def update_word_frequency_metrics(vault: str, top_n: int = 100) -> None:
    """Update Prometheus gauges with top N word frequencies for a vault.
    
    Args:
        vault: The vault name
        top_n: Number of top words to expose as metrics (default 100)
    """
    global metrics_data
    
    word_counts = metrics_data['word_frequencies'][vault]
    if not word_counts:
        return
    
    # Get top N words sorted by frequency
    top_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    
    # Clear existing metrics for this vault to avoid stale data
    # Note: prometheus_client doesn't have a clean way to remove specific labels,
    # so we set the values for top words and they'll replace previous values
    
    for word, count in top_words:
        obsidian_word_frequency.labels(vault=vault, word=word).set(count)
    
    logging.info(f"Updated word frequency metrics: top {len(top_words)} words for vault '{vault}'")


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
    """Get file creation and modification timestamps.
    
    Uses st_birthtime (true creation time) on macOS when available,
    falls back to st_ctime (inode change time) on other platforms.
    """
    try:
        stat = file_path.stat()
        
        # Use st_birthtime (true creation time) if available (macOS)
        # Fall back to st_ctime (inode change time) on other platforms
        try:
            created_at = datetime.fromtimestamp(stat.st_birthtime).isoformat()
        except AttributeError:
            created_at = datetime.fromtimestamp(stat.st_ctime).isoformat()
        
        return {
            'created_at': created_at,
            'modified_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'modified_at_timestamp': stat.st_mtime  # Keep raw timestamp for comparison
        }
    except Exception as e:
        logging.warning(f"Error getting timestamps for {file_path}: {e}")
        return {}


def load_known_files(known_files_path: Path) -> set:
    """Load the set of known file paths from the state file.
    
    Returns an empty set if the file doesn't exist or is corrupted.
    """
    if not known_files_path.exists():
        logging.info("No known files state found. All files will be treated as 'created'.")
        return set()
    
    try:
        with open(known_files_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(data)
            else:
                logging.warning(f"Invalid known files format. Expected list, got {type(data).__name__}.")
                return set()
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"Could not read known files state: {e}. All files will be treated as 'created'.")
        return set()


def save_known_files(known_files_path: Path, known_files: set) -> None:
    """Save the set of known file paths to the state file."""
    try:
        with open(known_files_path, 'w', encoding='utf-8') as f:
            json.dump(sorted(known_files), f, indent=2)
        logging.debug(f"Saved {len(known_files)} known files to {known_files_path}")
    except IOError as e:
        logging.error(f"Could not save known files state: {e}")
        raise


def create_loki_labels(note_name: str, vault_name: str, metadata: Dict[str, Any]) -> Dict[str, str]:
    """Create Loki labels from metadata."""
    labels = {
        'vault': vault_name,
        'job': 'obsidian-parser'
    }
    
    # Add event_type if present
    if 'event_type' in metadata:
        labels['event_type'] = metadata['event_type']
    
    # Add tags as labels
    if 'tags' in metadata:
        labels['tags'] = metadata['tags']
    
    # Add frontmatter fields as labels (limit cardinality)
    for key, value in metadata.items():
        if key.startswith('frontmatter_') and len(str(value)) < 100:  # Avoid very long labels
            labels[key] = str(value)
    
    return labels


def parse_obsidian_vault_metrics_only(vault_path: str, exclude_files: set = None) -> None:
    """Parse all markdown files in the Obsidian vault and update metrics only (no file output)."""
    global metrics_data
    
    vault_path = Path(vault_path)
    if not vault_path.exists():
        raise ValueError(f"Vault path does not exist: {vault_path}")
    
    exclude_files = exclude_files or set()
    vault_name = vault_path.name
    
    # Reset word frequencies for this vault (since we're recalculating)
    metrics_data['word_frequencies'][vault_name] = defaultdict(int)
    
    # Find all markdown files
    md_files = list(vault_path.rglob("*.md"))
    logging.info(f"Found {len(md_files)} markdown files in {vault_path}")
    
    for file_path in md_files:
        try:
            # Skip hidden files and directories
            if any(part.startswith('.') for part in file_path.parts):
                continue
            
            note_name = file_path.stem
            if note_name in exclude_files:
                logging.debug(f"Skipping excluded file: {file_path.name}")
                continue
            relative_path = str(file_path.relative_to(vault_path))
            
            # Extract all metadata
            basic_stats = extract_basic_stats(file_path)
            frontmatter_metadata = extract_frontmatter_metadata(file_path)
            timestamps = get_file_timestamps(file_path)
            
            # Extract word frequencies from content (excluding frontmatter)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    post = frontmatter.load(f)
                content = post.content
                word_freqs = extract_word_frequencies(content)
                # Aggregate word frequencies for this vault
                for word, count in word_freqs.items():
                    metrics_data['word_frequencies'][vault_name][word] += count
            except Exception as e:
                logging.debug(f"Could not extract word frequencies from {file_path}: {e}")
            
            # Combine all metadata (excluding internal timestamp field)
            all_metadata = {
                **basic_stats,
                **frontmatter_metadata,
                **{k: v for k, v in timestamps.items() if k != 'modified_at_timestamp'},
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
            
            update_metrics(note_name, vault_name, basic_stats.get('word_count', 0), tags, wikilinks_count, file_path=relative_path)
            
            logging.debug(f"Processed: {relative_path}")
            
        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            continue
    
    # Update word frequency Prometheus metrics
    update_word_frequency_metrics(vault_name, top_n=100)
    
    logging.info(f"Processed {len(md_files)} files for metrics")


def parse_obsidian_vault(vault_path: str, output_file: str, exclude_files: set = None) -> None:
    """Parse all markdown files in the Obsidian vault and output to JSON.
    
    Uses event-based logging: only logs notes that were modified since the last run.
    Tracks known files to distinguish between 'created' and 'modified' events.
    """
    vault_path = Path(vault_path)
    if not vault_path.exists():
        raise ValueError(f"Vault path does not exist: {vault_path}")
    
    exclude_files = exclude_files or set()
    vault_name = vault_path.name
    entries = []
    
    # Load known files state for event_type determination
    output_dir = Path(output_file).parent
    known_files_path = output_dir / '.known_files'
    known_files = load_known_files(known_files_path)
    initial_known_files_count = len(known_files)
    
    # Get the last run timestamp
    last_run_file = output_dir / '.last_run'
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
            if note_name in exclude_files:
                logging.debug(f"Skipping excluded file: {file_path.name}")
                continue
            
            relative_path = str(file_path.relative_to(vault_path))
            
            # Extract all metadata
            basic_stats = extract_basic_stats(file_path)
            frontmatter_metadata = extract_frontmatter_metadata(file_path)
            timestamps = get_file_timestamps(file_path)
            
            # Check if note was modified since last run (event-based logging)
            if last_run_time is not None:
                modified_at_timestamp = timestamps.get('modified_at_timestamp')
                if modified_at_timestamp:
                    try:
                        # last_run_time is stored as UTC but parsed as naive datetime
                        # We need to treat it as UTC when converting to timestamp
                        # Create a UTC-aware datetime from the naive one
                        last_run_utc = last_run_time.replace(tzinfo=timezone.utc)
                        last_run_timestamp = last_run_utc.timestamp()
                        # File mtime is already a timestamp (seconds since epoch)
                        if modified_at_timestamp <= last_run_timestamp:
                            # Skip this file - not modified since last run
                            continue
                    except Exception as e:
                        logging.debug(f"Could not compare timestamps for {relative_path}: {e}")
            
            # Determine event_type based on known files state
            if relative_path in known_files:
                event_type = 'modified'
            else:
                event_type = 'created'
                known_files.add(relative_path)
            
            # Combine all metadata (excluding internal timestamp field)
            all_metadata = {
                **basic_stats,
                **frontmatter_metadata,
                **{k: v for k, v in timestamps.items() if k != 'modified_at_timestamp'},
                'file_path': relative_path,
                'note_name': note_name,
                'event_type': event_type
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
            
            update_metrics(note_name, vault_name, basic_stats.get('word_count', 0), tags, wikilinks_count, file_path=relative_path)
            
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
        
        # Save the known files state
        if len(known_files) > initial_known_files_count:
            save_known_files(known_files_path, known_files)
            logging.info(f"Known files: {initial_known_files_count} -> {len(known_files)} (+{len(known_files) - initial_known_files_count} new)")
        
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
    exclude_files = set(config.get('exclude_files', []))
    
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
            parse_obsidian_vault_metrics_only(vault_path, exclude_files)
            logging.info("Metrics parsing completed successfully")
            logging.info("Metrics server is running. Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logging.info("Shutting down...")
        else:
            parse_obsidian_vault(vault_path, output_file, exclude_files)
            logging.info("Parsing completed successfully")
    except Exception as e:
        logging.error(f"Parsing failed: {e}")
        exit(1)


if __name__ == "__main__":
    main()
