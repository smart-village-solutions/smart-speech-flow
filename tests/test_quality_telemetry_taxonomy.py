"""The event and error taxonomy: closed, typed, and incapable of carrying content.

Task 1.1 asks for versioned, typed, allowlisted event models and a stable error
taxonomy; 3.1 and 3.2 constrain every field to a number, a closed enum, or an
opaque reference. Those are the same requirement seen from two sides, so they
are enforced here as one rule: an attribute may only be emitted if the manifest
declares what shape its value has, and the value must actually have that shape.

Name-based checks alone cannot do this -- `error_code` reads like content and is
not, `translation_duration_ms` reads like content and is not -- so the manifest
declares a kind per key and the value is checked against it.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.api_gateway.quality_telemetry import (
    ALLOWED_ATTRIBUTE_KEYS,
    ALLOWED_ATTRIBUTES,
    SCHEMA_VERSION,
    AttributeKind,
    DisallowedTelemetryAttribute,
    DisallowedTelemetryValue,
    PipelineStage,
    QualityErrorCode,
    QualityEventType,
    RefinementAttemptEvent,
    RefinerRole,
    RefinementOutcomeCode,
    TelemetryMode,
    classify_upstream_status,
    classify_exception,
    enforce_value_shapes,
    to_otlp_attributes,
)

REFINEMENT_KEYS = {
    "ssf.quality.refiner_role",
    "ssf.quality.model_ref",
    "ssf.quality.refinement_outcome",
    "ssf.quality.refinement_latency_ms",
    "ssf.quality.refinement_changed",
    "ssf.quality.source_lang",
    "ssf.quality.target_lang",
    "ssf.quality.error_code",
}


def _refinement_event(**overrides) -> RefinementAttemptEvent:
    defaults = dict(
        event_id=uuid4(),
        schema_version=SCHEMA_VERSION,
        emitted_at_utc=datetime.now(timezone.utc),
        event_type=QualityEventType.REFINEMENT_ATTEMPT,
        refiner_role=RefinerRole.CANDIDATE,
        model_ref="phi4-mini",
        outcome=RefinementOutcomeCode.SUCCESS,
        latency_ms=340,
        changed=True,
        source_lang="en",
        target_lang="de",
        error_code=QualityErrorCode.NONE,
    )
    defaults.update(overrides)
    return RefinementAttemptEvent(**defaults)


class TestManifestIsClosed:
    def test_every_allowlisted_key_declares_a_value_shape(self):
        assert set(ALLOWED_ATTRIBUTES) == set(ALLOWED_ATTRIBUTE_KEYS)

    def test_every_enum_attribute_declares_a_non_empty_closed_value_set(self):
        enums = {
            key: spec for key, spec in ALLOWED_ATTRIBUTES.items() if spec.kind is AttributeKind.ENUM
        }
        assert enums, "the manifest should declare at least one closed enum"
        assert all(spec.values for spec in enums.values())

    def test_no_attribute_is_declared_as_free_text(self):
        """There is deliberately no free-text kind. If one appears, this fails."""
        assert not hasattr(AttributeKind, "TEXT")
        assert not hasattr(AttributeKind, "FREEFORM")


class TestValueShapesAreEnforced:
    def test_the_shipped_refinement_event_passes_its_own_shape_check(self):
        enforce_value_shapes(to_otlp_attributes(_refinement_event()))

    def test_a_value_outside_a_closed_enum_is_rejected(self):
        attributes = to_otlp_attributes(_refinement_event())
        attributes["ssf.quality.error_code"] = "asr returned 500: model not loaded"
        with pytest.raises(DisallowedTelemetryValue):
            enforce_value_shapes(attributes)

    def test_a_sentence_in_a_label_slot_is_rejected(self):
        attributes = to_otlp_attributes(_refinement_event())
        attributes["ssf.quality.model_ref"] = "Übersetze folgenden Satz ins Deutsche"
        with pytest.raises(DisallowedTelemetryValue):
            enforce_value_shapes(attributes)

    def test_a_non_numeric_value_in_a_number_slot_is_rejected(self):
        attributes = to_otlp_attributes(_refinement_event())
        attributes["ssf.quality.refinement_latency_ms"] = "quite slow"
        with pytest.raises(DisallowedTelemetryValue):
            enforce_value_shapes(attributes)

    def test_a_transcript_in_a_language_slot_is_rejected(self):
        attributes = to_otlp_attributes(_refinement_event())
        attributes["ssf.quality.source_lang"] = "guten Tag, wie geht es Ihnen"
        with pytest.raises(DisallowedTelemetryValue):
            enforce_value_shapes(attributes)


class TestRefinementAttemptEvent:
    def test_it_maps_exactly_the_expected_attribute_keys(self):
        envelope = {"ssf.quality.event_id", "ssf.quality.schema_version"}
        assert set(to_otlp_attributes(_refinement_event())) == envelope | REFINEMENT_KEYS

    def test_every_mapped_key_is_on_the_allowlist(self):
        assert set(to_otlp_attributes(_refinement_event())) <= ALLOWED_ATTRIBUTE_KEYS

    def test_every_mapped_value_is_a_string(self):
        values = to_otlp_attributes(_refinement_event()).values()
        assert all(isinstance(value, str) for value in values)

    def test_it_is_immutable(self):
        from dataclasses import FrozenInstanceError

        event = _refinement_event()
        with pytest.raises(FrozenInstanceError):
            event.latency_ms = 1

    def test_it_rejects_a_negative_latency(self):
        with pytest.raises(ValueError):
            _refinement_event(latency_ms=-1)

    def test_it_rejects_a_model_reference_that_could_carry_a_sentence(self):
        with pytest.raises(ValueError):
            _refinement_event(model_ref="please translate the following text")

    def test_it_cannot_be_constructed_with_a_content_field(self):
        with pytest.raises(TypeError):
            _refinement_event(source_text="guten Tag")


class TestErrorTaxonomyIsStable:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (200, QualityErrorCode.NONE),
            (503, QualityErrorCode.UPSTREAM_BUSY),
            (504, QualityErrorCode.UPSTREAM_TIMEOUT),
            (500, QualityErrorCode.UPSTREAM_ERROR),
            (400, QualityErrorCode.UPSTREAM_REJECTED),
        ],
    )
    def test_an_upstream_status_maps_to_a_stable_code(self, status, expected):
        assert classify_upstream_status(status) is expected

    @pytest.mark.parametrize(
        ("exception", "expected"),
        [
            (TimeoutError(), QualityErrorCode.UPSTREAM_TIMEOUT),
            (ConnectionError(), QualityErrorCode.UPSTREAM_UNREACHABLE),
            (ValueError("Expecting value"), QualityErrorCode.UPSTREAM_MALFORMED_RESPONSE),
            (RuntimeError("boom"), QualityErrorCode.INTERNAL_ERROR),
        ],
    )
    def test_an_exception_maps_to_a_stable_code(self, exception, expected):
        assert classify_exception(exception) is expected

    def test_classification_never_carries_the_original_message(self):
        code = classify_exception(RuntimeError("ASR said: guten Tag, wie geht es"))
        assert code.value in {member.value for member in QualityErrorCode}
        assert "guten Tag" not in code.value

    def test_classification_never_raises_on_an_unexpected_exception(self):
        class Weird(Exception):
            pass

        assert classify_exception(Weird()) is QualityErrorCode.INTERNAL_ERROR

    def test_every_error_code_is_a_lowercase_token(self):
        for member in QualityErrorCode:
            assert member.value == member.value.lower()
            assert " " not in member.value

    def test_every_pipeline_stage_is_a_lowercase_token(self):
        for member in PipelineStage:
            assert member.value == member.value.lower()
            assert " " not in member.value


class TestTelemetryModeGainsAnEventsValue:
    def test_enabled_is_a_distinct_mode(self):
        assert TelemetryMode.parse("enabled") is TelemetryMode.ENABLED
        assert TelemetryMode.ENABLED is not TelemetryMode.PROBE

    def test_probe_keeps_its_existing_meaning(self):
        assert TelemetryMode.parse("probe") is TelemetryMode.PROBE

    def test_an_unknown_mode_still_falls_back_to_disabled(self):
        assert TelemetryMode.parse("on") is TelemetryMode.DISABLED


class TestTheAdapterIsActuallyTheLastCheckpoint:
    """`__call__` enforced only the key allowlist, while value shapes were
    checked in to_otlp_attributes. Any emitter building its own dict therefore
    shipped an unvalidated value for an allowlisted key -- exactly the
    error_code-carrying-a-raw-message case the manifest exists to prevent."""

    @staticmethod
    def _adapter():
        from unittest.mock import Mock

        from services.api_gateway.quality_telemetry_otlp import OtlpQualityExporter

        provider = Mock()
        provider.get_logger.return_value = Mock()
        return OtlpQualityExporter(provider), provider.get_logger.return_value

    def test_an_allowlisted_key_with_a_raw_message_is_rejected_at_the_wire(self):
        from datetime import datetime, timezone

        adapter, sink = self._adapter()
        smuggled = {
            "ssf.quality.event_id": str(uuid4()),
            "ssf.quality.schema_version": "1",
            "ssf.quality.error_code": "ASR said: guten Tag, wie geht es Ihnen",
        }

        with pytest.raises(DisallowedTelemetryValue):
            adapter("refinement_attempt", smuggled, datetime.now(timezone.utc))

        sink.emit.assert_not_called()

    def test_a_well_formed_event_still_ships(self):
        adapter, sink = self._adapter()
        event = _refinement_event()

        adapter(
            event.event_type.value,
            to_otlp_attributes(event),
            event.emitted_at_utc,
        )

        sink.emit.assert_called_once()


class TestShapePatternsRejectTrailingWhitespaceAndUnicodeDigits:
    """`$` matches before a trailing newline and `\\d` accepts Unicode digits,
    so a guard whose stated purpose is that a label carry no whitespace was
    accepting `gpt-oss:20b\\n`."""

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("ssf.quality.model_ref", "gpt-oss:20b\n"),
            ("ssf.quality.refinement_latency_ms", "123\n"),
            ("ssf.quality.source_lang", "de\n"),
            ("ssf.quality.refinement_latency_ms", "١٢٣"),
        ],
    )
    def test_the_value_is_rejected(self, key, value):
        attributes = to_otlp_attributes(_refinement_event())
        attributes[key] = value
        with pytest.raises(DisallowedTelemetryValue):
            enforce_value_shapes(attributes)
