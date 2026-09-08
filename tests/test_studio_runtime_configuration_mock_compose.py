"""Compose contract tests for the opt-in Studio mock service."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
RUNBOOK = ROOT / "docs/operations/keycloak-admin-access.md"


def test_studio_mock_is_loopback_only_without_a_traefik_route() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["studio-mock"]

    assert service["profiles"] == ["studio-mock"]
    assert service["ports"] == ["127.0.0.1:8010:8000"]
    assert service.get("labels") is None
    assert service["build"]["dockerfile"] == "services/studio_mock/Dockerfile"


def test_runbook_documents_protected_swappable_mock_endpoint() -> None:
    runbook = RUNBOOK.read_text()

    assert "studio-mock" in runbook
    assert "http://127.0.0.1:8010" in runbook
    assert "http://studio-mock:8000" in runbook
    assert "studio-mock-authorized-token" in runbook
    assert "STUDIO_RUNTIME_CONFIGURATION_BASE_URL" in runbook
    assert "X-Studio-Tenant-Id: tenant-kassel" in runbook
    assert "tenant-suspended" in runbook
    assert "plugin-inactive" in runbook
    assert "tenant-not-ready" in runbook
    assert "authorization-pending" not in runbook
    assert "X-Studio-Instance-Id" not in runbook
    assert "X-Tenant-Id" not in runbook
