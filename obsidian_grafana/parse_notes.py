#!/usr/bin/env python3
"""
Obsidian Note Parser for Grafana Monitoring

This script parses Obsidian Markdown notes and extracts metadata
for visualization in Grafana via Loki.
"""

import os
import sys
import json
import yaml
import logging
import argparse
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict
import frontmatter
from prometheus_client import REGISTRY, CollectorRegistry, Gauge, Histogram, start_http_server as prometheus_start_http_server
import re

# Defaults shared by the CLI and the config file (config.yaml overrides, CLI overrides both)
DEFAULT_OUTPUT_FILE = './logs/obsidian_logs.json'
DEFAULT_LOG_LEVEL = 'INFO'
DEFAULT_METRICS_PORT = 8080
# Seconds between vault re-scans when running the metrics exporter (matches the 5 minute cron cadence)
DEFAULT_REFRESH_INTERVAL = 300
# Low-series aggregates: how many most-linked notes to expose (0 disables) and the folder series cap
DEFAULT_TOP_LINKED_NOTES = 50
DEFAULT_MAX_FOLDERS = 50
ROOT_FOLDER = '(root)'
OTHER_FOLDER = '(other)'
# Upper bounds (in words) of the note length histogram; +Inf is added automatically
NOTE_LENGTH_BUCKETS = (10, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
# Upper bounds of the outgoing links per note histogram (le="0" counts notes without outgoing links)
NOTE_LINK_BUCKETS = (0, 1, 2, 5, 10)

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

# Prometheus metrics. Only low-cardinality series are exposed: nothing is labelled per note
# (per-note facts live in the Loki note events), so the same series can be used locally and in Grafana Cloud.
obsidian_notes_gauge = Gauge('obsidian_notes_count', 'Current number of unique notes', ['vault'])
obsidian_words_gauge = Gauge('obsidian_words_total', 'Current total word count', ['vault'])
obsidian_tags_gauge = Gauge('obsidian_tags_count', 'Current number of unique tags', ['vault'])
obsidian_wikilinks_gauge = Gauge('obsidian_wikilinks_total', 'Current total number of wikilinks', ['vault'])
obsidian_word_frequency = Gauge('obsidian_word_frequency', 'Word frequency in vault (top 100 words)', ['vault', 'word'])

# Low-series aggregates (safe to forward to Grafana Cloud: cardinality does not grow with the note count)
obsidian_folder_notes = Gauge('obsidian_folder_notes', 'Number of notes per top-level folder', ['vault', 'folder'])
obsidian_folder_words = Gauge('obsidian_folder_words', 'Total word count per top-level folder', ['vault', 'folder'])
obsidian_folder_wikilinks = Gauge('obsidian_folder_wikilinks', 'Total wikilinks per top-level folder', ['vault', 'folder'])
obsidian_folder_tags = Gauge('obsidian_folder_tags', 'Number of unique tags per top-level folder', ['vault', 'folder'])
obsidian_note_length_words = Histogram(
    'obsidian_note_length_words', 'Distribution of note length in words', ['vault'], buckets=NOTE_LENGTH_BUCKETS)
obsidian_note_outlinks = Histogram(
    'obsidian_note_outlinks', 'Distribution of outgoing wikilinks per note', ['vault'], buckets=NOTE_LINK_BUCKETS)
obsidian_top_linked_note_backlinks = Gauge(
    'obsidian_top_linked_note_backlinks', 'Backlinks (distinct notes linking in) for the most-linked notes',
    ['vault', 'note_name'])

# Global state for metrics
metrics_data = {
    'unique_notes': set(),
    'unique_tags': set(),
    'total_words': 0,
    'vault_counts': defaultdict(lambda: {'notes': set(), 'tags': set(), 'words': 0, 'wikilinks': 0}),
    'word_frequencies': defaultdict(lambda: defaultdict(int))  # vault -> word -> count
}


_snapshot_lock = threading.Lock()


class _SnapshotCollector:
    """Serve the default registry, waiting while a refresh is swapping in a new snapshot."""

    def collect(self):
        with _snapshot_lock:
            return list(REGISTRY.collect())


def start_metrics_server(port: int = DEFAULT_METRICS_PORT):
    """Start the Prometheus metrics HTTP server (serves /metrics from the default registry)."""
    scrape_registry = CollectorRegistry()
    scrape_registry.register(_SnapshotCollector())
    result = prometheus_start_http_server(port, registry=scrape_registry)
    logging.info(f"Starting metrics server on port {port}")
    return result


def update_metrics(note_name: str, vault: str, word_count: int, tags: List[str], wikilinks_count: int = 0):
    """Update the vault totals with new note data."""
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
    
    # Update gauges
    obsidian_notes_gauge.labels(vault=vault).set(len(metrics_data['vault_counts'][vault]['notes']))
    obsidian_words_gauge.labels(vault=vault).set(metrics_data['vault_counts'][vault]['words'])
    obsidian_tags_gauge.labels(vault=vault).set(len(metrics_data['vault_counts'][vault]['tags']))
    obsidian_wikilinks_gauge.labels(vault=vault).set(metrics_data['vault_counts'][vault]['wikilinks'])


def _top_level_folder(file_path: str) -> str:
    parts = Path(file_path).parts
    return parts[0] if len(parts) > 1 else ROOT_FOLDER


def _link_target(raw: str) -> str:
    """Normalise the inside of a [[wikilink]] to a note name (drop alias, heading, folder and .md)."""
    target = raw.split('|')[0].split('#')[0].strip()
    if target.endswith('.md'):
        target = target[:-3]
    return target.rsplit('/', 1)[-1].strip()


def compute_backlinks(notes: List[Dict[str, Any]]) -> Dict[str, int]:
    """Map note_name -> number of distinct notes linking to it (links to missing notes are ignored)."""
    canonical: Dict[str, str] = {}
    for note in notes:
        canonical.setdefault(note['note_name'].casefold(), note['note_name'])
    sources: Dict[str, set] = defaultdict(set)
    for note in notes:
        for raw in note.get('link_targets', []):
            name = canonical.get(_link_target(raw).casefold())
            if name is not None and name != note['note_name']:
                sources[name].add(note['file_path'])
    return {name: len(srcs) for name, srcs in sources.items()}


def update_aggregate_metrics(vault: str, notes: List[Dict[str, Any]],
                             top_linked_notes: int = DEFAULT_TOP_LINKED_NOTES,
                             max_folders: int = DEFAULT_MAX_FOLDERS) -> None:
    """Expose low-cardinality aggregates: per top-level folder totals, note length histogram, most-linked notes.

    Series count is bounded by ``max_folders`` (+1 for the '(other)' bucket) and ``top_linked_notes``
    regardless of how many notes the vault has.
    """
    folders: Dict[str, Dict[str, Any]] = defaultdict(lambda: {'notes': 0, 'words': 0, 'wikilinks': 0, 'tags': set()})
    for note in notes:
        agg = folders[_top_level_folder(note['file_path'])]
        agg['notes'] += 1
        agg['words'] += note['word_count']
        agg['wikilinks'] += note['wikilinks_count']
        agg['tags'].update(note['tags'])
        obsidian_note_length_words.labels(vault=vault).observe(note['word_count'])
        obsidian_note_outlinks.labels(vault=vault).observe(note['wikilinks_count'])

    # Keep the largest folders; fold the rest into one bucket so cardinality stays bounded
    ranked = sorted(folders.items(), key=lambda kv: (-kv[1]['notes'], kv[0]))
    kept, rest = ranked[:max_folders], ranked[max_folders:]
    if rest:
        other: Dict[str, Any] = {'notes': 0, 'words': 0, 'wikilinks': 0, 'tags': set()}
        for _, agg in rest:
            other['notes'] += agg['notes']
            other['words'] += agg['words']
            other['wikilinks'] += agg['wikilinks']
            other['tags'] |= agg['tags']
        kept.append((OTHER_FOLDER, other))
    for folder, agg in kept:
        obsidian_folder_notes.labels(vault=vault, folder=folder).set(agg['notes'])
        obsidian_folder_words.labels(vault=vault, folder=folder).set(agg['words'])
        obsidian_folder_wikilinks.labels(vault=vault, folder=folder).set(agg['wikilinks'])
        obsidian_folder_tags.labels(vault=vault, folder=folder).set(len(agg['tags']))

    if top_linked_notes > 0:
        backlinks = compute_backlinks(notes)
        top = sorted(backlinks.items(), key=lambda kv: (-kv[1], kv[0]))[:top_linked_notes]
        for note_name, count in top:
            obsidian_top_linked_note_backlinks.labels(vault=vault, note_name=note_name).set(count)


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
    word_counts = metrics_data['word_frequencies'][vault]
    if not word_counts:
        return
    
    # Get top N words sorted by frequency
    top_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    
    # Stale words are dropped by reset_metrics() before every exporter re-scan.
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


def reset_metrics() -> None:
    """Drop all accumulated metric state so a fresh vault scan can repopulate it.

    Without this, every re-scan would add to the counters and sums built by the
    previous one, and notes or words that no longer exist would never disappear.
    """
    metrics_data['unique_notes'] = set()
    metrics_data['unique_tags'] = set()
    metrics_data['total_words'] = 0
    metrics_data['vault_counts'].clear()
    metrics_data['word_frequencies'].clear()
    for metric in (
        obsidian_notes_gauge,
        obsidian_words_gauge,
        obsidian_tags_gauge,
        obsidian_wikilinks_gauge,
        obsidian_word_frequency,
        obsidian_folder_notes,
        obsidian_folder_words,
        obsidian_folder_wikilinks,
        obsidian_folder_tags,
        obsidian_note_length_words,
        obsidian_note_outlinks,
        obsidian_top_linked_note_backlinks,
    ):
        metric.clear()


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(',') if item.strip()]


def _note_tags_and_wikilinks(all_metadata: Dict[str, Any]):
    """Return (tags, wikilink_count) from the comma-joined metadata fields."""
    tags: List[str] = []
    if 'tags' in all_metadata:
        tags = _split_csv(all_metadata['tags'])
    if 'inline_tags' in all_metadata:
        tags.extend(_split_csv(all_metadata['inline_tags']))
    wikilinks_count = len(_split_csv(all_metadata['wikilinks'])) if 'wikilinks' in all_metadata else 0
    return tags, wikilinks_count


def collect_vault_metrics(vault_path: str, exclude_files: Optional[set] = None) -> Dict[str, Any]:
    """Scan the vault and return per-note metric inputs without touching any metric.

    Keeping the (slow) filesystem scan separate from the (fast) metric update lets
    the exporter swap in a complete new snapshot instead of exposing a half-built one.
    """
    vault_path = Path(vault_path)
    if not vault_path.exists():
        raise ValueError(f"Vault path does not exist: {vault_path}")

    exclude_files = exclude_files or set()
    vault_name = vault_path.name
    notes: List[Dict[str, Any]] = []
    word_frequencies: Dict[str, int] = defaultdict(int)

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

            # Extract word frequencies and link targets from content (excluding frontmatter)
            link_targets: List[str] = []
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    post = frontmatter.load(f)
                link_targets = re.findall(r'\[\[([^\]]+)\]\]', post.content)
                for word, count in extract_word_frequencies(post.content).items():
                    word_frequencies[word] += count
            except Exception as e:
                logging.debug(f"Could not extract word frequencies from {file_path}: {e}")

            tags, wikilinks_count = _note_tags_and_wikilinks(frontmatter_metadata)
            notes.append({
                'note_name': note_name,
                'file_path': relative_path,
                'word_count': basic_stats.get('word_count', 0),
                'tags': tags,
                'wikilinks_count': wikilinks_count,
                'link_targets': link_targets,
            })

            logging.debug(f"Processed: {relative_path}")

        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            continue

    logging.info(f"Processed {len(md_files)} files for metrics")
    return {'vault': vault_name, 'notes': notes, 'word_frequencies': dict(word_frequencies)}


def parse_obsidian_vault_metrics_only(
    vault_path: str,
    exclude_files: Optional[set] = None,
    top_linked_notes: int = DEFAULT_TOP_LINKED_NOTES,
    max_folders: int = DEFAULT_MAX_FOLDERS,
) -> None:
    """Parse all markdown files in the Obsidian vault and replace the metrics (no file output).

    Safe to call repeatedly: each call discards the previous snapshot and rebuilds it.
    Exposes vault totals, folder aggregates, note length / outgoing link histograms, the
    most-linked notes and the word frequencies; there are no per-note series.
    """
    scan = collect_vault_metrics(vault_path, exclude_files)
    vault_name = scan['vault']

    with _snapshot_lock:
        reset_metrics()
        for note in scan['notes']:
            update_metrics(
                note['note_name'], vault_name, note['word_count'], note['tags'],
                note['wikilinks_count'],
            )
        update_aggregate_metrics(vault_name, scan['notes'], top_linked_notes, max_folders)
        metrics_data['word_frequencies'][vault_name] = defaultdict(int, scan['word_frequencies'])
        update_word_frequency_metrics(vault_name, top_n=100)


def run_metrics_exporter(
    vault_path: str,
    exclude_files: Optional[set] = None,
    refresh_interval: float = DEFAULT_REFRESH_INTERVAL,
    stop_event: Optional[threading.Event] = None,
    top_linked_notes: int = DEFAULT_TOP_LINKED_NOTES,
    max_folders: int = DEFAULT_MAX_FOLDERS,
) -> None:
    """Scan the vault, then keep re-scanning every ``refresh_interval`` seconds until stopped.

    The first scan must succeed (a bad vault path is a configuration error). Later
    scan failures are logged and the previous snapshot keeps being served.
    """
    if refresh_interval <= 0:
        raise ValueError("refresh interval must be greater than zero")
    stop_event = stop_event or threading.Event()

    def scan() -> None:
        parse_obsidian_vault_metrics_only(vault_path, exclude_files, top_linked_notes, max_folders)

    scan()
    logging.info("Metrics parsing completed successfully")
    logging.info(f"Metrics server is running; re-scanning every {refresh_interval:g}s. Press Ctrl+C to stop.")

    while not stop_event.wait(refresh_interval):
        try:
            scan()
        except Exception as e:
            logging.error(f"Metrics refresh failed, keeping previous values: {e}")


def _utcnow() -> datetime:
    """Naive UTC timestamp (the format already used in log entries and .last_run)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
            # Numeric, so LogQL can unwrap it (the 'wikilinks' field is the comma-joined list)
            all_metadata['wikilink_count'] = _note_tags_and_wikilinks(all_metadata)[1]
            
            # Create Loki labels
            labels = create_loki_labels(note_name, vault_name, all_metadata)
            
            # Create log entry
            entry = {
                'timestamp': _utcnow().isoformat() + 'Z',
                'labels': labels,
                'line': json.dumps(all_metadata)
            }
            
            entries.append(entry)
            
            # Update Prometheus metrics
            tags, wikilinks_count = _note_tags_and_wikilinks(all_metadata)
            update_metrics(note_name, vault_name, basic_stats.get('word_count', 0), tags, wikilinks_count)
            
            logging.debug(f"Processed: {relative_path}")
            
        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            continue
    
    # Record the current time before writing (for next run)
    current_run_time = _utcnow()
    
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


def _setting(cli_value, config: Dict[str, Any], key: str, default):
    """Resolve a setting: CLI argument, then config file, then built-in default."""
    if cli_value is not None:
        return cli_value
    value = config.get(key)
    return default if value is None else value


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Parse Obsidian notes for Grafana monitoring')
    parser.add_argument('--config', default='config.yaml', help='Configuration file path')
    parser.add_argument('--vault-path', help='Override vault path from config')
    parser.add_argument('--output', help=f'Override output file from config (default: {DEFAULT_OUTPUT_FILE})')
    parser.add_argument('--log-level', help=f'Log level (default: config log_level, else {DEFAULT_LOG_LEVEL})')
    parser.add_argument('--metrics-port', type=int,
                        help=f'Port for Prometheus metrics server (default: config metrics_port, else {DEFAULT_METRICS_PORT})')
    parser.add_argument('--refresh-interval', type=float,
                        help='Seconds between vault re-scans when the metrics server is running '
                             f'(default: config metrics_refresh_interval, else {DEFAULT_REFRESH_INTERVAL})')
    parser.add_argument('--top-linked-notes', type=int,
                        help='How many most-linked notes to expose as obsidian_top_linked_note_backlinks, 0 to disable '
                             f'(default: config top_linked_notes, else {DEFAULT_TOP_LINKED_NOTES})')
    parser.add_argument('--max-folders', type=int,
                        help='Max top-level folders exposed individually; the rest are folded into "(other)" '
                             f'(default: config max_folders, else {DEFAULT_MAX_FOLDERS})')
    parser.add_argument('--start-metrics-server', action='store_true', help='Start the Prometheus metrics server')
    return parser


def main(argv: Optional[List[str]] = None):
    """Main entry point."""
    args = build_arg_parser().parse_args(argv)

    # Load configuration
    config: Dict[str, Any] = {}
    if os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f) or {}

    # Resolve settings: command line > config file > built-in default
    vault_path = args.vault_path or config.get('vault_path')
    output_file = _setting(args.output, config, 'output_file', DEFAULT_OUTPUT_FILE)
    log_level = _setting(args.log_level, config, 'log_level', DEFAULT_LOG_LEVEL)
    metrics_port = _setting(args.metrics_port, config, 'metrics_port', DEFAULT_METRICS_PORT)
    refresh_interval = _setting(args.refresh_interval, config, 'metrics_refresh_interval', DEFAULT_REFRESH_INTERVAL)
    top_linked_notes = int(_setting(args.top_linked_notes, config, 'top_linked_notes', DEFAULT_TOP_LINKED_NOTES))
    max_folders = int(_setting(args.max_folders, config, 'max_folders', DEFAULT_MAX_FOLDERS))
    start_metrics_server_flag = args.start_metrics_server or config.get('start_metrics_server', False)
    exclude_files = set(config.get('exclude_files', []))

    if not vault_path:
        raise ValueError("Vault path must be specified in config file or --vault-path argument")

    setup_logging(log_level)

    try:
        if start_metrics_server_flag:
            # In metrics-only mode, don't write to file, just parse for metrics
            start_metrics_server(int(metrics_port))
            logging.info(f"Metrics server started on port {metrics_port}")
            try:
                run_metrics_exporter(
                    vault_path, exclude_files, float(refresh_interval),
                    top_linked_notes=top_linked_notes, max_folders=max_folders,
                )
            except KeyboardInterrupt:
                logging.info("Shutting down...")
        else:
            parse_obsidian_vault(vault_path, output_file, exclude_files)
            logging.info("Parsing completed successfully")
    except Exception as e:
        logging.error(f"Parsing failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
