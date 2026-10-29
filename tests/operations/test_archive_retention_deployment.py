"""Each archive VM's retention worker: its own site, its own pair, no gateway secret (§16.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SITES = {
    "deploy/archive-storage/docker-compose.yml": "primary",
    "deploy/archive-storage/docker-compose.replica.yml": "replica",
}


def _retention(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text())["services"]["retention"]


@pytest.mark.parametrize(("path", "site"), sorted(SITES.items()))
def test_each_site_runs_its_worker_only_under_the_retention_profile(path, site):
    service = _retention(path)
    assert service["profiles"] == ["retention"]
    assert service["environment"]["SSF_RETENTION_SITE"] == site
    assert service["command"] == [
        "python",
        "-m",
        "services.api_gateway.recording.retention",
        "run",
    ]


@pytest.mark.parametrize("path", sorted(SITES))
def test_the_worker_publishes_nothing_and_writes_only_its_state(path):
    service = _retention(path)
    assert "ports" not in service and "expose" not in service
    assert service["read_only"] is True
    assert service["tmpfs"] == ["/tmp"]
    writable = [volume for volume in service["volumes"] if not volume.endswith(":ro")]
    assert writable == ["retention-state:/var/lib/ssf-retention"]
    assert "retention-state" in yaml.safe_load((ROOT / path).read_text())["volumes"]


@pytest.mark.parametrize("path", sorted(SITES))
def test_the_worker_holds_its_own_secrets_and_never_the_gateways(path):
    service = _retention(path)
    secrets = [volume for volume in service["volumes"] if "/run/secrets/" in volume]
    assert secrets == ["/etc/ssf-archive/retention:/run/secrets/ssf-retention:ro"]
    assert "ssf-recording" not in (ROOT / path).read_text()
    for value in service["environment"].values():
        assert ":?" not in str(value)  # optional: the default stack starts without it


def test_the_image_prepares_the_state_volume_for_the_app_user():
    dockerfile = (ROOT / "services/api_gateway/Dockerfile").read_text()
    assert "mkdir -p /data/archive-spool /var/lib/ssf-retention" in dockerfile
    assert "chown -R app:app /data /var/lib/ssf-retention" in dockerfile
