"""The `translation_message` event: one row per processed message.

This is the spine event -- the denominator every ratio in the dashboards
divides by -- and it is the first one whose emit path sits in the live message
route. Two properties matter more than any field: it can express nothing that
is content, and emitting it can never change what the caller returns.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.quality_telemetry import (
    ALLOWED_ATTRIBUTES,
    ALLOWED_ATTRIBUTE_KEYS,
    AttributeKind,
    InputMode,
    MessageDirection,
    PipelineStage,
    ProbeOutcome,
    QualityErrorCode,
    QualityEventType,
    QualityTelemetry,
    TelemetryMode,
    TerminalOutcome,
    TranslationMessageEvent,
    discard_event,
    to_otlp_attributes,
)

REFERENCE = "a" * 32


def _event(**overrides) -> TranslationMessageEvent:
    fields = dict(
        event_id=uuid4(),
        schema_version=1,
        emitted_at_utc=datetime.now(timezone.utc),
        event_type=QualityEventType.TRANSLATION_MESSAGE,
        session_ref=REFERENCE,
        direction=MessageDirection.CUSTOMER_TO_ADMIN,
        input_mode=InputMode.AUDIO,
        source_lang="de",
        target_lang="en",
        terminal_outcome=TerminalOutcome.SUCCESS,
        failed_stage=PipelineStage.NONE,
        error_code=QualityErrorCode.NONE,
        total_duration_ms=2500,
        asr_duration_ms=900,
        translation_duration_ms=400,
        refinement_duration_ms=300,
        tts_duration_ms=800,
    )
    fields.update(overrides)
    return TranslationMessageEvent(**fields)


class _Recording:
    def __init__(self):
        self.calls = []

    def __call__(self, name, attributes, emitted_at_utc):
        self.calls.append((name, dict(attributes), emitted_at_utc))


def _telemetry(mode=TelemetryMode.ENABLED, exporter=None):
    return QualityTelemetry(
        mode=mode,
        exporter=exporter or discard_event,
        registry=CollectorRegistry(),
    )


class TestTheEventCarriesNoContent:
    def test_every_attribute_is_a_number_an_enum_or_an_opaque_reference(self):
        for key in to_otlp_attributes(_event()):
            assert ALLOWED_ATTRIBUTES[key].kind is not AttributeKind.OPAQUE_REF or (
                key == "ssf.quality.session_ref"
            )
            assert ALLOWED_ATTRIBUTES[key].kind in {
                AttributeKind.UUID,
                AttributeKind.NUMBER,
                AttributeKind.ENUM,
                AttributeKind.LANGUAGE,
                AttributeKind.OPAQUE_REF,
            }

    def test_it_has_no_label_field_at_all(self):
        """LABEL is the only kind whose charset a sentence fragment could fit.

        `refinement_attempt` needs one for the operator-set model name; nothing
        on a message row is operator-set, so the widest kind stays unused here.
        """
        kinds = {ALLOWED_ATTRIBUTES[key].kind for key in to_otlp_attributes(_event())}
        assert AttributeKind.LABEL not in kinds

    def test_a_session_id_is_never_stored_in_the_clear(self):
        attributes = to_otlp_attributes(_event(session_ref=REFERENCE))
        assert "42" not in attributes.values()
        assert attributes["ssf.quality.session_ref"] == REFERENCE

    def test_a_session_reference_of_the_wrong_shape_is_rejected(self):
        with pytest.raises(ValueError):
            _event(session_ref="session-42")


class TestInvariants:
    def test_a_negative_duration_is_rejected(self):
        with pytest.raises(ValueError):
            _event(total_duration_ms=-1)

    @pytest.mark.parametrize(
        "field",
        [
            "asr_duration_ms",
            "translation_duration_ms",
            "refinement_duration_ms",
            "tts_duration_ms",
        ],
    )
    def test_every_stage_duration_is_rejected_when_negative(self, field):
        with pytest.raises(ValueError):
            _event(**{field: -1})

    def test_a_success_cannot_also_name_a_failed_stage(self):
        with pytest.raises(ValueError):
            _event(
                terminal_outcome=TerminalOutcome.SUCCESS, failed_stage=PipelineStage.TTS
            )

    def test_a_success_cannot_also_carry_an_error_code(self):
        with pytest.raises(ValueError):
            _event(
                terminal_outcome=TerminalOutcome.SUCCESS,
                error_code=QualityErrorCode.UPSTREAM_TIMEOUT,
            )

    def test_a_failure_must_say_why(self):
        with pytest.raises(ValueError):
            _event(
                terminal_outcome=TerminalOutcome.FAILURE,
                failed_stage=PipelineStage.TTS,
                error_code=QualityErrorCode.NONE,
            )

    def test_a_well_formed_failure_is_accepted(self):
        event = _event(
            terminal_outcome=TerminalOutcome.FAILURE,
            failed_stage=PipelineStage.TTS,
            error_code=QualityErrorCode.UPSTREAM_ERROR,
        )
        assert to_otlp_attributes(event)["ssf.quality.failed_stage"] == "tts"


class TestTheSixPlacesAgree:
    def test_every_attribute_the_event_emits_is_allowlisted(self):
        assert set(to_otlp_attributes(_event())) <= ALLOWED_ATTRIBUTE_KEYS

    @pytest.mark.parametrize(
        "key",
        [
            "ssf.quality.session_ref",
            "ssf.quality.direction",
            "ssf.quality.input_mode",
            "ssf.quality.terminal_outcome",
            "ssf.quality.failed_stage",
            "ssf.quality.total_duration_ms",
            "ssf.quality.asr_duration_ms",
            "ssf.quality.translation_duration_ms",
            "ssf.quality.refinement_duration_ms",
            "ssf.quality.tts_duration_ms",
        ],
    )
    def test_the_event_emits_each_of_its_declared_fields(self, key):
        assert key in to_otlp_attributes(_event())

    def test_languages_reuse_the_keys_the_refinement_event_already_opened(self):
        attributes = to_otlp_attributes(_event())
        assert attributes["ssf.quality.source_lang"] == "de"
        assert attributes["ssf.quality.target_lang"] == "en"


class TestEmission:
    def test_an_enabled_gateway_emits_the_event(self):
        exporter = _Recording()

        result = _telemetry(exporter=exporter).emit_translation_message(
            session_ref=REFERENCE,
            direction=MessageDirection.ADMIN_TO_CUSTOMER,
            input_mode=InputMode.TEXT,
            source_lang="en",
            target_lang="de",
            terminal_outcome=TerminalOutcome.SUCCESS,
            failed_stage=PipelineStage.NONE,
            error_code=QualityErrorCode.NONE,
            total_duration_ms=1200,
            asr_duration_ms=0,
            translation_duration_ms=400,
            refinement_duration_ms=0,
            tts_duration_ms=700,
        )

        assert result.outcome is ProbeOutcome.EMITTED
        assert exporter.calls[0][0] == QualityEventType.TRANSLATION_MESSAGE.value

    @pytest.mark.parametrize("mode", [TelemetryMode.DISABLED, TelemetryMode.PROBE])
    def test_probe_mode_stays_a_transport_check(self, mode):
        exporter = _Recording()

        result = _telemetry(mode=mode, exporter=exporter).emit_translation_message(
            session_ref=REFERENCE,
            direction=MessageDirection.ADMIN_TO_CUSTOMER,
            input_mode=InputMode.TEXT,
            source_lang="en",
            target_lang="de",
            terminal_outcome=TerminalOutcome.SUCCESS,
            failed_stage=PipelineStage.NONE,
            error_code=QualityErrorCode.NONE,
            total_duration_ms=1200,
            asr_duration_ms=0,
            translation_duration_ms=400,
            refinement_duration_ms=0,
            tts_duration_ms=700,
        )

        assert result.outcome is ProbeOutcome.DISABLED
        assert exporter.calls == []

    def test_hostile_values_are_coerced_rather_than_dropping_the_row(self):
        """A missing row makes the denominator wrong for every ratio built on
        it, which is worse than an imprecise label."""
        exporter = _Recording()

        result = _telemetry(exporter=exporter).emit_translation_message(
            session_ref="not a reference",
            direction=MessageDirection.ADMIN_TO_CUSTOMER,
            input_mode=InputMode.TEXT,
            source_lang="Deutsch, bitte",
            target_lang="en",
            terminal_outcome=TerminalOutcome.SUCCESS,
            failed_stage=PipelineStage.NONE,
            error_code=QualityErrorCode.NONE,
            total_duration_ms=-5,
            asr_duration_ms=0,
            translation_duration_ms=400,
            refinement_duration_ms=0,
            tts_duration_ms=700,
        )

        assert result.outcome is ProbeOutcome.EMITTED
        attributes = exporter.calls[0][1]
        assert attributes["ssf.quality.source_lang"] == "und"
        assert attributes["ssf.quality.total_duration_ms"] == "0"
        assert "not a reference" not in attributes.values()

    def test_an_export_failure_never_reaches_the_caller(self):
        def explode(name, attributes, emitted_at_utc):
            raise RuntimeError("ClickHouse is gone")

        result = _telemetry(exporter=explode).emit_translation_message(
            session_ref=REFERENCE,
            direction=MessageDirection.ADMIN_TO_CUSTOMER,
            input_mode=InputMode.TEXT,
            source_lang="en",
            target_lang="de",
            terminal_outcome=TerminalOutcome.FAILURE,
            failed_stage=PipelineStage.TTS,
            error_code=QualityErrorCode.UPSTREAM_ERROR,
            total_duration_ms=1200,
            asr_duration_ms=0,
            translation_duration_ms=400,
            refinement_duration_ms=0,
            tts_duration_ms=700,
        )

        assert result.outcome is ProbeOutcome.EXPORT_FAILED
