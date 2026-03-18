"""Tests for event_type functionality in parse_notes.py and backfill_event_type.py"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from parse_notes import load_known_files, save_known_files
from backfill_event_type import (
    add_event_type,
    extract_file_path,
    find_rotated_files,
    read_log_file,
    validate_entries,
)


class TestKnownFilesState:
    """Tests for load_known_files and save_known_files."""

    def test_load_nonexistent_file_returns_empty_set(self, tmp_path):
        """First run with no .known_files -- all files should be treated as 'created'."""
        known_files_path = tmp_path / '.known_files'
        result = load_known_files(known_files_path)
        assert result == set()

    def test_save_and_load_roundtrip(self, tmp_path):
        """Known files should persist across runs."""
        known_files_path = tmp_path / '.known_files'
        original = {'path/to/note1.md', 'path/to/note2.md', 'subfolder/note3.md'}
        
        save_known_files(known_files_path, original)
        loaded = load_known_files(known_files_path)
        
        assert loaded == original

    def test_load_corrupt_json_returns_empty_set(self, tmp_path):
        """Missing or corrupt .known_files -- graceful fallback to treating all as 'created'."""
        known_files_path = tmp_path / '.known_files'
        known_files_path.write_text('this is not valid json {{{')
        
        result = load_known_files(known_files_path)
        assert result == set()

    def test_load_wrong_type_returns_empty_set(self, tmp_path):
        """Invalid format (not a list) should fallback to empty set."""
        known_files_path = tmp_path / '.known_files'
        known_files_path.write_text('{"type": "dict instead of list"}')
        
        result = load_known_files(known_files_path)
        assert result == set()

    def test_load_empty_file_returns_empty_set(self, tmp_path):
        """Empty file should return empty set."""
        known_files_path = tmp_path / '.known_files'
        known_files_path.write_text('')
        
        result = load_known_files(known_files_path)
        assert result == set()

    def test_save_creates_sorted_json(self, tmp_path):
        """Saved file should be human-readable sorted JSON."""
        known_files_path = tmp_path / '.known_files'
        files = {'c.md', 'a.md', 'b.md'}
        
        save_known_files(known_files_path, files)
        content = known_files_path.read_text()
        data = json.loads(content)
        
        assert data == ['a.md', 'b.md', 'c.md']


class TestEventTypeDetermination:
    """Tests for event_type determination in backfill."""

    def _make_entry(self, file_path: str, timestamp: str = '2024-01-01T00:00:00Z') -> dict:
        """Create a minimal log entry for testing."""
        return {
            'timestamp': timestamp,
            'labels': {'vault': 'test', 'job': 'obsidian-parser'},
            'line': json.dumps({
                'file_path': file_path,
                'note_name': Path(file_path).stem,
                'word_count': 100
            })
        }

    def test_first_occurrence_is_created(self):
        """First occurrence of a file_path should be 'created'."""
        entries = [self._make_entry('note.md')]
        result, known = add_event_type(entries)
        
        assert result[0]['labels']['event_type'] == 'created'
        assert 'note.md' in known

    def test_subsequent_occurrence_is_modified(self):
        """Subsequent run -- re-seen files should be 'modified'."""
        entries = [
            self._make_entry('note.md', '2024-01-01T00:00:00Z'),
            self._make_entry('note.md', '2024-01-02T00:00:00Z'),
        ]
        result, known = add_event_type(entries)
        
        assert result[0]['labels']['event_type'] == 'created'
        assert result[1]['labels']['event_type'] == 'modified'

    def test_new_files_in_subsequent_run_are_created(self):
        """Subsequent run -- new files should be 'created'."""
        entries = [
            self._make_entry('note1.md', '2024-01-01T00:00:00Z'),
            self._make_entry('note2.md', '2024-01-02T00:00:00Z'),
            self._make_entry('note1.md', '2024-01-03T00:00:00Z'),
        ]
        result, known = add_event_type(entries)
        
        assert result[0]['labels']['event_type'] == 'created'
        assert result[1]['labels']['event_type'] == 'created'
        assert result[2]['labels']['event_type'] == 'modified'

    def test_event_type_added_to_line_json(self):
        """Event type should also be in the line JSON."""
        entries = [self._make_entry('note.md')]
        result, _ = add_event_type(entries)
        
        line_data = json.loads(result[0]['line'])
        assert line_data['event_type'] == 'created'

    def test_deleted_file_reappearing_is_created(self):
        """Deleted file reappearing -- treated as 'created' again (not in known_files)."""
        entries = [
            self._make_entry('note.md', '2024-01-01T00:00:00Z'),
            self._make_entry('note.md', '2024-01-02T00:00:00Z'),
        ]
        result, known = add_event_type(entries)
        
        # Simulate deletion by removing from known_files
        known.discard('note.md')
        
        new_entries = [self._make_entry('note.md', '2024-01-03T00:00:00Z')]
        result2, _ = add_event_type(new_entries)
        
        # Should be 'created' again since it was removed from known_files
        assert result2[0]['labels']['event_type'] == 'created'


class TestBackfillChronologicalOrder:
    """Tests for backfill with entries out of chronological order."""

    def _make_entry(self, file_path: str, timestamp: str) -> dict:
        return {
            'timestamp': timestamp,
            'labels': {'vault': 'test', 'job': 'obsidian-parser'},
            'line': json.dumps({'file_path': file_path, 'note_name': Path(file_path).stem})
        }

    def test_out_of_order_entries_processed_correctly(self):
        """Backfill with entries out of chronological order."""
        # Entries are NOT in chronological order
        entries = [
            self._make_entry('note.md', '2024-01-03T00:00:00Z'),  # third
            self._make_entry('note.md', '2024-01-01T00:00:00Z'),  # first
            self._make_entry('note.md', '2024-01-02T00:00:00Z'),  # second
        ]
        
        # Sort by timestamp first (as the backfill script does)
        entries.sort(key=lambda x: x['timestamp'])
        
        result, _ = add_event_type(entries)
        
        # After sorting, first should be created, rest modified
        assert result[0]['labels']['event_type'] == 'created'
        assert result[0]['timestamp'] == '2024-01-01T00:00:00Z'
        assert result[1]['labels']['event_type'] == 'modified'
        assert result[2]['labels']['event_type'] == 'modified'


class TestBackfillMultipleRotatedFiles:
    """Tests for backfill across multiple rotated files."""

    def test_find_rotated_files_sorted_chronologically(self, tmp_path):
        """Backfill across multiple rotated files -- sorted oldest first."""
        # Create rotated files with different timestamps
        (tmp_path / 'obsidian_logs.json.20240101_120000').write_text('')
        (tmp_path / 'obsidian_logs.json.20240315_090000').write_text('')
        (tmp_path / 'obsidian_logs.json.20240210_180000').write_text('')
        (tmp_path / 'obsidian_logs.json.pre_backfill').write_text('')  # Should be excluded
        (tmp_path / 'obsidian_logs.json').write_text('')  # Main file, not rotated
        
        result = find_rotated_files(tmp_path)
        
        assert len(result) == 3
        assert result[0].name == 'obsidian_logs.json.20240101_120000'
        assert result[1].name == 'obsidian_logs.json.20240210_180000'
        assert result[2].name == 'obsidian_logs.json.20240315_090000'

    def test_find_rotated_files_excludes_pre_backfill(self, tmp_path):
        """Pre-backfill file should not be included in rotated files."""
        (tmp_path / 'obsidian_logs.json.20240101_120000').write_text('')
        (tmp_path / 'obsidian_logs.json.pre_backfill').write_text('')
        
        result = find_rotated_files(tmp_path)
        
        assert len(result) == 1
        assert 'pre_backfill' not in result[0].name

    def test_read_log_file_with_invalid_lines(self, tmp_path):
        """Invalid JSON lines should be skipped."""
        log_file = tmp_path / 'test.json'
        log_file.write_text(
            '{"timestamp": "2024-01-01T00:00:00Z", "labels": {}, "line": "{}"}\n'
            'invalid json line\n'
            '{"timestamp": "2024-01-02T00:00:00Z", "labels": {}, "line": "{}"}\n'
        )
        
        entries = read_log_file(log_file)
        
        assert len(entries) == 2


class TestValidation:
    """Tests for entry validation."""

    def test_valid_entries_pass(self):
        """Valid entries should pass validation."""
        entries = [{
            'timestamp': '2024-01-01T00:00:00Z',
            'labels': {'vault': 'test'},
            'line': '{"file_path": "note.md"}'
        }]
        
        assert validate_entries(entries) is True

    def test_missing_timestamp_fails(self):
        """Missing timestamp should fail validation."""
        entries = [{
            'labels': {'vault': 'test'},
            'line': '{}'
        }]
        
        assert validate_entries(entries) is False

    def test_missing_labels_fails(self):
        """Missing labels should fail validation."""
        entries = [{
            'timestamp': '2024-01-01T00:00:00Z',
            'line': '{}'
        }]
        
        assert validate_entries(entries) is False

    def test_missing_line_fails(self):
        """Missing line should fail validation."""
        entries = [{
            'timestamp': '2024-01-01T00:00:00Z',
            'labels': {}
        }]
        
        assert validate_entries(entries) is False

    def test_invalid_line_json_fails(self):
        """Invalid JSON in line should fail validation."""
        entries = [{
            'timestamp': '2024-01-01T00:00:00Z',
            'labels': {},
            'line': 'not json'
        }]
        
        assert validate_entries(entries) is False


class TestExtractFilePath:
    """Tests for file_path extraction."""

    def test_extracts_file_path(self):
        """Should extract file_path from line JSON."""
        entry = {
            'line': json.dumps({'file_path': 'subfolder/note.md', 'word_count': 100})
        }
        
        assert extract_file_path(entry) == 'subfolder/note.md'

    def test_missing_line_returns_empty(self):
        """Missing line should return empty string."""
        entry = {}
        
        assert extract_file_path(entry) == ''

    def test_invalid_json_returns_empty(self):
        """Invalid JSON in line should return empty string."""
        entry = {'line': 'not json'}
        
        assert extract_file_path(entry) == ''

    def test_missing_file_path_returns_empty(self):
        """Missing file_path in line should return empty string."""
        entry = {'line': '{"word_count": 100}'}
        
        assert extract_file_path(entry) == ''
