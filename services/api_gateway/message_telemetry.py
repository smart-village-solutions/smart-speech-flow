"""Assembles one `translation_message` row across a request's many exits.

The message route leaves through eight places: two success returns, an
admission 503, an upstream 503, two pipeline failures, a validation 4xx and an
unexpected 500. Emitting at each would duplicate the row on some paths and miss
it on others the next time the route changes, so the recorder is filled in as
the request proceeds and emitted once, from the `finally` the route already has.

It is also the boundary that keeps content out of telemetry. ``debug["steps"]``
holds the transcript, the source text and the raw upstream error; this module
reads two keys from each step -- its name and its duration -- and nothing else,
and every value it passes on is an int or a member of a closed enum.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final, Mapping, Optional

from .quality_telemetry import (
    InputMode,
    MessageDirection,
    PipelineStage,
    QualityErrorCode,
    TerminalOutcome,
)
from .session_manager import ClientType
from .session_pseudonym import session_ref

logger = logging.getLogger(__name__)

# The pipeline's own step names, which are stable strings in debug_info.
_STEP_DURATION_FIELDS: Final[Mapping[str, str]] = {
    "ASR": "asr_duration_ms",
    "Translation": "translation_duration_ms",
    "LLM_Refinement": "refinement_duration_ms",
    "TTS": "tts_duration_ms",
}

_DIRECTION_BY_SENDER: Final[Mapping[ClientType, MessageDirection]] = {
    ClientType.CUSTOMER: MessageDirection.CUSTOMER_TO_ADMIN,
    ClientType.ADMIN: MessageDirection.ADMIN_TO_CUSTOMER,
}

_VALIDATION_CODE_BY_MODE: Final[Mapping[InputMode, QualityErrorCode]] = {
    InputMode.AUDIO: QualityErrorCode.AUDIO_VALIDATION_FAILED,
    InputMode.TEXT: QualityErrorCode.TEXT_VALIDATION_FAILED,
}


def _member(enum_class, value, fallback):
    """Never raise on a token the pipeline wrote but this enum does not know."""
    try:
        return enum_class(value)
    except (ValueError, TypeError):
        return fallback


class MessageTelemetryRecorder:
    """Accumulates one row. Every method is safe to call in any order."""

    def __init__(self, *, session_id: Any, start_time: float) -> None:
        self._session_id = session_id
        self._start_time = start_time
        self._armed = False
        self._emitted = False
        self._pipeline_ran = False
        self._input_mode = InputMode.UNKNOWN
        self._direction = MessageDirection.UNKNOWN
        self._source_lang = ""
        self._target_lang = ""
        self._outcome = TerminalOutcome.SUCCESS
        self._failed_stage = PipelineStage.NONE
        self._error_code = QualityErrorCode.NONE
        self._durations = {name: 0 for name in _STEP_DURATION_FIELDS.values()}

    def arm(self, input_mode: InputMode) -> None:
        """Mark the request as a message, from the content-type dispatch on.

        A request rejected before this -- an unknown session, an inactive one,
        an unsupported content type -- never became a message, and counting it
        would put requests the gateway declined into the denominator of every
        success ratio built on this event.
        """
        self._armed = True
        self._input_mode = input_mode

    def record_request(
        self, *, client_type: Any, source_lang: str, target_lang: str
    ) -> None:
        self._direction = _DIRECTION_BY_SENDER.get(
            client_type, MessageDirection.UNKNOWN
        )
        self._source_lang = source_lang
        self._target_lang = target_lang

    def record_pipeline_result(self, result: Optional[Mapping[str, Any]]) -> None:
        """Take the outcome and the reason from the pipeline, never from steps.

        Each branch is fully determined here rather than repaired afterwards:
        the two fields are only meaningful as a pair, and a partial assignment
        produces a combination `TranslationMessageEvent` rejects -- which loses
        the row silently, and a missing row makes the denominator wrong for
        every ratio built on it.
        """
        if not isinstance(result, Mapping):
            return
        self._pipeline_ran = True
        debug = result.get("debug")
        if not isinstance(debug, Mapping):
            debug = {}
        self._record_step_durations(debug.get("steps"))

        if not result.get("error"):
            # A success cannot name a failure, whatever the pipeline wrote.
            self._outcome = TerminalOutcome.SUCCESS
            self._failed_stage = PipelineStage.NONE
            self._error_code = QualityErrorCode.NONE
            return

        self._outcome = TerminalOutcome.FAILURE
        self._failed_stage = _member(
            PipelineStage, debug.get("failed_stage"), PipelineStage.UNKNOWN
        )
        code = _member(
            QualityErrorCode, debug.get("error_code"), QualityErrorCode.UNKNOWN
        )
        # `none` on a row flagged as an error is not a classification. It has
        # been reachable before -- a TTS reply of 200 with a JSON error body
        # classified off its status code alone -- and the event's invariant
        # would reject the row rather than store the contradiction.
        if code is QualityErrorCode.NONE:
            code = QualityErrorCode.UNKNOWN
        self._error_code = code

    def record_http_failure(self, status_code: int) -> None:
        """Classify an exit the pipeline did not reach, or did not explain.

        A reason the pipeline recorded always wins: by the time
        `_raise_if_upstream_busy` turns a shed load into a 503, the pipeline has
        already named the stage that shed it, which the status code cannot.
        """
        if self._outcome is TerminalOutcome.FAILURE:
            return
        self._outcome = TerminalOutcome.FAILURE
        if self._pipeline_ran:
            self._failed_stage = PipelineStage.DELIVERY
            self._error_code = QualityErrorCode.INTERNAL_ERROR
        elif status_code == 503:
            self._failed_stage = PipelineStage.ADMISSION
            self._error_code = QualityErrorCode.UPSTREAM_BUSY
        elif 400 <= status_code < 500:
            self._failed_stage = PipelineStage.VALIDATION
            self._error_code = _VALIDATION_CODE_BY_MODE.get(
                self._input_mode, QualityErrorCode.UNKNOWN
            )
        else:
            self._failed_stage = PipelineStage.UNKNOWN
            self._error_code = QualityErrorCode.INTERNAL_ERROR

    def emit(self, telemetry: Any) -> None:
        """Emit at most one row, and never raise.

        Telemetry is optional; the gateway is not. This runs in the route's
        `finally`, so an exception here would replace whatever the request was
        actually about to return.
        """
        if not self._armed or self._emitted:
            return
        self._emitted = True
        emit = getattr(telemetry, "emit_translation_message", None)
        if emit is None:
            return
        try:
            emit(
                session_ref=session_ref(self._session_id),
                direction=self._direction,
                input_mode=self._input_mode,
                source_lang=self._source_lang,
                target_lang=self._target_lang,
                terminal_outcome=self._outcome,
                failed_stage=self._failed_stage,
                error_code=self._error_code,
                total_duration_ms=self._elapsed_ms(),
                **self._durations,
            )
        except Exception:  # telemetry must never reach the caller
            logger.warning("Message quality telemetry failed", exc_info=True)

    def _elapsed_ms(self) -> int:
        return max(0, int((time.perf_counter() - self._start_time) * 1000))

    def _record_step_durations(self, steps: Any) -> None:
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            field = _STEP_DURATION_FIELDS.get(step.get("step"))
            if field is None:
                continue
            duration = step.get("duration_ms")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                # Last wins: a stage that appended both a failure step and a
                # success step reports the one it actually ended on.
                self._durations[field] = max(0, int(duration))
