"""A telemetry failure must never change the caller's outcome."""

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import UUID

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.quality_telemetry import (
    DisallowedTelemetryAttribute,
    ProbeOutcome,
    QualityTelemetry,
    TelemetryMode,
)

_EVENT_TYPE = "telemetry_probe"
_COUNTER = "ssf_quality_telemetry_events_total"


class _Recorder:
    """Three-argument exporter double, matching the shipped adapter's contract."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], datetime]] = []

    def __call__(
        self, event_name: str, attributes: Mapping[str, str], emitted_at_utc: datetime
    ) -> None:
        self.calls.append((event_name, dict(attributes), emitted_at_utc))


def _raising(error: BaseException):
    def export(_name: str, _attributes: Mapping[str, str], _emitted_at_utc: datetime) -> None:
        raise error

    return export


def _telemetry(exporter, *, mode=TelemetryMode.PROBE, registry=None) -> QualityTelemetry:
    return QualityTelemetry(mode=mode, exporter=exporter, registry=registry or CollectorRegistry())


def _count(registry: CollectorRegistry, outcome: str) -> float:
    return registry.get_sample_value(_COUNTER, {"outcome": outcome}) or 0.0


def test_a_successful_emission_reports_emitted_and_counts_it() -> None:
    recorder = _Recorder()
    registry = CollectorRegistry()

    result = _telemetry(recorder, registry=registry).emit_probe(event_type=_EVENT_TYPE)

    assert result.outcome is ProbeOutcome.EMITTED
    assert isinstance(result.event_id, UUID)
    assert len(recorder.calls) == 1
    name, attributes, _emitted_at = recorder.calls[0]
    assert name == _EVENT_TYPE
    assert attributes["ssf.quality.event_id"] == str(result.event_id)
    assert _count(registry, "emitted") == 1.0


def test_a_failed_export_is_distinguishable_from_a_successful_one() -> None:
    """The #199 acceptance criterion, as a unit test. No containers."""
    registry = CollectorRegistry()

    result = _telemetry(
        _raising(ConnectionError("ClickHouse is down")), registry=registry
    ).emit_probe(event_type=_EVENT_TYPE)

    assert result.outcome is ProbeOutcome.EXPORT_FAILED
    assert isinstance(result.event_id, UUID)
    assert _count(registry, "export_failed") == 1.0
    assert _count(registry, "emitted") == 0.0


def test_an_allowlist_rejection_at_the_wire_is_counted_as_disallowed() -> None:
    """The adapter enforces the allowlist; this is how that surfaces here."""
    registry = CollectorRegistry()

    result = _telemetry(
        _raising(DisallowedTelemetryAttribute("disallowed attribute keys: ['x']")),
        registry=registry,
    ).emit_probe(event_type=_EVENT_TYPE)

    assert result.outcome is ProbeOutcome.DROPPED_DISALLOWED
    assert _count(registry, "dropped_disallowed") == 1.0
    assert _count(registry, "export_failed") == 0.0


def test_every_outcome_label_is_one_the_code_can_actually_emit() -> None:
    """No dead metric labels: a dashboard series nothing increments is a lie.

    Every member of the enum, with no exemptions — `disabled` included, because
    disabled is the production default and a scrape that shows no series at all
    cannot tell "off on purpose" from "never wired up".
    """
    registry = CollectorRegistry()

    _telemetry(_Recorder(), registry=registry).emit_probe(event_type=_EVENT_TYPE)
    _telemetry(_raising(ConnectionError("down")), registry=registry).emit_probe(
        event_type=_EVENT_TYPE
    )
    _telemetry(_raising(DisallowedTelemetryAttribute("nope")), registry=registry).emit_probe(
        event_type=_EVENT_TYPE
    )
    _telemetry(_Recorder(), mode=TelemetryMode.DISABLED, registry=registry).emit_probe(
        event_type=_EVENT_TYPE
    )

    assert [_count(registry, o.value) for o in ProbeOutcome] == [1.0] * len(ProbeOutcome)


@pytest.mark.parametrize(
    "failure", [ConnectionError, TimeoutError, RuntimeError, MemoryError, TypeError]
)
def test_no_exporter_failure_kind_escapes(failure: type[Exception]) -> None:
    result = _telemetry(_raising(failure("boom"))).emit_probe(event_type=_EVENT_TYPE)
    assert result.outcome is ProbeOutcome.EXPORT_FAILED


@pytest.mark.parametrize("signal", [asyncio.CancelledError, KeyboardInterrupt, SystemExit])
def test_control_flow_exceptions_are_not_swallowed(signal: type[BaseException]) -> None:
    """Swallowing these turns a cancelled request into a silently continued one."""
    telemetry = _telemetry(_raising(signal()))

    with pytest.raises(signal):
        telemetry.emit_probe(event_type=_EVENT_TYPE)


def test_disabled_mode_exports_nothing_but_still_records_the_outcome() -> None:
    """Counting it is what makes "telemetry is off" observable in a scrape."""
    recorder = _Recorder()
    registry = CollectorRegistry()

    result = _telemetry(recorder, mode=TelemetryMode.DISABLED, registry=registry).emit_probe(
        event_type=_EVENT_TYPE
    )

    assert result.outcome is ProbeOutcome.DISABLED
    assert result.event_id is None
    assert recorder.calls == []
    assert _count(registry, "disabled") == 1.0
    assert _count(registry, "emitted") == 0.0


def test_the_exporter_receives_only_the_two_allowlisted_attributes() -> None:
    recorder = _Recorder()

    _telemetry(recorder).emit_probe(event_type=_EVENT_TYPE)

    _name, attributes, _emitted_at = recorder.calls[0]
    assert set(attributes) == {
        "ssf.quality.event_id",
        "ssf.quality.schema_version",
    }


def test_the_exporter_is_called_with_the_events_own_emission_time() -> None:
    """A signature mismatch here would surface only as a silent export_failed."""
    recorder = _Recorder()

    before = datetime.now(timezone.utc)
    result = _telemetry(recorder).emit_probe(event_type=_EVENT_TYPE)
    after = datetime.now(timezone.utc)

    assert result.outcome is ProbeOutcome.EMITTED, result
    _name, _attributes, emitted_at = recorder.calls[0]
    assert emitted_at.tzinfo is not None
    assert before <= emitted_at <= after


def test_each_emission_has_a_distinct_event_id() -> None:
    telemetry = _telemetry(_Recorder())
    ids = {telemetry.emit_probe(event_type=_EVENT_TYPE).event_id for _ in range(50)}
    assert len(ids) == 50


def test_two_instances_share_one_registry_without_a_duplicate_registration() -> None:
    """The real trap: lifespan re-entry rebuilds the emitter over app.state's registry."""
    registry = CollectorRegistry()

    for _ in range(2):
        _telemetry(_Recorder(), registry=registry).emit_probe(event_type=_EVENT_TYPE)

    assert _count(registry, "emitted") == 2.0
