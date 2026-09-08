"""Compose contract tests for the opt-in Studio mock service."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
RUNBOOK = ROOT / "docs/operations/keycloak-admin-access.md"


def test_studio_mock_publishes_http_port_on_all_interfaces() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["studio-mock"]

    assert service["profiles"] == ["studio-mock"]
    assert service["ports"] == ["8010:8000"]
    assert service.get("labels") is None
    assert service["build"]["dockerfile"] == "services/studio_mock/Dockerfile"


def test_runbook_documents_unauthenticated_http_mock_startup() -> None:
    runbook = RUNBOOK.read_text()

    assert "studio-mock" in runbook
    assert "http://<host-ip>:8010" in runbook
    assert "does not require authentication" in runbook
