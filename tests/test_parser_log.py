"""Tests for the parser log: size rotation in scripts/cron-parse.sh and the Alloy non-JSON filter."""

import gzip
import json
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ALLOY_IMAGE = "grafana/alloy:v1.21.3"
WARNING = "DeprecationWarning: something is deprecated"
HEARTBEAT = '{"timestamp": "2026-01-01T00:00:00.000Z", "level": "info", "message": "Cron job executed successfully", "source": "cron"}'


def make_install(tmp_path, python_body):
    """A throwaway copy of the install layout with a stub virtualenv python."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "cron-parse.sh", tmp_path / "scripts" / "cron-parse.sh")
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text(f"#!/usr/bin/env bash\n{python_body}\n")
    py.chmod(0o755)
    return tmp_path


def run_cron(install, **env):
    return subprocess.run(
        ["bash", str(install / "scripts" / "cron-parse.sh")],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", **env},
    )


class TestRotation:
    def test_small_log_is_appended_not_rotated(self, tmp_path):
        install = make_install(tmp_path, f"echo '{WARNING}' >&2")
        for _ in range(3):
            assert run_cron(install).returncode == 0
        logs = install / "logs"
        assert sorted(p.name for p in logs.iterdir()) == ["obsidian_parser.log"]
        lines = (logs / "obsidian_parser.log").read_text().splitlines()
        assert sum(1 for line in lines if line == WARNING) == 3
        heartbeats = [json.loads(line) for line in lines if line.startswith("{")]
        assert len(heartbeats) == 3 and heartbeats[0]["message"] == "Cron job executed successfully"

    def test_oversized_log_rotates_to_compressed_generations_and_is_bounded(self, tmp_path):
        install = make_install(tmp_path, f"echo '{WARNING}' >&2")
        env = {"OBSIDIAN_PARSER_LOG_MAX_BYTES": "500", "OBSIDIAN_PARSER_LOG_KEEP": "2"}
        for i in range(40):
            assert run_cron(install, **env).returncode == 0
        logs = install / "logs"
        names = sorted(p.name for p in logs.iterdir())
        assert names == ["obsidian_parser.log", "obsidian_parser.log.1.gz", "obsidian_parser.log.2.gz"]
        assert (logs / "obsidian_parser.log").stat().st_size <= 500 + 400  # one run past the limit at most
        newest = gzip.decompress((logs / "obsidian_parser.log.1.gz").read_bytes()).decode()
        assert WARNING in newest

    def test_rotation_never_loses_the_existing_content(self, tmp_path):
        install = make_install(tmp_path, "true")
        logs = install / "logs"
        logs.mkdir()
        (logs / "obsidian_parser.log").write_text("old line\n" * 100)
        assert run_cron(install, OBSIDIAN_PARSER_LOG_MAX_BYTES="100").returncode == 0
        assert gzip.decompress((logs / "obsidian_parser.log.1.gz").read_bytes()).decode() == "old line\n" * 100
        fresh = (logs / "obsidian_parser.log").read_text()
        assert "old line" not in fresh and "Cron job executed successfully" in fresh

    def test_failed_parser_still_writes_no_heartbeat(self, tmp_path):
        install = make_install(tmp_path, "exit 1")
        run_cron(install)
        assert "Cron job executed" not in (install / "logs" / "obsidian_parser.log").read_text()


def docker_available():
    return shutil.which("docker") is not None and subprocess.run(
        ["docker", "info"], capture_output=True
    ).returncode == 0


needs_docker = pytest.mark.skipif(not docker_available(), reason="docker not available")


def snappy_decode(data):
    """Minimal snappy block decoder (Loki push bodies are snappy-compressed protobuf)."""
    pos, shift, length = 0, 0, 0
    while True:
        b = data[pos]
        pos += 1
        length |= (b & 0x7F) << shift
        if not b & 0x80:
            break
        shift += 7
    out = bytearray()
    while pos < len(data):
        tag = data[pos]
        pos += 1
        kind = tag & 3
        if kind == 0:
            n = tag >> 2
            if n >= 60:
                extra = n - 59
                n = int.from_bytes(data[pos:pos + extra], "little")
                pos += extra
            n += 1
            out += data[pos:pos + n]
            pos += n
            continue
        if kind == 1:
            n = ((tag >> 2) & 7) + 4
            offset = ((tag >> 5) << 8) | data[pos]
            pos += 1
        elif kind == 2:
            n = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 2], "little")
            pos += 2
        else:
            n = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        for _ in range(n):
            out.append(out[-offset])
    assert len(out) == length
    return bytes(out)


class _Sink(BaseHTTPRequestHandler):
    bodies = []

    def do_POST(self):
        self.bodies.append(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


@needs_docker
class TestAlloyFilter:
    def test_config_is_valid(self):
        result = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{ROOT / 'alloy' / 'config.alloy'}:/c.alloy:ro",
             ALLOY_IMAGE, "validate", "/c.alloy"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_non_json_parser_log_lines_are_dropped_but_heartbeat_and_events_are_kept(self, tmp_path):
        event = {"timestamp": "2026-01-01T00:00:00.000Z", "labels": {"vault": "v", "job": "obsidian-parser"}, "line": "{}"}
        (tmp_path / "obsidian_parser.log").write_text(f"{WARNING}\n2026-01-01 00:00:00 - INFO - noise\n{HEARTBEAT}\n")
        (tmp_path / "obsidian_logs.json").write_text(json.dumps(event) + "\n")
        # Point loki.write at a local sink instead of the compose-network "loki" host
        config = (ROOT / "alloy" / "config.alloy").read_text()
        server = HTTPServer(("0.0.0.0", 0), _Sink)
        _Sink.bodies = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cfg = tmp_path / "c.alloy"
        cfg.write_text(config.replace("http://loki:3100", f"http://host.docker.internal:{server.server_port}"))
        started = subprocess.run(
            ["docker", "run", "-d", "--add-host", "host.docker.internal:host-gateway",
             "-v", f"{cfg}:/c.alloy:ro", "-v", f"{tmp_path}:/logs:ro",
             ALLOY_IMAGE, "run", "/c.alloy", "--storage.path=/tmp/alloy"],
            capture_output=True, text=True,
        )
        assert started.returncode == 0, started.stderr
        cid = started.stdout.strip()
        try:
            def payload():
                return b"".join(snappy_decode(b) for b in list(_Sink.bodies))

            deadline = time.time() + 40
            while time.time() < deadline and not (
                b"Cron job executed" in payload() and b"obsidian-parser" in payload()
            ):
                time.sleep(1)
            time.sleep(3)  # let any (wrongly kept) plain-text lines arrive too
            payload = payload()
            assert b"Cron job executed successfully" in payload
            assert b"obsidian-parser" in payload
            assert b"DeprecationWarning" not in payload and b"noise" not in payload
        finally:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
            server.shutdown()
