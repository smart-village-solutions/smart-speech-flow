"""Each gateway app owns its collaborators (#228 task 1.4).

create_app() builds an app whose lifespan builds its own dependency container.
Two apps, or two lifespans of one app, must not share anything the container
constructs, and a provider override on one app must not reach another.
"""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import Counter, Gauge

from services.api_gateway.app import create_app
from services.api_gateway.dependencies import GatewayDependencies, get_login_directory
from services.api_gateway.service_health import ServiceHealthManager
from services.api_gateway.studio_login_directory_client import StudioLoginDirectory
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

REVISION = f"sha256:{'a' * 64}"

CONTAINER_BUILT = (
    "pseudonymizer",
    "websocket_monitor",
    "audio_store",
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
    "oidc_key_cache",
)
# Built once per app by create_app(), so every lifespan of that app reuses it.
APP_BUILT = ("prometheus_registry",)
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
        *APP_BUILT,
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
        for name in APP_BUILT:
            assert getattr(first, name) is not getattr(second, name), name


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
            # One reference per session in the manager's and the monitor's log lines.
            assert dependencies.websocket_monitor.pseudonymizer is dependencies.pseudonymizer
            assert dependencies.websocket_manager.monitor is dependencies.websocket_monitor
            assert sessions.runtime_policy is not None
            gates.append(sessions.runtime_policy)
        assert gates[0] is not gates[1]


@pytest.mark.usefixtures("configured_process")
def test_a_second_lifespan_builds_a_fresh_container() -> None:
    app = create_app()

    with TestClient(app):
        first_container = app.state.dependencies
        first = _built(first_container)
    with TestClient(app):
        second_container = app.state.dependencies
        second = _built(second_container)

    _assert_owned_separately(first, second)
    for name in APP_BUILT:
        assert getattr(first_container, name) is getattr(second_container, name), name


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


def test_polling_records_presence_in_its_own_apps_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """A poller's presence lands in the session manager of the app it polled.

    Each app's session store is its own, so a route that reached another
    app's manager would not find the session at all.
    """
    for variable in ("REDIS_URL", "SSF_DEPLOYMENT_ENV", "STUDIO_RUNTIME_CONFIGURATION_BASE_URL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    snapshot = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")
    first_app, second_app = create_app(), create_app()

    with TestClient(first_app) as first, TestClient(second_app) as second:
        keys = []
        for client, app in ((first, first_app), (second, second_app)):
            sessions = app.state.dependencies.session_manager
            session = client.portal.call(sessions.create_admin_session, "tenant-a", snapshot)
            activated = client.post(f"/api/customer/session/{session.id}/polling/activate")
            assert activated.status_code == 200, activated.text
            keys.append(session.key)

        for app, key in ((first_app, keys[0]), (second_app, keys[1])):
            sessions = app.state.dependencies.session_manager
            assert sessions.get_session(key).customer_connection_count == 1
        assert first_app.state.dependencies.session_manager.get_session(keys[1]) is None


def _metric_objects(app: FastAPI) -> dict[str, object]:
    metrics = app.state.gateway_metrics
    return {field.name: getattr(metrics, field.name) for field in fields(metrics)}


def _count_on_metrics(client: TestClient, family: str) -> str:
    lines = [line for line in client.get("/metrics").text.splitlines() if line.startswith(family)]
    assert len(lines) == 1, lines
    return lines[0]


def test_two_apps_share_no_registry_or_series() -> None:
    first_app, second_app = create_app(), create_app()

    first, second = _metric_objects(first_app), _metric_objects(second_app)
    assert first.keys() == second.keys()
    for name in first:
        assert first[name] is not second[name], name
    assert first_app.state.prometheus_registry is first["registry"]
    served = [app.state.prometheus_registry._collector_to_names for app in (first_app, second_app)]
    assert not set(map(id, served[0])) & set(map(id, served[1]))


@pytest.mark.usefixtures("configured_process")
def test_one_apps_metrics_do_not_show_anothers_counts() -> None:
    first_app, second_app = create_app(), create_app()

    with TestClient(first_app) as first, TestClient(second_app) as second:
        # Counted before the upload is validated, so no speech service is reached.
        refused = first.post(
            "/pipeline",
            files={"file": ("speech.wav", b"not a wav", "audio/wav")},
            data={"source_lang": "de", "target_lang": "en"},
        )
        assert refused.status_code != 200

        assert _count_on_metrics(first, "gateway_requests_total ") == "gateway_requests_total 1.0"
        assert _count_on_metrics(second, "gateway_requests_total ") == "gateway_requests_total 0.0"


def _sample(metric: Counter | Gauge, directory: str) -> float | None:
    for family in metric.collect():
        for sample in family.samples:
            if sample.labels.get("directory") == directory and not sample.name.endswith("_created"):
                return float(sample.value)
    return None


@pytest.mark.usefixtures("configured_process")
def test_each_apps_audio_store_counts_into_that_apps_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import os
    import time

    from services.api_gateway.audio_storage import AudioVariant
    from services.api_gateway.tenant_session import TenantSessionKey

    monkeypatch.setenv("SSF_AUDIO_BASE_DIR", str(tmp_path))
    first_app, second_app = create_app(), create_app()

    with TestClient(first_app), TestClient(second_app):
        store = first_app.state.dependencies.audio_store
        assert store.metrics is first_app.state.gateway_metrics.audio_storage
        assert second_app.state.dependencies.audio_store.metrics is (
            second_app.state.gateway_metrics.audio_storage
        )
        key = TenantSessionKey("tenant-a", "SESSION1")
        kept = store.save(key, "kept", AudioVariant.ORIGINAL, b"RIFF")
        expired = store.save(key, "expired", AudioVariant.ORIGINAL, b"RIFFRIFF")
        two_days_ago = time.time() - 2 * 24 * 3600
        os.utime(expired, (two_days_ago, two_days_ago))

        assert store.cleanup_expired()["deleted_original"] == 1
        assert store.disk_usage()["original_files"] == 1
        assert kept.exists()

        counted = first_app.state.gateway_metrics.audio_storage
        untouched = second_app.state.gateway_metrics.audio_storage
        assert _sample(counted.cleanup_deleted_files, "original") == 1.0
        assert _sample(counted.files, "original") == 1.0
        assert _sample(counted.disk_usage_bytes, "original") == 4.0
        for metric in (
            untouched.cleanup_deleted_files,
            untouched.files,
            untouched.disk_usage_bytes,
        ):
            assert _sample(metric, "original") is None


@pytest.mark.usefixtures("configured_process")
def test_an_oidc_key_cached_by_one_app_stays_there() -> None:
    first_app, second_app = create_app(), create_app()
    issuer = "https://keycloak.example/realms/tenant-a"

    with TestClient(first_app), TestClient(second_app):
        cached = first_app.state.dependencies.oidc_key_cache
        cached.entries[issuer] = (float("inf"), {"kid-1": {"kid": "kid-1"}})

        assert second_app.state.dependencies.oidc_key_cache.entries == {}

    # A new lifespan starts with no keys, as a new process always has.
    with TestClient(first_app):
        assert first_app.state.dependencies.oidc_key_cache.entries == {}
