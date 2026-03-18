#!/usr/bin/env python3
"""
Backfill event_type (created/modified) to existing log entries.

This script is a one-time migration tool that:
1. Backs up the current obsidian_logs.json
2. Processes all rotated log files in chronological order
3. Adds event_type based on first occurrence of each file_path
4. Generates the initial .known_files state
5. Validates and atomically replaces the original file

Usage:
    python backfill_event_type.py [--logs-dir /path/to/logs] [--dry-run]
"""

import argparse
import glob
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple


def setup_logging(verbose: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )


def find_rotated_files(logs_dir: Path) -> List[Path]:
    """Find all rotated log files, sorted chronologically (oldest first).
    
    Rotated files have names like obsidian_logs.json.YYYYMMDD_HHMMSS
    """
    pattern = str(logs_dir / 'obsidian_logs.json.*')
    files = glob.glob(pattern)
    
    rotated = []
    for f in files:
        path = Path(f)
        # Skip backup files we create
        if path.suffix == '.pre_backfill':
            continue
        # Extract timestamp from filename
        match = re.search(r'\.(\d{8}_\d{6})$', path.name)
        if match:
            timestamp_str = match.group(1)
            try:
                timestamp = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                rotated.append((timestamp, path))
            except ValueError:
                logging.warning(f"Could not parse timestamp from {path.name}, skipping")
                continue
    
    # Sort by timestamp (oldest first)
    rotated.sort(key=lambda x: x[0])
    return [path for _, path in rotated]


def read_log_file(file_path: Path) -> List[Dict]:
    """Read a JSON-lines log file and return parsed entries."""
    entries = []
    line_num = 0
    
    if not file_path.exists():
        logging.warning(f"File not found: {file_path}")
        return entries
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line_num += 1
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError as e:
                logging.warning(f"Invalid JSON at {file_path}:{line_num}: {e}")
                continue
    
    logging.info(f"Read {len(entries)} entries from {file_path}")
    return entries


def extract_file_path(entry: Dict) -> str:
    """Extract the file_path from a log entry's line field."""
    try:
        line_data = json.loads(entry.get('line', '{}'))
        return line_data.get('file_path', '')
    except json.JSONDecodeError:
        return ''


def add_event_type(entries: List[Dict]) -> Tuple[List[Dict], Set[str]]:
    """Add event_type to entries based on first occurrence of file_path.
    
    Returns:
        Tuple of (modified entries, set of all known file paths)
    """
    known_files: Set[str] = set()
    modified_entries = []
    created_count = 0
    modified_count = 0
    
    for entry in entries:
        file_path = extract_file_path(entry)
        
        if not file_path:
            # Can't determine event_type without file_path, keep entry as-is
            modified_entries.append(entry)
            continue
        
        # Determine event_type
        if file_path in known_files:
            event_type = 'modified'
            modified_count += 1
        else:
            event_type = 'created'
            known_files.add(file_path)
            created_count += 1
        
        # Add event_type to labels
        new_entry = entry.copy()
        if 'labels' not in new_entry:
            new_entry['labels'] = {}
        new_entry['labels'] = {**new_entry['labels'], 'event_type': event_type}
        
        # Also add event_type to the line JSON
        try:
            line_data = json.loads(entry.get('line', '{}'))
            line_data['event_type'] = event_type
            new_entry['line'] = json.dumps(line_data)
        except json.JSONDecodeError:
            pass
        
        modified_entries.append(new_entry)
    
    logging.info(f"Event types: {created_count} created, {modified_count} modified")
    return modified_entries, known_files


def validate_entries(entries: List[Dict]) -> bool:
    """Validate that all entries are valid JSON and have required fields."""
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            logging.error(f"Entry {i} is not a dict: {type(entry)}")
            return False
        if 'timestamp' not in entry:
            logging.error(f"Entry {i} missing timestamp")
            return False
        if 'labels' not in entry:
            logging.error(f"Entry {i} missing labels")
            return False
        if 'line' not in entry:
            logging.error(f"Entry {i} missing line")
            return False
        # Validate line is valid JSON
        try:
            json.loads(entry['line'])
        except json.JSONDecodeError as e:
            logging.error(f"Entry {i} has invalid line JSON: {e}")
            return False
    return True


def write_entries(entries: List[Dict], output_path: Path) -> None:
    """Write entries to a file in JSON-lines format."""
    with open(output_path, 'w', encoding='utf-8') as f:
        for entry in entries:
            f.write(json.dumps(entry) + '\n')


def save_known_files(known_files_path: Path, known_files: Set[str]) -> None:
    """Save the set of known file paths to the state file."""
    with open(known_files_path, 'w', encoding='utf-8') as f:
        json.dump(sorted(known_files), f, indent=2)
    logging.info(f"Saved {len(known_files)} known files to {known_files_path}")


def backfill(logs_dir: Path, dry_run: bool = False) -> bool:
    """Run the backfill process.
    
    Returns True on success, False on failure.
    """
    main_log = logs_dir / 'obsidian_logs.json'
    backup_path = logs_dir / 'obsidian_logs.json.pre_backfill'
    known_files_path = logs_dir / '.known_files'
    
    # Check main log exists
    if not main_log.exists():
        logging.error(f"Main log file not found: {main_log}")
        return False
    
    # Step 1: Create backup
    if not dry_run:
        if backup_path.exists():
            logging.warning(f"Backup already exists: {backup_path}")
            response = input("Overwrite backup? [y/N] ").strip().lower()
            if response != 'y':
                logging.info("Aborting")
                return False
        logging.info(f"Creating backup: {backup_path}")
        shutil.copy2(main_log, backup_path)
    else:
        logging.info(f"[DRY RUN] Would create backup: {backup_path}")
    
    # Step 2: Find and read all rotated files
    rotated_files = find_rotated_files(logs_dir)
    logging.info(f"Found {len(rotated_files)} rotated log files")
    
    all_entries = []
    
    # Read rotated files first (oldest to newest)
    for rotated_file in rotated_files:
        entries = read_log_file(rotated_file)
        all_entries.extend(entries)
    
    # Then read main log
    main_entries = read_log_file(main_log)
    all_entries.extend(main_entries)
    
    total_input = len(all_entries)
    logging.info(f"Total entries to process: {total_input}")
    
    if total_input == 0:
        logging.warning("No entries found, nothing to do")
        return True
    
    # Step 3: Sort by timestamp to ensure chronological order
    def get_timestamp(entry: Dict) -> str:
        return entry.get('timestamp', '')
    
    all_entries.sort(key=get_timestamp)
    
    # Step 4: Add event_type
    modified_entries, known_files = add_event_type(all_entries)
    
    # Step 5: Validate
    logging.info("Validating output entries...")
    if not validate_entries(modified_entries):
        logging.error("Validation failed!")
        return False
    
    if len(modified_entries) != total_input:
        logging.error(f"Entry count mismatch: input={total_input}, output={len(modified_entries)}")
        return False
    
    logging.info(f"Validation passed: {len(modified_entries)} entries")
    
    if dry_run:
        logging.info("[DRY RUN] Would write entries and known files")
        logging.info(f"[DRY RUN] Sample entry: {json.dumps(modified_entries[0], indent=2)[:500]}")
        return True
    
    # Step 6: Write to temporary file first
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, dir=logs_dir) as tmp:
        tmp_path = Path(tmp.name)
    
    try:
        write_entries(modified_entries, tmp_path)
        
        # Verify the temp file
        verify_entries = read_log_file(tmp_path)
        if len(verify_entries) != len(modified_entries):
            logging.error(f"Verification failed: wrote {len(modified_entries)}, read back {len(verify_entries)}")
            tmp_path.unlink()
            return False
        
        # Step 7: Atomic replace
        logging.info(f"Replacing {main_log} with backfilled data")
        os.replace(tmp_path, main_log)
        
        # Step 8: Save known files state
        save_known_files(known_files_path, known_files)
        
        logging.info("Backfill completed successfully!")
        logging.info(f"  - Processed {len(modified_entries)} entries")
        logging.info(f"  - {len(known_files)} unique files tracked")
        logging.info(f"  - Backup saved at {backup_path}")
        
        return True
        
    except Exception as e:
        logging.error(f"Error during write: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Backfill event_type to existing log entries'
    )
    parser.add_argument(
        '--logs-dir',
        type=Path,
        default=Path(__file__).parent / 'logs',
        help='Directory containing log files (default: ./logs)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    logs_dir = args.logs_dir.resolve()
    logging.info(f"Logs directory: {logs_dir}")
    
    if not logs_dir.exists():
        logging.error(f"Logs directory not found: {logs_dir}")
        sys.exit(1)
    
    success = backfill(logs_dir, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
