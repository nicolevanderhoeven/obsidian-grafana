"""Tests for the optional Grafana Cloud forwarding (alloy/cloud.alloy, compose profile, dashboard import)."""

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLOUD_ENV = {
    "GRAFANA_CLOUD_LOKI_URL": "https://logs.example/loki/api/v1/push",
    "GRAFANA_CLOUD_LOKI_USER": "1",
    "GRAFANA_CLOUD_PROMETHEUS_URL": "https://prom.example/api/prom/push",
    "GRAFANA_CLOUD_PROMETHEUS_USER": "2",
    "GRAFANA_CLOUD_TOKEN": "placeholder",
}


def compose(*args, **extra_env):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GRAFANA_CLOUD_")}
    env.update(VAULT_PATH="/tmp/vault", GRAFANA_PASSWORD="placeholder", **extra_env)
    return subprocess.run(
        ["docker", "compose", *args], cwd=ROOT, env=env, capture_output=True, text=True
    )


needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None or subprocess.run(
        ["docker", "compose", "version"], capture_output=True
    ).returncode != 0,
    reason="docker compose not available",
)


ALLOY_IMAGE = "grafana/alloy:v1.21.3"


def alloy(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


@needs_docker
class TestAlloyCloudConfig:
    def test_config_is_valid(self):
        result = alloy(
            "run", "--rm", "-v", f"{ROOT / 'alloy' / 'cloud.alloy'}:/c.alloy:ro",
            ALLOY_IMAGE, "validate", "/c.alloy",
        )
        assert result.returncode == 0, result.stderr

    def test_only_the_json_event_stream_is_tailed(self, tmp_path):
        # obsidian_parser.log can contain absolute vault paths: it must stay local
        (tmp_path / "obsidian_logs.json").write_text("{}\n")
        (tmp_path / "obsidian_parser.log").write_text("/secret/vault/path\n")
        env = []
        for k, v in CLOUD_ENV.items():
            env += ["-e", f"{k}={v}"]
        started = alloy(
            "run", "-d", "-p", "127.0.0.1::12345", *env,
            "-v", f"{ROOT / 'alloy' / 'cloud.alloy'}:/c.alloy:ro",
            "-v", f"{tmp_path}:/logs:ro",
            ALLOY_IMAGE, "run", "/c.alloy",
            "--server.http.listen-addr=0.0.0.0:12345", "--storage.path=/tmp/alloy",
        )
        assert started.returncode == 0, started.stderr
        cid = started.stdout.strip()
        try:
            port = alloy("port", cid, "12345/tcp").stdout.strip().rsplit(":", 1)[1]
            url = f"http://127.0.0.1:{port}/api/v0/web/components/loki.source.file.obsidian_events"
            paths = set()
            for _ in range(30):
                try:
                    component = json.load(urllib.request.urlopen(url, timeout=2))
                except (OSError, ValueError):
                    time.sleep(1)
                    continue
                paths = {
                    entry["value"]["value"]
                    for info in component.get("debugInfo", [])
                    for entry in info.get("body", [])
                    if entry["name"] == "path"
                }
                if paths:
                    break
                time.sleep(1)
            assert paths == {"/logs/obsidian_logs.json"}
        finally:
            alloy("rm", "-f", cid)


@needs_docker
class TestComposeProfile:
    def test_valid_without_cloud_vars_and_no_cloud_service(self):
        result = compose("config", "--services")
        assert result.returncode == 0, result.stderr
        assert "alloy-cloud" not in result.stdout.split()
        assert "alloy" in result.stdout.split()

    def test_valid_with_cloud_vars_and_service_enabled(self):
        result = compose("--profile", "cloud", "config", "--services", **CLOUD_ENV)
        assert result.returncode == 0, result.stderr
        assert "alloy-cloud" in result.stdout.split()

    def test_cloud_profile_does_not_touch_local_services(self):
        base = set(compose("config", "--services").stdout.split())
        cloud = set(compose("--profile", "cloud", "config", "--services", **CLOUD_ENV).stdout.split())
        assert cloud - base == {"alloy-cloud"}


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not available")
class TestDashboardImport:
    def test_dry_run_rewrites_datasource_uids_only_in_output(self, tmp_path):
        script = ROOT / "scripts" / "import-cloud-dashboards.sh"
        result = subprocess.run(
            ["bash", str(script), "--dry-run", str(tmp_path)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        outputs = sorted(tmp_path.glob("*.json"))
        assert len(outputs) == len(list((ROOT / "grafana" / "dashboards").glob("*.json")))
        for out in outputs:
            text = out.read_text()
            data = json.loads(text)
            assert data["uid"].startswith("obsidian-")  # dashboard uids are preserved
            assert '"uid": "loki"' not in text and '"uid": "prometheus"' not in text
        combined = "".join(p.read_text() for p in outputs)
        assert "grafanacloud-logs" in combined and "grafanacloud-prom" in combined
        # sources untouched
        for src in (ROOT / "grafana" / "dashboards").glob("*.json"):
            assert "grafanacloud-" not in src.read_text()
