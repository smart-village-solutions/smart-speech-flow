"""Binding the gate must never be able to stop the gateway starting."""

import pytest

from services.api_gateway.app import app, lifespan

_STUDIO_VARIABLES = (
    "STUDIO_RUNTIME_CONFIGURATION_BASE_URL",
    "STUDIO_RUNTIME_FIXED_TOKEN",
    "STUDIO_RUNTIME_TOKEN_URL",
    "STUDIO_RUNTIME_CLIENT_SECRET",
)


@pytest.fixture(autouse=True)
def quiet_lifespan(monkeypatch: pytest.MonkeyPatch):
    """Keep the lifespan local: no telemetry exporter, no Redis."""
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")


def _configure_studio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "http://studio-mock:8000")
    monkeypatch.setenv("STUDIO_RUNTIME_FIXED_TOKEN", "studio-mock-authorized-token")


async def test_gateway_starts_with_no_studio_configuration(monkeypatch):
    for name in _STUDIO_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    async with lifespan(app):
        assert app.state is not None
        assert app.state.dependencies.session_manager.runtime_policy is None


async def test_gateway_binds_the_gate_when_configured(monkeypatch):
    _configure_studio(monkeypatch)
    async with lifespan(app):
        assert app.state.dependencies.session_manager.runtime_policy is not None


async def test_shutdown_unbinds_the_gate(monkeypatch):
    _configure_studio(monkeypatch)
    async with lifespan(app):
        sessions = app.state.dependencies.session_manager
    assert sessions.runtime_policy is None


def test_timeout_variable_reaches_the_client(monkeypatch):
    from services.api_gateway.studio_runtime_flow import (
        runtime_flow_from_environment,
    )

    _configure_studio(monkeypatch)
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS", "2.5")
    flow = runtime_flow_from_environment()
    assert flow.client.timeout_seconds == pytest.approx(2.5)


def test_timeout_defaults_to_the_client_default(monkeypatch):
    from services.api_gateway.studio_runtime_flow import (
        runtime_flow_from_environment,
    )

    _configure_studio(monkeypatch)
    monkeypatch.delenv("STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS", raising=False)
    flow = runtime_flow_from_environment()
    assert flow.client.timeout_seconds == pytest.approx(5.0)


@pytest.mark.parametrize("raw", ["60", "0", "-1", "not-a-number", "31"])
def test_an_out_of_range_timeout_falls_back_instead_of_breaking_the_flow(monkeypatch, raw):
    """A bad timeout must not take tenant login down with it.

    `runtime_flow_from_environment` also backs
    `require_validated_runtime_configuration`, so letting the client's range
    check raise here turns every tenant-login runtime-configuration request
    into a 502 -- far beyond unbinding the persistence gate.
    """
    from services.api_gateway.studio_runtime_flow import (
        runtime_flow_from_environment,
    )

    _configure_studio(monkeypatch)
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS", raw)
    flow = runtime_flow_from_environment()
    assert flow.client.timeout_seconds == pytest.approx(5.0)
