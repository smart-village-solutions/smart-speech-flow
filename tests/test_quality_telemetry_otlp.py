"""The OTLP adapter is the only place opentelemetry may be imported."""

import ast
import pathlib
import threading
from datetime import datetime, timezone

import pytest
from opentelemetry.sdk._logs.export import LogExporter, LogExportResult

import services.api_gateway.quality_telemetry_otlp as module
from services.api_gateway.quality_telemetry import DisallowedTelemetryAttribute
from services.api_gateway.quality_telemetry_otlp import build_otlp_exporter

ROOT = pathlib.Path(__file__).parents[1]
CONTRACT_MODULE = ROOT / "services" / "api_gateway" / "quality_telemetry.py"
_EMITTED_AT = datetime(2026, 9, 1, 12, 34, 56, tzinfo=timezone.utc)


def _imported_packages(source: str) -> set[str]:
    packages = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            packages.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            packages.add(node.module.split(".")[0])
    return packages


def test_the_contract_module_imports_no_opentelemetry_package() -> None:
    """Structural, not textual: prose naming OTel must not break this test."""
    packages = _imported_packages(CONTRACT_MODULE.read_text())
    assert "opentelemetry" not in packages, sorted(packages)


class _CapturingLogExporter(LogExporter):
    """Stands in for the HTTP exporter only. The SDK path stays real."""

    def __init__(self, sink: list) -> None:
        self._sink = sink

    def export(self, batch) -> LogExportResult:
        self._sink.extend(batch)
        return LogExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def _build(monkeypatch: pytest.MonkeyPatch, sink: list):
    monkeypatch.setattr(module, "OTLPLogExporter", lambda **_kwargs: _CapturingLogExporter(sink))
    return build_otlp_exporter(
        endpoint="http://localhost:4318/v1/logs",
        service_name="api_gateway",
        service_version="test-version",
        deployment_environment="test-env",
    )


@pytest.fixture
def exported(monkeypatch: pytest.MonkeyPatch):
    sink: list = []
    exporter = _build(monkeypatch, sink)
    try:
        yield exporter, sink
    finally:
        exporter.shutdown()


def _one_record(exporter, sink):
    """The readable wrapper: `resource` sits on it, the rest on `.log_record`."""
    exporter.force_flush()
    assert len(sink) == 1, sink
    return sink[0]


def test_the_resource_carries_only_the_three_declared_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OTEL_RESOURCE_ATTRIBUTES must not be able to widen what we ship.

    Deliberately not the `exported` fixture: the Resource is frozen when the
    provider is built, so setting these afterwards would prove nothing.
    """
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "ssf.leak=SECRET,net.peer.ip=10.1.2.3")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "hijacked")
    sink: list = []
    exporter = _build(monkeypatch, sink)

    try:
        exporter("telemetry_probe", {"ssf.quality.event_id": "abc"}, _EMITTED_AT)

        resource = _one_record(exporter, sink).resource
        assert dict(resource.attributes) == {
            "service.name": "api_gateway",
            "service.version": "test-version",
            "deployment.environment.name": "test-env",
        }
    finally:
        exporter.shutdown()


def test_the_exporter_rejects_a_disallowed_attribute_at_the_wire(exported) -> None:
    """The allowlist must be load-bearing where attributes actually leave."""
    exporter, sink = exported

    with pytest.raises(DisallowedTelemetryAttribute):
        exporter("telemetry_probe", {"ssf.quality.source_text": "Guten Tag"}, _EMITTED_AT)

    exporter.force_flush()
    assert sink == []


def test_the_events_own_emission_time_becomes_the_otlp_timestamp(exported) -> None:
    """Silver's emitted_at_utc must be the event's time, not an exporter fallback."""
    exporter, sink = exported

    exporter("telemetry_probe", {"ssf.quality.event_id": "abc"}, _EMITTED_AT)

    record = _one_record(exporter, sink).log_record
    assert record.timestamp is not None
    assert datetime.fromtimestamp(record.timestamp / 1e9, tz=timezone.utc) == _EMITTED_AT


def test_the_exporter_always_sends_an_empty_body(exported) -> None:
    """Body must always be empty — the bronze table indexes lower(Body)."""
    exporter, sink = exported

    exporter("telemetry_probe", {"ssf.quality.event_id": "abc"}, _EMITTED_AT)

    assert _one_record(exporter, sink).log_record.body == ""


def test_the_event_type_travels_as_the_top_level_event_name(exported) -> None:
    """Not as an attribute — it must reach the typed EventName column."""
    exporter, sink = exported

    exporter("telemetry_probe", {"ssf.quality.event_id": "abc"}, _EMITTED_AT)

    record = _one_record(exporter, sink).log_record
    assert record.event_name == "telemetry_probe"
    assert "event.name" not in dict(record.attributes or {})


def test_shutdown_stops_the_background_export_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An un-shut-down provider leaks a thread per gateway startup."""

    def batch_threads() -> list[str]:
        return [t.name for t in threading.enumerate() if "OtelBatch" in t.name]

    before = batch_threads()
    exporter = _build(monkeypatch, [])
    assert len(batch_threads()) == len(before) + 1

    exporter.shutdown()

    assert batch_threads() == before
