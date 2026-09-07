"""The first real pipeline event: one row per shadow refinement attempt.

`ShadowComparisonRefiner._run_candidate` already measures candidate latency and
throws it away into a log line. This is the pilot for the six-places workflow --
small enough to get right, and every field a number or a closed enum, so it
carries no privacy risk by construction.

Task 2.4 applies here too: the refiner must behave identically whether telemetry
is off, attached, or attached to something broken.
"""

from unittest.mock import Mock

import pytest

from prometheus_client import CollectorRegistry

from services.api_gateway.quality_telemetry import (
    ProbeOutcome,
    QualityErrorCode,
    QualityTelemetry,
    RefinerRole,
    RefinementOutcomeCode,
    TelemetryMode,
)
from services.api_gateway.translation_refiner import (
    RefinementOutcome,
    ShadowComparisonRefiner,
)


class _RecordingExporter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, event_name, attributes, emitted_at_utc) -> None:
        self.calls.append((event_name, dict(attributes), emitted_at_utc))


def _telemetry(mode: TelemetryMode, exporter=None, registry=None) -> QualityTelemetry:
    return QualityTelemetry(
        mode=mode,
        exporter=exporter or _RecordingExporter(),
        registry=registry or CollectorRegistry(),
    )


def _refiner(monkeypatch, telemetry, *, outcome: RefinementOutcome):
    refiner = ShadowComparisonRefiner(
        "http://ollama:11434",
        "gpt-oss:20b",
        4.0,
        0.7,
        1,
        False,
        candidate_model="phi4-mini",
        queue_limit=4,
    )
    refiner.attach_quality_telemetry(telemetry)

    # The candidate refiner is constructed inside _run_candidate; stub the
    # class it builds so no HTTP happens.
    class _StubCandidate:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def _perform_refinement(self, *args, **kwargs) -> RefinementOutcome:
            return outcome

    monkeypatch.setattr(
        "services.api_gateway.translation_refiner.OllamaTranslationRefiner",
        _StubCandidate,
    )
    refiner.pending = 1
    return refiner


def _success() -> RefinementOutcome:
    return RefinementOutcome(text="Hallo Welt", changed=True, latency_ms=340.0)


class TestTheModeGatesPipelineEvents:
    def test_enabled_emits_one_refinement_attempt(self, monkeypatch):
        exporter = _RecordingExporter()
        refiner = _refiner(
            monkeypatch, _telemetry(TelemetryMode.ENABLED, exporter), outcome=_success()
        )

        refiner._run_candidate("Hello world", "en", "de")

        assert len(exporter.calls) == 1
        event_name, attributes, _ = exporter.calls[0]
        assert event_name == "refinement_attempt"
        assert attributes["ssf.quality.refiner_role"] == RefinerRole.CANDIDATE.value
        assert attributes["ssf.quality.model_ref"] == "phi4-mini"
        assert attributes["ssf.quality.refinement_outcome"] == "success"
        assert attributes["ssf.quality.refinement_latency_ms"] == "340"
        assert attributes["ssf.quality.refinement_changed"] == "true"
        assert attributes["ssf.quality.source_lang"] == "en"
        assert attributes["ssf.quality.target_lang"] == "de"
        assert attributes["ssf.quality.error_code"] == QualityErrorCode.NONE.value

    def test_probe_mode_emits_no_pipeline_events(self, monkeypatch):
        """PROBE stays a pure transport check, so dev does not start emitting
        production volume merely by upgrading."""
        exporter = _RecordingExporter()
        refiner = _refiner(
            monkeypatch, _telemetry(TelemetryMode.PROBE, exporter), outcome=_success()
        )

        refiner._run_candidate("Hello world", "en", "de")

        assert exporter.calls == []

    def test_disabled_emits_nothing(self, monkeypatch):
        exporter = _RecordingExporter()
        refiner = _refiner(
            monkeypatch, _telemetry(TelemetryMode.DISABLED, exporter), outcome=_success()
        )

        refiner._run_candidate("Hello world", "en", "de")

        assert exporter.calls == []


class TestTheEventDescribesWhatHappened:
    def test_a_failed_candidate_is_classified_not_quoted(self, monkeypatch):
        """Asserts the specific code, not merely that it differs from `none`.

        The weaker assertion passed while every failure collapsed to
        `internal_error`, which is exactly the bug it should have caught.
        """
        exporter = _RecordingExporter()
        outcome = RefinementOutcome(
            text="Hallo",
            changed=False,
            latency_ms=12.0,
            error="connection refused",
            error_code=QualityErrorCode.UPSTREAM_UNREACHABLE,
        )
        refiner = _refiner(
            monkeypatch, _telemetry(TelemetryMode.ENABLED, exporter), outcome=outcome
        )

        refiner._run_candidate("Hello world", "en", "de")

        _, attributes, _ = exporter.calls[0]
        assert attributes["ssf.quality.refinement_outcome"] == "error"
        assert attributes["ssf.quality.error_code"] == QualityErrorCode.UPSTREAM_UNREACHABLE.value
        assert "connection refused" not in str(attributes)

    def test_keyword_call_sites_still_yield_the_languages(self, monkeypatch):
        exporter = _RecordingExporter()
        refiner = _refiner(
            monkeypatch, _telemetry(TelemetryMode.ENABLED, exporter), outcome=_success()
        )

        refiner._run_candidate("Hello", source_lang="fr", target_lang="ar")

        _, attributes, _ = exporter.calls[0]
        assert attributes["ssf.quality.source_lang"] == "fr"
        assert attributes["ssf.quality.target_lang"] == "ar"

    def test_an_unusable_language_is_recorded_as_undetermined(self, monkeypatch):
        """Better a row marked `und` than no row: dropping the event would make
        the denominator wrong for every ratio built on it."""
        exporter = _RecordingExporter()
        refiner = _refiner(
            monkeypatch, _telemetry(TelemetryMode.ENABLED, exporter), outcome=_success()
        )

        refiner._run_candidate("Hello", "not a language code", "de")

        _, attributes, _ = exporter.calls[0]
        assert attributes["ssf.quality.source_lang"] == "und"

    def test_a_missing_latency_is_recorded_as_zero(self, monkeypatch):
        exporter = _RecordingExporter()
        outcome = RefinementOutcome(text="Hallo", changed=False, latency_ms=None)
        refiner = _refiner(
            monkeypatch, _telemetry(TelemetryMode.ENABLED, exporter), outcome=outcome
        )

        refiner._run_candidate("Hello", "en", "de")

        _, attributes, _ = exporter.calls[0]
        assert attributes["ssf.quality.refinement_latency_ms"] == "0"


class TestTelemetryNeverChangesTheRefiner:
    """Task 2.4, at the one call site that exists so far."""

    def test_an_exploding_exporter_does_not_break_the_candidate_run(self, monkeypatch):
        def explode(*_args, **_kwargs):
            raise RuntimeError("clickhouse is gone")

        refiner = _refiner(
            monkeypatch, _telemetry(TelemetryMode.ENABLED, explode), outcome=_success()
        )

        refiner._run_candidate("Hello world", "en", "de")

        assert refiner.pending == 0, "the queue slot must still be released"

    def test_a_refiner_with_no_telemetry_attached_still_runs(self, monkeypatch):
        refiner = _refiner(monkeypatch, _telemetry(TelemetryMode.ENABLED), outcome=_success())
        refiner.attach_quality_telemetry(None)

        refiner._run_candidate("Hello world", "en", "de")

        assert refiner.pending == 0

    def test_a_broken_telemetry_object_does_not_break_the_candidate_run(self, monkeypatch):
        broken = Mock()
        broken.emit_refinement_attempt.side_effect = RuntimeError("boom")
        refiner = _refiner(monkeypatch, broken, outcome=_success())

        refiner._run_candidate("Hello world", "en", "de")

        assert refiner.pending == 0

    def test_the_outcome_is_counted_for_the_operator(self, monkeypatch):
        registry = CollectorRegistry()
        telemetry = _telemetry(TelemetryMode.ENABLED, registry=registry)
        refiner = _refiner(monkeypatch, telemetry, outcome=_success())

        refiner._run_candidate("Hello world", "en", "de")

        emitted = registry.get_sample_value(
            "ssf_quality_telemetry_events_total",
            {"outcome": ProbeOutcome.EMITTED.value},
        )
        assert emitted == 1.0


class TestThePrimaryPathEmitsToo:
    """Production runs LLM_REFINEMENT_MODE=primary_only, so a refinement event
    reachable only from the shadow candidate is a dashboard that is empty
    exactly where it matters. RefinerRole.PRIMARY must be reachable."""

    @staticmethod
    def _primary(monkeypatch, telemetry, *, payload=None, raises=None):
        from services.api_gateway.translation_refiner import OllamaTranslationRefiner

        refiner = OllamaTranslationRefiner("http://ollama:11434", "gpt-oss:20b", 4.0, 0.7, 1, False)
        refiner.attach_quality_telemetry(telemetry)

        def post(*_args, **_kwargs):
            if raises is not None:
                raise raises
            response = Mock()
            response.status_code = 200
            response.raise_for_status.return_value = None
            response.json.return_value = payload
            return response

        monkeypatch.setattr("services.api_gateway.translation_refiner.requests.post", post)
        return refiner

    def test_a_primary_refinement_emits_with_the_primary_role(self, monkeypatch):
        exporter = _RecordingExporter()
        refiner = self._primary(
            monkeypatch,
            _telemetry(TelemetryMode.ENABLED, exporter),
            payload={"response": "Hallo Welt"},
        )

        refiner.refine("Hello world", "en", "de")

        assert len(exporter.calls) == 1
        _, attributes, _ = exporter.calls[0]
        assert attributes["ssf.quality.refiner_role"] == RefinerRole.PRIMARY.value
        assert attributes["ssf.quality.model_ref"] == "gpt-oss:20b"
        assert attributes["ssf.quality.error_code"] == QualityErrorCode.NONE.value

    def test_a_primary_timeout_records_upstream_timeout_not_internal_error(self, monkeypatch):
        from requests import exceptions

        exporter = _RecordingExporter()
        refiner = self._primary(
            monkeypatch,
            _telemetry(TelemetryMode.ENABLED, exporter),
            raises=exceptions.ReadTimeout("read timed out"),
        )

        refiner.refine("Hello world", "en", "de")

        _, attributes, _ = exporter.calls[0]
        assert attributes["ssf.quality.error_code"] == QualityErrorCode.UPSTREAM_TIMEOUT.value
        assert attributes["ssf.quality.refinement_outcome"] == "error"

    def test_a_noop_refiner_emits_nothing(self, monkeypatch):
        """No refinement happened, so there is no attempt to record."""
        from services.api_gateway.translation_refiner import NoOpTranslationRefiner

        exporter = _RecordingExporter()
        refiner = NoOpTranslationRefiner()
        refiner.attach_quality_telemetry(_telemetry(TelemetryMode.ENABLED, exporter))

        refiner.refine("Hello world", "en", "de")

        assert exporter.calls == []


class TestShadowQueueOverloadIsVisible:
    """`skipped_overload` and `submission_failed` are reserved enum members and
    were unreachable: the candidate never runs, so nothing emitted them."""

    @staticmethod
    def _shadow(monkeypatch, telemetry, *, pending):
        refiner = ShadowComparisonRefiner(
            "http://ollama:11434",
            "gpt-oss:20b",
            4.0,
            0.7,
            1,
            False,
            candidate_model="phi4-mini",
            queue_limit=1,
        )
        refiner.attach_quality_telemetry(telemetry)
        refiner.pending = pending

        def post(*_args, **_kwargs):
            response = Mock()
            response.status_code = 200
            response.raise_for_status.return_value = None
            response.json.return_value = {"response": "Hallo Welt"}
            return response

        monkeypatch.setattr("services.api_gateway.translation_refiner.requests.post", post)
        return refiner

    def test_a_skipped_candidate_is_recorded(self, monkeypatch):
        exporter = _RecordingExporter()
        refiner = self._shadow(monkeypatch, _telemetry(TelemetryMode.ENABLED, exporter), pending=1)

        outcome = refiner.refine("Hello world", "en", "de")

        assert outcome.candidate_status == "skipped_overload"
        roles = [a["ssf.quality.refiner_role"] for _, a, _ in exporter.calls]
        outcomes = [a["ssf.quality.refinement_outcome"] for _, a, _ in exporter.calls]
        assert RefinerRole.PRIMARY.value in roles
        assert RefinementOutcomeCode.SKIPPED_OVERLOAD.value in outcomes

    def test_a_skipped_candidate_reports_the_candidate_model(self, monkeypatch):
        exporter = _RecordingExporter()
        refiner = self._shadow(monkeypatch, _telemetry(TelemetryMode.ENABLED, exporter), pending=1)

        refiner.refine("Hello world", "en", "de")

        skipped = [
            a
            for _, a, _ in exporter.calls
            if a["ssf.quality.refinement_outcome"] == RefinementOutcomeCode.SKIPPED_OVERLOAD.value
        ]
        assert skipped[0]["ssf.quality.model_ref"] == "phi4-mini"
        assert skipped[0]["ssf.quality.error_code"] == QualityErrorCode.REFINEMENT_OVERLOADED.value
