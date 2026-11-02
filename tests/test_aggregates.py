"""Tests for the low-series aggregate metrics and the Grafana Cloud allowlist."""

import re
from pathlib import Path

import pytest
from prometheus_client import REGISTRY, generate_latest

from obsidian_grafana import parse_notes
from obsidian_grafana.parse_notes import parse_obsidian_vault_metrics_only, reset_metrics

ROOT = Path(__file__).resolve().parent.parent
PER_NOTE_FAMILIES = ("obsidian_note_total", "obsidian_word_count_total", "obsidian_note_wikilinks", "obsidian_tags_total")


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels)


@pytest.fixture(autouse=True)
def clean_metrics():
    reset_metrics()
    yield
    reset_metrics()


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "v"
    (v / "projects").mkdir(parents=True)
    (v / "journal" / "2026").mkdir(parents=True)
    (v / ".obsidian").mkdir()
    (v / "hub.md").write_text("one two three\n")  # root, 0 links
    (v / "projects" / "a.md").write_text("---\ntags: [x, y]\n---\nalpha [[hub]] [[b]] [[hub|Hub alias]]\n")
    (v / "projects" / "b.md").write_text("beta " * 60 + "[[hub]] [[projects/a#Heading]] [[ghost]]\n")
    (v / "journal" / "2026" / "d.md").write_text("day #x [[hub.md]] [[A]]\n")
    (v / ".obsidian" / "hidden.md").write_text("[[hub]]\n")
    return v


def scan(vault, **kw):
    parse_obsidian_vault_metrics_only(str(vault), None, **kw)


class TestFolderAggregates:
    def test_per_top_level_folder_totals(self, vault):
        scan(vault)
        assert sample("obsidian_folder_notes", vault="v", folder="projects") == 2
        assert sample("obsidian_folder_notes", vault="v", folder="journal") == 1
        assert sample("obsidian_folder_notes", vault="v", folder="(root)") == 1
        assert sample("obsidian_folder_wikilinks", vault="v", folder="projects") == 6
        assert sample("obsidian_folder_tags", vault="v", folder="projects") >= 2
        assert sample("obsidian_folder_words", vault="v", folder="(root)") == 3
        # folder totals add up to the vault totals
        total = sum(sample("obsidian_folder_notes", vault="v", folder=f) for f in ("projects", "journal", "(root)"))
        assert total == sample("obsidian_notes_count", vault="v") == 4

    def test_folders_beyond_cap_are_folded_into_other(self, tmp_path):
        v = tmp_path / "many"
        for i in range(8):
            (v / f"f{i}").mkdir(parents=True)
            for j in range(i + 1):  # f7 is largest, f0 smallest
                (v / f"f{i}" / f"n{j}.md").write_text("word\n")
        scan(v, max_folders=3)
        folders = {
            s.labels["folder"] for m in REGISTRY.collect() if m.name == "obsidian_folder_notes" for s in m.samples
        }
        assert folders == {"f7", "f6", "f5", "(other)"}
        assert sample("obsidian_folder_notes", vault="many", folder="(other)") == 1 + 2 + 3 + 4 + 5


class TestHistograms:
    def test_note_length_histogram(self, vault):
        scan(vault)
        assert sample("obsidian_note_length_words_count", vault="v") == 4
        assert sample("obsidian_note_length_words_bucket", vault="v", le="10.0") == 3  # all but the 60+ word note
        assert sample("obsidian_note_length_words_bucket", vault="v", le="100.0") == 4
        assert sample("obsidian_note_length_words_bucket", vault="v", le="+Inf") == 4

    def test_outgoing_links_histogram_gives_orphans(self, vault):
        scan(vault)
        assert sample("obsidian_note_outlinks_bucket", vault="v", le="0.0") == 1  # only hub.md has no links
        assert sample("obsidian_note_outlinks_bucket", vault="v", le="2.0") == 2
        assert sample("obsidian_note_outlinks_bucket", vault="v", le="+Inf") == 4


class TestTopLinked:
    def test_backlinks_count_distinct_existing_notes(self, vault):
        scan(vault)
        # hub: linked by a (twice, counted once), b, d. Hidden notes are not scanned. ghost does not exist.
        assert sample("obsidian_top_linked_note_backlinks", vault="v", note_name="hub") == 3
        assert sample("obsidian_top_linked_note_backlinks", vault="v", note_name="a") == 2  # b via path+heading, d via case
        assert sample("obsidian_top_linked_note_backlinks", vault="v", note_name="b") == 1
        assert sample("obsidian_top_linked_note_backlinks", vault="v", note_name="ghost") is None

    def test_top_n_limit_and_disable(self, vault):
        scan(vault, top_linked_notes=1)
        assert sample("obsidian_top_linked_note_backlinks", vault="v", note_name="hub") == 3
        assert sample("obsidian_top_linked_note_backlinks", vault="v", note_name="a") is None
        scan(vault, top_linked_notes=0)
        assert sample("obsidian_top_linked_note_backlinks", vault="v", note_name="hub") is None


class TestNoPerNoteSeries:
    def test_old_families_and_labels_are_gone(self, vault):
        scan(vault)
        text = generate_latest(REGISTRY).decode()
        for family in PER_NOTE_FAMILIES:
            assert family not in text
        obsidian = [line for line in text.splitlines() if line.startswith("obsidian_")]
        assert obsidian and not any("file_path=" in line for line in obsidian)

    def test_series_count_is_independent_of_note_count(self, tmp_path):
        def series(n):
            v = tmp_path / f"s{n}"
            (v / "d").mkdir(parents=True)
            for i in range(n):
                (v / "d" / f"n{i}.md").write_text(f"w{i} [[n0]] text\n")
            reset_metrics()
            scan(v, top_linked_notes=5)
            return sum(len(m.samples) for m in REGISTRY.collect() if m.name.startswith("obsidian_"))

        # word frequency adds one series per distinct word (capped at 100), everything else is fixed
        assert series(300) <= series(30) + 100


def _allowlist_regex():
    text = (ROOT / "alloy" / "cloud.alloy").read_text()
    block = re.search(r'prometheus\.relabel "allowlist" \{.*?\n\}\n', text, re.S).group(0)
    return re.compile(re.search(r'regex\s*=\s*"([^"]+)"', block).group(1))


class TestCloudAllowlist:
    def test_allowlist_keeps_only_low_series_families(self, vault):
        scan(vault)
        allow = _allowlist_regex()
        # an old-style exporter (still running in someone's stack) must not leak per-note series
        legacy = list(PER_NOTE_FAMILIES) + [f + "_created" for f in PER_NOTE_FAMILIES]
        assert not any(allow.fullmatch(name) for name in legacy)
        names = {s.name for m in REGISTRY.collect() if m.name.startswith("obsidian_") for s in m.samples}
        kept = {n for n in names if allow.fullmatch(n)}
        assert {"obsidian_notes_count", "obsidian_words_total", "obsidian_tags_count", "obsidian_wikilinks_total",
                "obsidian_word_frequency", "obsidian_folder_notes", "obsidian_note_length_words_bucket",
                "obsidian_top_linked_note_backlinks", "obsidian_note_outlinks_bucket"} <= kept
        assert allow.fullmatch("up")
        assert not any(n.endswith("_created") for n in kept)

    def test_file_path_guard_rule_present(self):
        text = (ROOT / "alloy" / "cloud.alloy").read_text()
        block = re.search(r'prometheus\.relabel "allowlist" \{.*?\n\}\n', text, re.S).group(0)
        assert re.search(r'source_labels = \["file_path"\]\s+regex\s+= ".\+"\s+action\s+= "drop"', block)

    def test_scrape_goes_through_allowlist(self):
        text = (ROOT / "alloy" / "cloud.alloy").read_text()
        scrape = re.search(r'prometheus\.scrape "obsidian_metrics" \{.*?\n\}\n', text, re.S).group(0)
        assert "prometheus.relabel.allowlist.receiver" in scrape
        assert "prometheus.remote_write.cloud.receiver" not in scrape
