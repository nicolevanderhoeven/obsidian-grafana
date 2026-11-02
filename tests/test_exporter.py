"""Tests for the metrics exporter refresh loop and CLI/config resolution."""

import threading

import pytest
from prometheus_client import REGISTRY

from obsidian_grafana import parse_notes
from obsidian_grafana.parse_notes import (
    build_arg_parser,
    parse_obsidian_vault_metrics_only,
    reset_metrics,
    run_metrics_exporter,
)


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels)


@pytest.fixture(autouse=True)
def clean_metrics():
    reset_metrics()
    yield
    reset_metrics()


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "myvault"
    v.mkdir()
    (v / "alpha.md").write_text("---\ntags: [one, two]\n---\nplanet orbit planet [[beta]]\n")
    (v / "beta.md").write_text("galaxy cluster\n")
    return v


class TestRescan:
    def test_initial_scan_populates_metrics(self, vault):
        parse_obsidian_vault_metrics_only(str(vault))
        assert sample("obsidian_notes_count", vault="myvault") == 2
        assert sample("obsidian_wikilinks_total", vault="myvault") == 1
        assert sample("obsidian_word_frequency", vault="myvault", word="planet") == 2

    def test_rescan_picks_up_added_changed_and_removed_notes(self, vault):
        parse_obsidian_vault_metrics_only(str(vault))

        (vault / "gamma.md").write_text("nebula nebula nebula\n")
        (vault / "beta.md").unlink()
        (vault / "alpha.md").write_text("planet only\n")
        parse_obsidian_vault_metrics_only(str(vault))

        assert sample("obsidian_notes_count", vault="myvault") == 2
        assert sample("obsidian_wikilinks_total", vault="myvault") == 0
        assert sample("obsidian_word_frequency", vault="myvault", word="nebula") == 3
        assert sample("obsidian_word_frequency", vault="myvault", word="planet") == 1
        # Words and notes that no longer exist must disappear, not linger as stale series
        assert sample("obsidian_word_frequency", vault="myvault", word="galaxy") is None
        assert sample("obsidian_note_wikilinks", vault="myvault", note_name="beta", file_path="beta.md") is None

    def test_rescan_does_not_accumulate(self, vault):
        for _ in range(3):
            parse_obsidian_vault_metrics_only(str(vault))
        assert sample("obsidian_notes_count", vault="myvault") == 2
        assert sample("obsidian_note_total", vault="myvault", note_name="alpha", file_path="alpha.md") == 1
        words_once = sample("obsidian_words_total", vault="myvault")
        parse_obsidian_vault_metrics_only(str(vault))
        assert sample("obsidian_words_total", vault="myvault") == words_once

    def test_missing_vault_raises(self, tmp_path):
        with pytest.raises(ValueError):
            parse_obsidian_vault_metrics_only(str(tmp_path / "nope"))


class TestExporterLoop:
    def test_loop_rescans_on_interval(self, vault, monkeypatch):
        stop = threading.Event()
        calls = []
        real = parse_notes.parse_obsidian_vault_metrics_only

        def counting(path, exclude=None):
            calls.append(path)
            real(path, exclude)
            if len(calls) == 3:
                stop.set()

        monkeypatch.setattr(parse_notes, "parse_obsidian_vault_metrics_only", counting)
        run_metrics_exporter(str(vault), set(), refresh_interval=0.01, stop_event=stop)
        assert len(calls) == 3

    def test_loop_sees_new_notes(self, vault):
        stop = threading.Event()
        t = threading.Thread(target=run_metrics_exporter, args=(str(vault), set(), 0.05, stop))
        t.start()
        try:
            (vault / "late.md").write_text("late arrival\n")
            for _ in range(100):
                if sample("obsidian_notes_count", vault="myvault") == 3:
                    break
                stop.wait(0.05)
            assert sample("obsidian_notes_count", vault="myvault") == 3
        finally:
            stop.set()
            t.join(5)

    def test_failed_refresh_keeps_previous_values(self, vault, monkeypatch):
        stop = threading.Event()
        real = parse_notes.parse_obsidian_vault_metrics_only
        n = {"calls": 0}

        def flaky(path, exclude=None):
            n["calls"] += 1
            if n["calls"] == 1:
                return real(path, exclude)
            if n["calls"] >= 3:
                stop.set()
            raise ValueError("vault unavailable")

        monkeypatch.setattr(parse_notes, "parse_obsidian_vault_metrics_only", flaky)
        run_metrics_exporter(str(vault), set(), refresh_interval=0.01, stop_event=stop)
        assert sample("obsidian_notes_count", vault="myvault") == 2

    def test_rejects_non_positive_interval(self, vault):
        with pytest.raises(ValueError):
            run_metrics_exporter(str(vault), set(), refresh_interval=0)


class TestCliConfigResolution:
    def write_config(self, tmp_path, vault, **extra):
        lines = [f'vault_path: "{vault}"']
        lines += [f"{k}: {v}" for k, v in extra.items()]
        cfg = tmp_path / "config.yaml"
        cfg.write_text("\n".join(lines) + "\n")
        return cfg

    def test_cli_defaults_are_unset_so_config_can_win(self):
        args = build_arg_parser().parse_args([])
        assert args.log_level is None
        assert args.metrics_port is None
        assert args.output is None

    def test_config_log_level_is_used(self, tmp_path, vault, monkeypatch):
        cfg = self.write_config(tmp_path, vault, log_level="DEBUG", output_file=str(tmp_path / "out.json"))
        seen = {}
        monkeypatch.setattr(parse_notes, "setup_logging", lambda level: seen.setdefault("level", level))
        monkeypatch.setattr(parse_notes, "parse_obsidian_vault", lambda *a: seen.setdefault("args", a))
        parse_notes.main(["--config", str(cfg)])
        assert seen["level"] == "DEBUG"
        assert seen["args"][1] == str(tmp_path / "out.json")

    def test_cli_overrides_config(self, tmp_path, vault, monkeypatch):
        cfg = self.write_config(tmp_path, vault, log_level="DEBUG")
        seen = {}
        monkeypatch.setattr(parse_notes, "setup_logging", lambda level: seen.setdefault("level", level))
        monkeypatch.setattr(parse_notes, "parse_obsidian_vault", lambda *a: None)
        parse_notes.main(["--config", str(cfg), "--log-level", "ERROR"])
        assert seen["level"] == "ERROR"

    def test_default_output_is_logs_dir_not_tmp(self, tmp_path, vault, monkeypatch):
        cfg = self.write_config(tmp_path, vault)
        seen = {}
        monkeypatch.setattr(parse_notes, "setup_logging", lambda level: None)
        monkeypatch.setattr(parse_notes, "parse_obsidian_vault", lambda *a: seen.setdefault("args", a))
        parse_notes.main(["--config", str(cfg)])
        assert seen["args"][1] == "./logs/obsidian_logs.json"

    def test_config_metrics_port_and_interval(self, tmp_path, vault, monkeypatch):
        cfg = self.write_config(tmp_path, vault, metrics_port=9999, metrics_refresh_interval=42, start_metrics_server="true")
        seen = {}
        monkeypatch.setattr(parse_notes, "setup_logging", lambda level: None)
        monkeypatch.setattr(parse_notes, "start_metrics_server", lambda port: seen.setdefault("port", port))
        monkeypatch.setattr(parse_notes, "run_metrics_exporter", lambda v, e, i: seen.setdefault("interval", i))
        parse_notes.main(["--config", str(cfg)])
        assert seen == {"port": 9999, "interval": 42.0}
