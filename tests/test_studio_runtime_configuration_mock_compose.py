"""Compose contract tests for the local-only Studio mock service."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
RUNBOOK = ROOT / "docs/operations/keycloak-admin-access.md"


def test_studio_mock_is_an_opt_in_local_service_without_a_traefik_route() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["studio-mock"]

    assert service["profiles"] == ["studio-mock"]
    assert service["ports"] == ["127.0.0.1:8010:8000"]
    assert service.get("labels") is None
    assert service["build"]["dockerfile"] == "services/studio_mock/Dockerfile"


def test_runbook_documents_local_mock_startup_and_production_exclusion() -> None:
    runbook = RUNBOOK.read_text()

    assert "studio-mock" in runbook
    assert "studio-mock-service-token" in runbook
    assert "must not be enabled in production" in runbook
