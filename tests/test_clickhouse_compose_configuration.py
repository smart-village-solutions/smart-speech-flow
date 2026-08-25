"""Regression tests for the internal ClickHouse Compose security contract."""

import os
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def _clickhouse_service() -> dict:
    """Return the resolved ClickHouse service using isolated test credentials."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as env_file:
        env_file.write("CLICKHOUSE_DB=ssf_analytics_test\n")
        env_file.write("CLICKHOUSE_USER=ssf_telemetry_test\n")
        env_file.write("CLICKHOUSE_PASSWORD=test-only-password\n")

    try:
        result = subprocess.run(
            ["docker", "compose", "--env-file", env_file.name, "config"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(env_file.name)

    return yaml.safe_load(result.stdout)["services"]["clickhouse"]


def test_clickhouse_service_is_internal_and_persistent() -> None:
    """Fail if ClickHouse becomes public or loses durable storage."""
    service = _clickhouse_service()

    assert service["image"] == "clickhouse/clickhouse-server:26.3.17.110"
    assert service["restart"] == "always"
    assert service.get("ports") is None
    assert service["expose"] == ["8123"]
    assert {
        "type": "volume",
        "source": "clickhouse-data",
        "target": "/var/lib/clickhouse",
        "volume": {},
    } in service["volumes"]
    assert service.get("labels") is None


def test_clickhouse_service_receives_required_credentials() -> None:
    """Fail if resolved ClickHouse credentials are omitted from the service."""
    environment = _clickhouse_service()["environment"]

    assert environment["CLICKHOUSE_PASSWORD"] == "test-only-password"
    assert environment["CLICKHOUSE_USER"] == "ssf_telemetry_test"
    assert environment["CLICKHOUSE_DB"] == "ssf_analytics_test"
