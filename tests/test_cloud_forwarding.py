"""Tests for the optional Grafana Cloud forwarding (alloy/cloud.alloy, compose profile, dashboard import)."""

import json
import os
import shutil
import subprocess
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


class TestAlloyCloudConfig:
    def setup_method(self):
        raw = (ROOT / "alloy" / "cloud.alloy").read_text()
        # comments may mention what is excluded; only the actual config matters
        self.text = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("//"))

    def test_does_not_forward_the_parser_error_log(self):
        # obsidian_parser.log (job=obsidian-cron) can contain absolute vault paths: stays local
        assert "obsidian_parser.log" not in self.text
        assert "obsidian-cron" not in self.text
        assert "/logs/obsidian_logs.json" in self.text

    def test_credentials_come_from_environment(self):
        for var in CLOUD_ENV:
            assert f'sys.env("{var}")' in self.text
        assert "glc_" not in self.text

    def test_local_pipeline_is_unchanged(self):
        local = (ROOT / "alloy" / "config.alloy").read_text()
        assert "grafana.net" not in local and "sys.env" not in local


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
