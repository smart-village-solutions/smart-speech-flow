"""Each gateway app owns its collaborators (#228 task 1.4).

create_app() builds an app whose lifespan builds its own dependency container.
Two apps, or two lifespans of one app, must not share anything the container
constructs, and a provider override on one app must not reach another.
"""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import create_app
from services.api_gateway.dependencies import GatewayDependencies, get_login_directory
from services.api_gateway.service_health import ServiceHealthManager
from services.api_gateway.studio_login_directory_client import StudioLoginDirectory

REVISION = f"sha256:{'a' * 64}"

CONTAINER_BUILT = (
    "session_manager",
    "realtime_tickets",
    "polling_store",
    "websocket_manager",
    "conversation_service",
    "session_lifecycle",
    "studio_runtime_flow",
    "login_directory",
    "service_health",
    "circuit_breaker_client",
    "speech_pipeline",
    "pipeline_admission",
    "quality_telemetry",
    "quality_telemetry_exporter",
)
# Module instances the container only refers to, until the PR named in the
# "Dependency ownership" table of the OpenSpec design replaces each of them.
ADAPTERS = (
    "prometheus_registry",
    "pseudonymizer",
    "websocket_monitor",
    "fallback_manager",
    "oidc_key_cache",
)
# None without a feedback database, as tests/gateway_contract/test_contract_lifespan.py pins.
FEEDBACK = (
    "feedback_repository",
    "feedback_maintenance_repository",
    "feedback_read_repository",
    "feedback_service",
    "feedback_read_service",
    "feedback_maintenance",
)


@pytest.fixture
def configured_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Studio configured and telemetry exporting, so every collaborator exists."""
    for variable in (
        "REDIS_URL",
        "SSF_DEPLOYMENT_ENV",
        "SSF_FEEDBACK_DATABASE_URL",
        "SSF_FEEDBACK_MAINTENANCE_DATABASE_URL",
        "SSF_FEEDBACK_READER_DATABASE_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "http://studio-mock:8000")
    monkeypatch.setenv("STUDIO_RUNTIME_FIXED_TOKEN", "studio-mock-authorized-token")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "probe")
    monkeypatch.setenv("SSF_OTLP_LOGS_ENDPOINT", "http://127.0.0.1:9/v1/logs")


def _built(dependencies: GatewayDependencies) -> dict[str, object]:
    """What the running lifespan built; shutdown releases part of it."""
    return {name: getattr(dependencies, name) for name in CONTAINER_BUILT}


def _assert_owned_separately(first: dict[str, object], second: dict[str, object]) -> None:
    for name in CONTAINER_BUILT:
        assert first[name] is not None, name
        assert second[name] is not None, name
        assert first[name] is not second[name], name


def test_every_container_field_is_classified() -> None:
    assert {field.name for field in fields(GatewayDependencies)} == {
        *CONTAINER_BUILT,
        *ADAPTERS,
        *FEEDBACK,
    }


@pytest.mark.usefixtures("configured_process")
def test_two_running_apps_hold_distinct_collaborators() -> None:
    first_app, second_app = create_app(), create_app()

    with TestClient(first_app), TestClient(second_app):
        first = first_app.state.dependencies
        second = second_app.state.dependencies
        assert first is not second
        _assert_owned_separately(_built(first), _built(second))
        for name in ADAPTERS:
            assert getattr(first, name) is getattr(second, name), name


@pytest.mark.usefixtures("configured_process")
def test_each_apps_session_manager_is_wired_to_that_apps_collaborators() -> None:
    first_app, second_app = create_app(), create_app()

    with TestClient(first_app), TestClient(second_app):
        gates = []
        for dependencies in (first_app.state.dependencies, second_app.state.dependencies):
            sessions = dependencies.session_manager
            assert sessions.realtime_tickets is dependencies.realtime_tickets
            assert sessions.polling_store is dependencies.polling_store
            assert sessions.websocket_manager is dependencies.websocket_manager
            assert sessions.pseudonymizer is dependencies.pseudonymizer
            assert sessions.runtime_policy is not None
            gates.append(sessions.runtime_policy)
        assert gates[0] is not gates[1]


@pytest.mark.usefixtures("configured_process")
def test_a_second_lifespan_builds_a_fresh_container() -> None:
    app = create_app()

    with TestClient(app):
        first = _built(app.state.dependencies)
    with TestClient(app):
        second = _built(app.state.dependencies)

    _assert_owned_separately(first, second)


def _speech_collaborators(dependencies: GatewayDependencies) -> list[object]:
    """Everything a speech call or a health report reaches in one app."""
    health = dependencies.service_health
    return [
        health,
        health.degradation,
        *health.circuit_breakers.values(),
        dependencies.speech_pipeline.speech,
        dependencies.speech_pipeline.refiner,
    ]


@pytest.mark.usefixtures("configured_process")
def test_two_running_apps_share_no_breaker_or_health_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Health polls that reach nothing would count failures on both apps' breakers.
    monkeypatch.setattr(
        ServiceHealthManager,
        "_perform_health_request",
        AsyncMock(return_value={"status_code": 200, "response_time": 0.0}),
    )
    first_app, second_app = create_app(), create_app()

    with TestClient(first_app) as first, TestClient(second_app) as second:
        first_dependencies = first_app.state.dependencies
        second_dependencies = second_app.state.dependencies
        shared = {id(item) for item in _speech_collaborators(first_dependencies)} & {
            id(item) for item in _speech_collaborators(second_dependencies)
        }
        assert not shared
        for dependencies in (first_dependencies, second_dependencies):
            assert dependencies.circuit_breaker_client.circuit_breakers() == (
                dependencies.service_health.circuit_breakers
            )

        tts = first_dependencies.service_health.circuit_breakers["tts"]
        for _ in range(tts.config.failure_threshold):
            tts.record_failure("opened on the first app only")

        opened = first.get("/api/health/circuit-breakers").json()["circuits"]["tts"]
        untouched = second.get("/api/health/circuit-breakers").json()["circuits"]["tts"]
        assert (opened["state"], untouched["state"]) == ("open", "closed")
        assert untouched["circuit_info"]["failure_count"] == 0

    for dependencies in (first_dependencies, second_dependencies):
        assert dependencies.service_health.is_monitoring is False
        assert dependencies.service_health.session is None


class _StubDirectory:
    async def get(self, correlation_id: str) -> StudioLoginDirectory:
        return StudioLoginDirectory.model_validate(
            {
                "contractVersion": "1.0",
                "directoryRevision": REVISION,
                "tenants": [{"id": "tenant-a", "displayName": "Tenant A", "realm": "realm-a"}],
            }
        )


def test_a_provider_override_stays_on_its_own_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", raising=False)
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    overridden, untouched = create_app(), create_app()
    overridden.dependency_overrides[get_login_directory] = _StubDirectory

    with TestClient(overridden) as first, TestClient(untouched) as second:
        assert first.get("/api/login/tenants").json() == {
            "tenants": [{"id": "tenant-a", "displayName": "Tenant A", "realm": "realm-a"}]
        }
        assert second.get("/api/login/tenants").status_code == 503

    assert untouched.dependency_overrides == {}
