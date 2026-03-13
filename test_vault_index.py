"""Tests for export_vault_index.py"""

import tempfile
from pathlib import Path

import pytest

from export_vault_index import (
    scan_note,
    scan_vault,
    compute_backlinks,
    format_note_block,
    generate_summary,
    generate_full_index,
)


SAMPLE_NOTE = """\
---
tags:
  - philosophy
  - writing
aliases:
  - Stoicism Notes
status: draft
type: concept
category: ideas
---

# Stoicism

## Core Principles

The Stoics believed in virtue as the highest good.

See also [[Marcus Aurelius]] and [[Epictetus]].

Related: [[Virtue Ethics|virtue ethics overview]]

## Modern Applications

Some modern takes on this: [Ryan Holiday](https://example.com/holiday)
and [Massimo Pigliucci](https://example.com/pigliucci).

Inline tag: #ancient-philosophy

Link with heading: [[Seneca#Letters]]
Link with path: [[People/Zeno of Citium]]
"""

SIMPLE_NOTE = """\
Just a plain note with no frontmatter.

Links to [[Stoicism]] and [[Plato]].
"""

EMPTY_NOTE = """\
---
tags: []
---
"""


@pytest.fixture
def vault_dir():
    """Create a temporary vault with sample notes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = Path(tmpdir)

        (vault / "Stoicism.md").write_text(SAMPLE_NOTE)
        (vault / "Plain Note.md").write_text(SIMPLE_NOTE)
        (vault / "Empty.md").write_text(EMPTY_NOTE)

        subfolder = vault / "People"
        subfolder.mkdir()
        (subfolder / "Marcus Aurelius.md").write_text(
            "# Marcus Aurelius\n\nRoman emperor and Stoic. See [[Stoicism]].\n"
        )

        hidden = vault / ".obsidian"
        hidden.mkdir()
        (hidden / "config.md").write_text("internal config")

        yield vault


class TestScanNote:
    def test_extracts_frontmatter_tags(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert "philosophy" in note["tags"]
        assert "writing" in note["tags"]

    def test_extracts_inline_tags(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert "ancient-philosophy" in note["tags"]

    def test_merges_and_deduplicates_tags(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert len(note["tags"]) == len(set(note["tags"]))

    def test_extracts_aliases(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert note["aliases"] == ["Stoicism Notes"]

    def test_extracts_frontmatter_fields(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert note["frontmatter"]["status"] == "draft"
        assert note["frontmatter"]["type"] == "concept"
        assert note["frontmatter"]["category"] == "ideas"

    def test_extracts_headings(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert "Stoicism" in note["headings"]
        assert "Core Principles" in note["headings"]
        assert "Modern Applications" in note["headings"]

    def test_no_h4_plus_headings(self, vault_dir):
        (vault_dir / "Deep.md").write_text(
            "# H1\n## H2\n### H3\n#### H4\n##### H5\n"
        )
        note = scan_note(vault_dir / "Deep.md", vault_dir)
        assert len(note["headings"]) == 3

    def test_extracts_wikilinks(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert "Marcus Aurelius" in note["wikilinks"]
        assert "Epictetus" in note["wikilinks"]

    def test_normalizes_wikilink_aliases(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert "Virtue Ethics" in note["wikilinks"]
        assert "virtue ethics overview" not in note["wikilinks"]

    def test_normalizes_wikilink_headings(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert "Seneca" in note["wikilinks"]

    def test_normalizes_wikilink_paths(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert "Zeno of Citium" in note["wikilinks"]

    def test_counts_external_urls(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert note["external_url_count"] == 2

    def test_word_count(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert note["word_count"] > 0

    def test_relative_path(self, vault_dir):
        note = scan_note(vault_dir / "People" / "Marcus Aurelius.md", vault_dir)
        assert note["path"] == str(Path("People") / "Marcus Aurelius.md")

    def test_note_without_frontmatter(self, vault_dir):
        note = scan_note(vault_dir / "Plain Note.md", vault_dir)
        assert note is not None
        assert "Stoicism" in note["wikilinks"]
        assert "Plato" in note["wikilinks"]
        assert note["tags"] == []

    def test_empty_note(self, vault_dir):
        note = scan_note(vault_dir / "Empty.md", vault_dir)
        assert note is not None
        assert note["word_count"] == 0

    def test_timestamps_present(self, vault_dir):
        note = scan_note(vault_dir / "Stoicism.md", vault_dir)
        assert note["created_at"]
        assert note["modified_at"]


class TestScanVault:
    def test_finds_all_notes(self, vault_dir):
        notes = scan_vault(vault_dir)
        names = {n["note_name"] for n in notes}
        assert "Stoicism" in names
        assert "Plain Note" in names
        assert "Empty" in names
        assert "Marcus Aurelius" in names

    def test_skips_hidden_directories(self, vault_dir):
        notes = scan_vault(vault_dir)
        names = {n["note_name"] for n in notes}
        assert "config" not in names

    def test_includes_subfolder_notes(self, vault_dir):
        notes = scan_vault(vault_dir)
        names = {n["note_name"] for n in notes}
        assert "Marcus Aurelius" in names


class TestComputeBacklinks:
    def test_basic_backlinks(self):
        notes = [
            {"note_name": "A", "wikilinks": ["B", "C"]},
            {"note_name": "B", "wikilinks": ["A"]},
            {"note_name": "C", "wikilinks": ["A", "B"]},
        ]
        bl = compute_backlinks(notes)
        assert set(bl["A"]) == {"B", "C"}
        assert set(bl["B"]) == {"A", "C"}
        assert bl["C"] == ["A"]

    def test_deduplicates_per_source(self):
        """A note linking to the same target twice should count as one backlink."""
        notes = [
            {"note_name": "A", "wikilinks": ["B", "B", "B"]},
        ]
        bl = compute_backlinks(notes)
        assert bl["B"] == ["A"]

    def test_no_backlinks(self):
        notes = [
            {"note_name": "A", "wikilinks": []},
            {"note_name": "B", "wikilinks": []},
        ]
        bl = compute_backlinks(notes)
        assert bl == {}

    def test_phantom_targets(self):
        """Links to notes that don't exist in the vault still appear as targets."""
        notes = [
            {"note_name": "A", "wikilinks": ["NonExistent"]},
        ]
        bl = compute_backlinks(notes)
        assert bl["NonExistent"] == ["A"]

    def test_with_vault_data(self, vault_dir):
        notes = scan_vault(vault_dir)
        bl = compute_backlinks(notes)
        stoicism_bl = bl.get("Stoicism", [])
        assert "Plain Note" in stoicism_bl
        assert "Marcus Aurelius" in stoicism_bl


class TestFormatNoteBlock:
    def test_contains_note_name(self):
        note = {
            "note_name": "Test",
            "path": "Test.md",
            "word_count": 100,
            "tags": ["tag1"],
            "frontmatter": {"status": "draft"},
            "modified_at": "2024-01-15T10:00:00",
            "created_at": "2023-06-01T10:00:00",
            "external_url_count": 1,
            "wikilinks": ["Other"],
            "headings": ["Heading One"],
            "aliases": ["alias1"],
        }
        block = format_note_block(note, {"Test": ["Linker"]})
        assert "### Test" in block
        assert "**Words**: 100" in block
        assert "**Backlinks**: 1" in block
        assert "**Status**: draft" in block
        assert "#tag1" in block
        assert "[[Other]]" in block
        assert "[[Linker]]" in block
        assert "Heading One" in block
        assert "alias1" in block

    def test_truncates_long_link_lists(self):
        note = {
            "note_name": "Hub",
            "path": "Hub.md",
            "word_count": 50,
            "tags": [],
            "frontmatter": {},
            "modified_at": "2024-01-01T00:00:00",
            "created_at": "2024-01-01T00:00:00",
            "external_url_count": 0,
            "wikilinks": [f"Note{i}" for i in range(30)],
            "headings": [],
            "aliases": [],
        }
        block = format_note_block(note, {})
        assert "... (30 total)" in block

    def test_no_links_line_when_empty(self):
        note = {
            "note_name": "Lonely",
            "path": "Lonely.md",
            "word_count": 10,
            "tags": [],
            "frontmatter": {},
            "modified_at": "2024-01-01T00:00:00",
            "created_at": "2024-01-01T00:00:00",
            "external_url_count": 0,
            "wikilinks": [],
            "headings": [],
            "aliases": [],
        }
        block = format_note_block(note, {})
        assert "Links to" not in block
        assert "Linked by" not in block


class TestGenerateFiles:
    def _make_notes(self):
        """Build a small set of notes for testing file generation."""
        notes = []
        for i in range(5):
            links = [f"Note{j}" for j in range(5) if j != i]
            notes.append(
                {
                    "note_name": f"Note{i}",
                    "path": f"Note{i}.md",
                    "word_count": (i + 1) * 100,
                    "line_count": (i + 1) * 10,
                    "file_size": (i + 1) * 500,
                    "created_at": f"2024-0{i+1}-01T00:00:00",
                    "modified_at": f"2024-0{i+1}-15T00:00:00",
                    "headings": [f"Section {i}"],
                    "external_url_count": i,
                    "wikilinks": links,
                    "tags": [f"tag{i}", "shared"],
                    "aliases": [f"n{i}"] if i % 2 == 0 else [],
                    "frontmatter": {"status": "draft" if i < 3 else "published", "type": "concept"},
                }
            )
        return notes

    def test_summary_file_created(self, tmp_path):
        notes = self._make_notes()
        bl = compute_backlinks(notes)
        out = tmp_path / "vault_index_summary.md"
        generate_summary(notes, bl, "test-vault", out)
        content = out.read_text()
        assert "# Vault Index Summary" in content
        assert "test-vault" in content
        assert "Most Backlinked" in content
        assert "Recently Modified" in content
        assert "Vault Breakdown" in content

    def test_full_index_file_created(self, tmp_path):
        notes = self._make_notes()
        bl = compute_backlinks(notes)
        out = tmp_path / "vault_index_full.md"
        generate_full_index(notes, bl, "test-vault", out)
        content = out.read_text()
        assert "# Vault Index (Full)" in content
        for i in range(5):
            assert f"### Note{i}" in content

    def test_full_index_sorted_by_backlinks(self, tmp_path):
        notes = self._make_notes()
        bl = compute_backlinks(notes)
        out = tmp_path / "vault_index_full.md"
        generate_full_index(notes, bl, "test-vault", out)
        content = out.read_text()
        positions = []
        for i in range(5):
            pos = content.index(f"### Note{i}")
            positions.append((i, pos))
        bl_counts = [len(bl.get(f"Note{i}", [])) for i in range(5)]
        sorted_by_bl = sorted(range(5), key=lambda i: bl_counts[i], reverse=True)
        sorted_by_pos = [i for i, _ in sorted(positions, key=lambda x: x[1])]
        assert sorted_by_pos == sorted_by_bl

    def test_summary_vault_breakdown(self, tmp_path):
        notes = self._make_notes()
        bl = compute_backlinks(notes)
        out = tmp_path / "vault_index_summary.md"
        generate_summary(notes, bl, "test-vault", out)
        content = out.read_text()
        assert "draft" in content
        assert "published" in content
        assert "concept" in content
        assert "#shared" in content

    def test_underdeveloped_section(self, tmp_path):
        notes = [
            {
                "note_name": "Stub",
                "path": "Stub.md",
                "word_count": 10,
                "line_count": 3,
                "file_size": 50,
                "created_at": "2024-01-01T00:00:00",
                "modified_at": "2024-01-01T00:00:00",
                "headings": [],
                "external_url_count": 0,
                "wikilinks": [],
                "tags": [],
                "aliases": [],
                "frontmatter": {},
            },
        ]
        for i in range(5):
            notes.append(
                {
                    "note_name": f"Linker{i}",
                    "path": f"Linker{i}.md",
                    "word_count": 500,
                    "line_count": 50,
                    "file_size": 2000,
                    "created_at": "2024-01-01T00:00:00",
                    "modified_at": "2024-01-01T00:00:00",
                    "headings": [],
                    "external_url_count": 0,
                    "wikilinks": ["Stub"],
                    "tags": [],
                    "aliases": [],
                    "frontmatter": {},
                }
            )
        bl = compute_backlinks(notes)
        out = tmp_path / "vault_index_summary.md"
        generate_summary(notes, bl, "test-vault", out)
        content = out.read_text()
        assert "Linked But Underdeveloped" in content
        assert "### Stub" in content
