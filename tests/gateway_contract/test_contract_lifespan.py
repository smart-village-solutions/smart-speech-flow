"""What the lifespan wires onto app.state, and what it releases on shutdown."""

from __future__ import annotations

import pytest

FEEDBACK_COLLABORATORS = (
    "feedback_repository",
    "feedback_maintenance_repository",
    "feedback_read_repository",
    "feedback_service",
    "feedback_read_service",
    "feedback_maintenance",
)
RELEASED_ON_SHUTDOWN = ("pipeline_admission", "quality_telemetry_exporter", *FEEDBACK_COLLABORATORS)


@pytest.fixture
def local_environment(monkeypatch):
    """A development process: no Redis, no feedback database, no Studio."""
    for variable in (
        "REDIS_URL",
        "SSF_DEPLOYMENT_ENV",
        "SSF_FEEDBACK_DATABASE_URL",
        "SSF_FEEDBACK_MAINTENANCE_DATABASE_URL",
        "SSF_FEEDBACK_READER_DATABASE_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SSF_OTLP_LOGS_ENDPOINT", "http://127.0.0.1:9/v1/logs")
    return monkeypatch


@pytest.mark.parametrize("telemetry_mode", ["disabled", "probe"])
def test_startup_wires_the_request_collaborators(
    client, gateway, local_environment, telemetry_mode
):
    local_environment.setenv("SSF_QUALITY_TELEMETRY_MODE", telemetry_mode)

    with client:
        state = gateway.state
        assert state.pipeline_admission is not None
        assert state.quality_telemetry is not None
        assert state.quality_telemetry.mode.value == telemetry_mode
        assert (state.quality_telemetry_exporter is not None) is (telemetry_mode == "probe")
        assert state.prometheus_registry is not None
        for name in FEEDBACK_COLLABORATORS:
            assert getattr(state, name) is None, name
        assert client.post("/api/admin/session/create").status_code == 201
        assert client.get("/metrics").status_code == 200


@pytest.mark.parametrize("telemetry_mode", ["disabled", "probe"])
def test_shutdown_releases_what_startup_acquired(
    client, gateway, local_environment, telemetry_mode
):
    local_environment.setenv("SSF_QUALITY_TELEMETRY_MODE", telemetry_mode)

    with client:
        pass

    for name in RELEASED_ON_SHUTDOWN:
        assert getattr(gateway.state, name) is None, name


@pytest.mark.usefixtures("local_environment")
def test_a_second_lifespan_wires_a_fresh_admission_gate(client, gateway):
    with client:
        first = gateway.state.pipeline_admission
    with client:
        second = gateway.state.pipeline_admission

    assert first is not None
    assert second is not None
    assert first is not second
