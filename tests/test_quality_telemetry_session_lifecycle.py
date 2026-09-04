"""The `session_lifecycle` event: the funnel every session ratio divides by.

`translation_message` counts messages; nothing counted sessions, so "messages
per session" and "sessions that never carried one" had no denominator. Every
field here already exists on the `Session` dataclass -- this event stores a
pseudonymised reference, two closed enums and two counts, and nothing else.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.quality_telemetry import (
    ALLOWED_ATTRIBUTES,
    ALLOWED_ATTRIBUTE_KEYS,
    AttributeKind,
    ProbeOutcome,
    QualityEventType,
    QualityTelemetry,
    SessionLifecycleEvent,
    SessionLifecyclePhase,
    SessionTerminationReason,
    TelemetryMode,
    discard_event,
    to_otlp_attributes,
)

REFERENCE = "c" * 32


def _event(**overrides) -> SessionLifecycleEvent:
    fields = dict(
        event_id=uuid4(),
        schema_version=1,
        emitted_at_utc=datetime.now(timezone.utc),
        event_type=QualityEventType.SESSION_LIFECYCLE,
        session_ref=REFERENCE,
        phase=SessionLifecyclePhase.TERMINATED,
        termination_reason=SessionTerminationReason.SESSION_TIMEOUT,
        session_duration_ms=1_800_000,
        message_count=12,
    )
    fields.update(overrides)
    return SessionLifecycleEvent(**fields)


class _Recording:
    def __init__(self):
        self.calls = []

    def __call__(self, name, attributes, emitted_at_utc):
        self.calls.append((name, dict(attributes), emitted_at_utc))


def _telemetry(mode=TelemetryMode.ENABLED, exporter=None):
    return QualityTelemetry(
        mode=mode, exporter=exporter or discard_event, registry=CollectorRegistry()
    )


def _emit(telemetry, **overrides):
    fields = dict(
        session_ref=REFERENCE,
        phase=SessionLifecyclePhase.TERMINATED,
        termination_reason=SessionTerminationReason.SESSION_TIMEOUT,
        session_duration_ms=1_800_000,
        message_count=12,
    )
    fields.update(overrides)
    return telemetry.emit_session_lifecycle(**fields)


class TestTheEventCarriesNoContent:
    def test_every_attribute_is_a_number_an_enum_or_an_opaque_reference(self):
        kinds = {ALLOWED_ATTRIBUTES[key].kind for key in to_otlp_attributes(_event())}

        assert kinds <= {
            AttributeKind.UUID,
            AttributeKind.NUMBER,
            AttributeKind.ENUM,
            AttributeKind.OPAQUE_REF,
        }

    def test_it_has_no_label_or_language_field(self):
        kinds = {ALLOWED_ATTRIBUTES[key].kind for key in to_otlp_attributes(_event())}

        assert AttributeKind.LABEL not in kinds

    def test_the_termination_reason_is_a_closed_enum_not_the_string_it_came_from(self):
        """`terminate_session(session_id, reason)` takes a free-form `str`.

        Anything a caller invents must land as `other`, or the reason becomes a
        free-text channel into a store that has no free-text kind.
        """
        assert (
            ALLOWED_ATTRIBUTES["ssf.quality.termination_reason"].kind
            is AttributeKind.ENUM
        )

    def test_a_session_reference_of_the_wrong_shape_is_rejected(self):
        with pytest.raises(ValueError):
            _event(session_ref="ABC123")


class TestInvariants:
    @pytest.mark.parametrize("field", ["session_duration_ms", "message_count"])
    def test_negative_counts_are_rejected(self, field):
        with pytest.raises(ValueError):
            _event(**{field: -1})

    @pytest.mark.parametrize(
        "phase", [SessionLifecyclePhase.CREATED, SessionLifecyclePhase.ACTIVATED]
    )
    def test_a_session_that_has_not_ended_cannot_name_a_reason(self, phase):
        with pytest.raises(ValueError):
            _event(
                phase=phase, termination_reason=SessionTerminationReason.SESSION_TIMEOUT
            )

    def test_a_terminated_session_must_name_a_reason(self):
        with pytest.raises(ValueError):
            _event(
                phase=SessionLifecyclePhase.TERMINATED,
                termination_reason=SessionTerminationReason.NONE,
            )

    def test_a_well_formed_creation_is_accepted(self):
        event = _event(
            phase=SessionLifecyclePhase.CREATED,
            termination_reason=SessionTerminationReason.NONE,
            session_duration_ms=0,
            message_count=0,
        )

        assert to_otlp_attributes(event)["ssf.quality.lifecycle_phase"] == "created"


class TestTheSixPlacesAgree:
    def test_every_attribute_the_event_emits_is_allowlisted(self):
        assert set(to_otlp_attributes(_event())) <= ALLOWED_ATTRIBUTE_KEYS

    @pytest.mark.parametrize(
        "key",
        [
            "ssf.quality.lifecycle_phase",
            "ssf.quality.termination_reason",
            "ssf.quality.session_duration_ms",
            "ssf.quality.message_count",
        ],
    )
    def test_the_event_emits_each_of_its_declared_fields(self, key):
        assert key in to_otlp_attributes(_event())

    def test_the_session_reference_reuses_the_message_events_key(self):
        """One key, one meaning: joining sessions to their messages depends on
        both events deriving the reference the same way."""
        assert to_otlp_attributes(_event())["ssf.quality.session_ref"] == REFERENCE


class TestEmission:
    def test_an_enabled_gateway_emits_the_event(self):
        exporter = _Recording()

        result = _emit(_telemetry(exporter=exporter))

        assert result.outcome is ProbeOutcome.EMITTED
        assert exporter.calls[0][0] == QualityEventType.SESSION_LIFECYCLE.value

    @pytest.mark.parametrize("mode", [TelemetryMode.DISABLED, TelemetryMode.PROBE])
    def test_probe_mode_stays_a_transport_check(self, mode):
        exporter = _Recording()

        result = _emit(_telemetry(mode=mode, exporter=exporter))

        assert result.outcome is ProbeOutcome.DISABLED
        assert exporter.calls == []

    def test_hostile_values_are_coerced_rather_than_dropping_the_row(self):
        exporter = _Recording()

        result = _emit(
            _telemetry(exporter=exporter),
            session_ref="session-ABC123",
            session_duration_ms=-5,
            message_count=None,
        )

        assert result.outcome is ProbeOutcome.EMITTED
        attributes = exporter.calls[0][1]
        assert attributes["ssf.quality.session_duration_ms"] == "0"
        assert attributes["ssf.quality.message_count"] == "0"
        assert "session-ABC123" not in attributes.values()

    def test_an_export_failure_never_reaches_the_caller(self):
        def explode(name, attributes, emitted_at_utc):
            raise RuntimeError("ClickHouse is gone")

        assert _emit(_telemetry(exporter=explode)).outcome is ProbeOutcome.EXPORT_FAILED


class TestTerminationReasonMapping:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("session_timeout", SessionTerminationReason.SESSION_TIMEOUT),
            ("new_session_created", SessionTerminationReason.NEW_SESSION_CREATED),
            (
                "manual_admin_termination",
                SessionTerminationReason.MANUAL_ADMIN_TERMINATION,
            ),
            ("manual_termination", SessionTerminationReason.MANUAL_TERMINATION),
            ("system_cleanup", SessionTerminationReason.SYSTEM_CLEANUP),
        ],
    )
    def test_every_reason_the_gateway_actually_passes_has_a_member(self, raw, expected):
        assert SessionTerminationReason.classify(raw) is expected

    @pytest.mark.parametrize(
        "raw", ["something_new", "", None, "a whole sentence about the user", 42]
    )
    def test_anything_else_is_other_rather_than_stored_verbatim(self, raw):
        assert SessionTerminationReason.classify(raw) is SessionTerminationReason.OTHER
