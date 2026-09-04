"""One request, one row -- assembled across every exit the route has.

A message request leaves through eight different places: two success returns,
an admission 503, an upstream 503, two pipeline failures, a validation 4xx and
an unexpected 500. Emitting at each of them would duplicate the row on some
paths and miss it on others as the route changes. The recorder is filled in as
the request proceeds and emitted once, from the `finally` the route already has.
"""

import pytest

from services.api_gateway.message_telemetry import MessageTelemetryRecorder
from services.api_gateway.quality_telemetry import (
    InputMode,
    MessageDirection,
    PipelineStage,
    QualityErrorCode,
    TerminalOutcome,
)
from services.api_gateway.session_manager import ClientType


class _Spy:
    """Stands in for QualityTelemetry, recording what it was asked to emit."""

    def __init__(self, explode: bool = False):
        self.calls = []
        self._explode = explode

    def emit_translation_message(self, **kwargs):
        if self._explode:
            raise RuntimeError("ClickHouse is gone")
        self.calls.append(kwargs)


def _debug(**overrides) -> dict:
    debug = {
        "failed_stage": PipelineStage.NONE.value,
        "error_code": QualityErrorCode.NONE.value,
        "steps": [
            {"step": "ASR", "output": "a transcript", "duration_ms": 900},
            {"step": "Translation", "input": {"text": "source"}, "duration_ms": 400},
            {"step": "LLM_Refinement", "output": "refined", "duration_ms": 300},
            {"step": "TTS", "input": {"text": "spoken"}, "duration_ms": 800},
        ],
    }
    debug.update(overrides)
    return debug


def _armed(input_mode=InputMode.AUDIO) -> MessageTelemetryRecorder:
    recorder = MessageTelemetryRecorder(session_id="42", start_time=0.0)
    recorder.arm(input_mode)
    recorder.record_request(
        client_type=ClientType.CUSTOMER, source_lang="de", target_lang="en"
    )
    return recorder


def _emit(recorder) -> dict:
    spy = _Spy()
    recorder.emit(spy)
    assert spy.calls, "nothing was emitted"
    return spy.calls[0]


class TestArming:
    def test_a_request_that_never_became_a_message_emits_nothing(self):
        """A 404 for an unknown session is not a message that failed.

        Counting it would put requests the system never accepted into the
        denominator of every success ratio.
        """
        spy = _Spy()

        MessageTelemetryRecorder(session_id="42", start_time=0.0).emit(spy)

        assert spy.calls == []

    def test_an_armed_request_emits_even_if_nothing_else_was_recorded(self):
        recorder = MessageTelemetryRecorder(session_id="42", start_time=0.0)
        recorder.arm(InputMode.TEXT)

        assert _emit(recorder)["input_mode"] is InputMode.TEXT

    def test_emitting_twice_still_produces_one_row(self):
        spy = _Spy()
        recorder = _armed()

        recorder.emit(spy)
        recorder.emit(spy)

        assert len(spy.calls) == 1


class TestDirection:
    @pytest.mark.parametrize(
        "client_type,expected",
        [
            (ClientType.CUSTOMER, MessageDirection.CUSTOMER_TO_ADMIN),
            (ClientType.ADMIN, MessageDirection.ADMIN_TO_CUSTOMER),
        ],
    )
    def test_the_sending_client_decides_the_direction(self, client_type, expected):
        recorder = MessageTelemetryRecorder(session_id="42", start_time=0.0)
        recorder.arm(InputMode.TEXT)
        recorder.record_request(
            client_type=client_type, source_lang="de", target_lang="en"
        )

        assert _emit(recorder)["direction"] is expected

    def test_an_unparsed_request_has_no_direction_rather_than_a_guessed_one(self):
        recorder = MessageTelemetryRecorder(session_id="42", start_time=0.0)
        recorder.arm(InputMode.AUDIO)

        assert _emit(recorder)["direction"] is MessageDirection.UNKNOWN


class TestPipelineResult:
    def test_stage_durations_come_from_the_steps(self):
        recorder = _armed()
        recorder.record_pipeline_result({"error": False, "debug": _debug()})

        emitted = _emit(recorder)

        assert emitted["asr_duration_ms"] == 900
        assert emitted["translation_duration_ms"] == 400
        assert emitted["refinement_duration_ms"] == 300
        assert emitted["tts_duration_ms"] == 800

    def test_a_successful_pipeline_records_a_success(self):
        recorder = _armed()
        recorder.record_pipeline_result({"error": False, "debug": _debug()})

        emitted = _emit(recorder)

        assert emitted["terminal_outcome"] is TerminalOutcome.SUCCESS
        assert emitted["failed_stage"] is PipelineStage.NONE
        assert emitted["error_code"] is QualityErrorCode.NONE

    def test_a_failed_pipeline_keeps_the_stage_and_code_the_pipeline_recorded(self):
        recorder = _armed()
        recorder.record_pipeline_result(
            {
                "error": True,
                "debug": _debug(
                    failed_stage=PipelineStage.TTS.value,
                    error_code=QualityErrorCode.UPSTREAM_TIMEOUT.value,
                ),
            }
        )

        emitted = _emit(recorder)

        assert emitted["terminal_outcome"] is TerminalOutcome.FAILURE
        assert emitted["failed_stage"] is PipelineStage.TTS
        assert emitted["error_code"] is QualityErrorCode.UPSTREAM_TIMEOUT

    def test_an_unrecognised_stage_or_code_becomes_unknown_not_a_crash(self):
        recorder = _armed()
        recorder.record_pipeline_result(
            {"error": True, "debug": {"failed_stage": "banana", "error_code": "🙂"}}
        )

        emitted = _emit(recorder)

        assert emitted["failed_stage"] is PipelineStage.UNKNOWN
        assert emitted["error_code"] is QualityErrorCode.UNKNOWN

    def test_a_result_with_no_debug_at_all_is_survivable(self):
        recorder = _armed()
        recorder.record_pipeline_result({"error": True})

        assert _emit(recorder)["terminal_outcome"] is TerminalOutcome.FAILURE


class TestNothingContentBearingIsRead:
    def test_only_the_step_name_and_its_duration_are_read(self):
        """`debug["steps"]` carries the transcript, the source text and the raw
        upstream error. The recorder must touch two keys and no others."""
        seen = []

        class _Watching(dict):
            def get(self, key, default=None):
                seen.append(key)
                return super().get(key, default)

        recorder = _armed()
        steps = [_Watching(step="ASR", output="a transcript", duration_ms=900)]
        recorder.record_pipeline_result({"error": False, "debug": {"steps": steps}})
        recorder.emit(_Spy())

        assert set(seen) <= {"step", "duration_ms"}

    def test_no_emitted_value_is_a_string_from_the_pipeline(self):
        recorder = _armed()
        recorder.record_pipeline_result(
            {
                "error": True,
                "error_msg": "ASR-Fehler: HTTPConnectionPool(host='asr', port=8001)",
                "asr_text": "a transcript",
                "translation_text": "eine Abschrift",
                "debug": _debug(
                    failed_stage=PipelineStage.ASR.value,
                    error_code=QualityErrorCode.UPSTREAM_UNREACHABLE.value,
                    error="ASR-Fehler: HTTPConnectionPool(host='asr', port=8001)",
                ),
            }
        )

        values = [str(v) for v in _emit(recorder).values()]

        assert not any("asr" in v and "8001" in v for v in values)
        assert "a transcript" not in values

    def test_the_session_id_is_never_emitted_in_the_clear(self):
        emitted = _emit(_armed())

        assert emitted["session_ref"] != "42"
        assert len(emitted["session_ref"]) == 32


class TestHttpFailures:
    def test_admission_rejection_is_its_own_stage(self):
        recorder = _armed()
        recorder.record_http_failure(503)

        emitted = _emit(recorder)

        assert emitted["failed_stage"] is PipelineStage.ADMISSION
        assert emitted["error_code"] is QualityErrorCode.UPSTREAM_BUSY

    @pytest.mark.parametrize(
        "input_mode,expected",
        [
            (InputMode.AUDIO, QualityErrorCode.AUDIO_VALIDATION_FAILED),
            (InputMode.TEXT, QualityErrorCode.TEXT_VALIDATION_FAILED),
        ],
    )
    def test_a_rejected_request_names_the_validation_that_rejected_it(
        self, input_mode, expected
    ):
        recorder = _armed(input_mode)
        recorder.record_http_failure(400)

        emitted = _emit(recorder)

        assert emitted["failed_stage"] is PipelineStage.VALIDATION
        assert emitted["error_code"] is expected

    def test_the_pipelines_own_reason_wins_over_the_http_status(self):
        """`_raise_if_upstream_busy` turns a pipeline failure into a 503 after
        the pipeline has already said which stage shed the load."""
        recorder = _armed()
        recorder.record_pipeline_result(
            {
                "error": True,
                "debug": _debug(
                    failed_stage=PipelineStage.ASR.value,
                    error_code=QualityErrorCode.UPSTREAM_BUSY.value,
                ),
            }
        )
        recorder.record_http_failure(503)

        assert _emit(recorder)["failed_stage"] is PipelineStage.ASR

    def test_a_failure_after_a_successful_pipeline_is_a_delivery_failure(self):
        recorder = _armed()
        recorder.record_pipeline_result({"error": False, "debug": _debug()})
        recorder.record_http_failure(500)

        emitted = _emit(recorder)

        assert emitted["terminal_outcome"] is TerminalOutcome.FAILURE
        assert emitted["failed_stage"] is PipelineStage.DELIVERY
        assert emitted["error_code"] is QualityErrorCode.INTERNAL_ERROR


class TestItNeverChangesTheCallersOutcome:
    def test_an_exploding_emitter_does_not_propagate(self):
        _armed().emit(_Spy(explode=True))

    def test_a_missing_telemetry_object_does_not_propagate(self):
        _armed().emit(None)

    def test_a_telemetry_object_without_the_method_does_not_propagate(self):
        _armed().emit(object())

    def test_a_hostile_pipeline_result_does_not_propagate(self):
        recorder = _armed()
        recorder.record_pipeline_result({"debug": {"steps": "not a list"}})
        recorder.record_pipeline_result(None)
        recorder.emit(_Spy())
