"""The probe endpoint is admin-authenticated and never fails on telemetry."""

from collections.abc import Iterator, Mapping
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.quality_telemetry import QualityTelemetry, TelemetryMode

_PROBE_URL = "/api/admin/telemetry/probe"


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[require_ssf_user] = lambda: {"sub": "test-admin"}
    previous = getattr(app.state, "quality_telemetry", None)
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.state.quality_telemetry = previous


def _install(exporter, mode: TelemetryMode = TelemetryMode.PROBE) -> None:
    app.state.quality_telemetry = QualityTelemetry(
        mode=mode, exporter=exporter, registry=CollectorRegistry()
    )


def _accepting(sink: list) -> object:
    def export(name: str, attributes: Mapping[str, str], emitted_at_utc: datetime) -> None:
        sink.append(dict(attributes))

    return export


def _broken(name: str, attributes: Mapping[str, str], emitted_at_utc: datetime) -> None:
    raise ConnectionError("down")


def test_a_successful_probe_reports_the_event_id_and_the_emitted_outcome(
    client: TestClient,
) -> None:
    seen: list[Mapping[str, str]] = []
    _install(_accepting(seen))

    response = client.post(_PROBE_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == seen[0]["ssf.quality.event_id"]
    assert body["outcome"] == "emitted"
    assert body["mode"] == "probe"


def test_a_probe_that_never_reached_clickhouse_says_so(client: TestClient) -> None:
    """A 200 with an event_id and no outcome would claim a row that never lands."""
    _install(_broken)

    response = client.post(_PROBE_URL)

    assert response.status_code == 200
    assert response.json()["outcome"] == "export_failed"


def test_an_outage_does_not_change_the_request_result(client: TestClient) -> None:
    _install(_broken)
    assert client.post(_PROBE_URL).status_code == 200


def test_a_disabled_probe_reports_disabled_and_no_event_id(client: TestClient) -> None:
    _install(_accepting([]), mode=TelemetryMode.DISABLED)

    body = client.post(_PROBE_URL).json()

    assert body["mode"] == "disabled"
    assert body["outcome"] == "disabled"
    assert body["event_id"] is None


def test_the_probe_requires_authentication() -> None:
    app.dependency_overrides.clear()  # do not depend on another test's teardown
    _install(_accepting([]))
    assert TestClient(app).post(_PROBE_URL).status_code in (401, 403)
