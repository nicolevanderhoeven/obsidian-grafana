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
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import frontmatter


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


def parse_obsidian_vault(vault_path: str, output_file: str) -> None:
    """Parse all markdown files in the Obsidian vault and output to JSON."""
    vault_path = Path(vault_path)
    if not vault_path.exists():
        raise ValueError(f"Vault path does not exist: {vault_path}")
    
    vault_name = vault_path.name
    entries = []
    
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
            
            # Create Loki labels
            labels = create_loki_labels(note_name, vault_name, all_metadata)
            
            # Create log entry
            entry = {
                'timestamp': datetime.now().isoformat(),
                'labels': labels,
                'line': json.dumps(all_metadata)
            }
            
            entries.append(entry)
            logging.debug(f"Processed: {relative_path}")
            
        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            continue
    
    # Write to output file
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')
        
        logging.info(f"Wrote {len(entries)} entries to {output_file}")
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
    
    if not vault_path:
        raise ValueError("Vault path must be specified in config file or --vault-path argument")
    
    setup_logging(log_level)
    
    try:
        parse_obsidian_vault(vault_path, output_file)
        logging.info("Parsing completed successfully")
    except Exception as e:
        logging.error(f"Parsing failed: {e}")
        exit(1)


if __name__ == "__main__":
    main()
