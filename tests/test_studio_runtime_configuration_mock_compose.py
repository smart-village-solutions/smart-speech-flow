"""Compose contract tests for the opt-in Studio mock service."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNBOOK = ROOT / "docs/operations/keycloak-admin-access.md"


def test_studio_mock_is_loopback_only_without_a_traefik_route(development_compose: dict) -> None:
    service = development_compose["services"]["studio-mock"]

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
    assert "X-Studio-Tenant-Id" in runbook
    assert "tenant-not-ready" in runbook
    assert "/internal/plugins/ssf/v2/runtime-configuration" in runbook
    assert "/internal/plugins/ssf/v2/installation-content" in runbook
    assert "services/studio_mock/fixtures/" in runbook
    assert "storage-disabled" in runbook
    assert "invalid-content" in runbook
    assert "tenant-marburg" in runbook
    assert "Installation content ignores the tenant scenarios" in runbook
    assert "a missing `X-Correlation-Id`" in runbook
