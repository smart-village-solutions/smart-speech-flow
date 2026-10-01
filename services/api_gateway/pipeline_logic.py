import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psutil
import requests

from .audio_processing import AudioValidator
from .circuit_breaker import CircuitBreakerOpenError
from .quality_telemetry import (
    PipelineStage,
    QualityErrorCode,
    classify_exception,
    classify_upstream_status,
)
from .speech_services import AUDIO_WAV_MIME, SpeechServices
from .translation_refiner import BaseTranslationRefiner, RefinementOutcome

# Marks a pipeline failure the client may usefully retry, so the routes can
# answer 503 with a Retry-After instead of a permanent-looking error.
UPSTREAM_BUSY_ERROR_CODE = "SYSTEM_BUSY"
# Only used when a shedding service sent no parseable Retry-After of its own.
DEFAULT_UPSTREAM_RETRY_AFTER_SECONDS = 5
# Marks a recording in which ASR heard nothing, so the message route can answer
# 422 instead of translating an empty string.
NO_SPEECH_ERROR_CODE = "NO_SPEECH_RECOGNIZED"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# === Text Validation Configuration ===


class TextValidationError(Exception):
    """Custom exception for text validation errors"""

    pass


@dataclass
class TextSpecs:
    """Text specification requirements"""

    MAX_LENGTH: int = 500  # Maximum 500 characters
    MIN_LENGTH: int = 1  # Minimum 1 character
    ALLOWED_ENCODINGS: Optional[List[str]] = None  # UTF-8 primary

    def __post_init__(self):
        if self.ALLOWED_ENCODINGS is None:
            self.ALLOWED_ENCODINGS = ["utf-8"]


@dataclass
class TextValidationResult:
    """Result of text validation"""

    is_valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    # Text properties
    length: Optional[int] = None
    encoding: Optional[str] = None
    contains_spam: Optional[bool] = None
    contains_harmful_content: Optional[bool] = None
    validation_time_ms: Optional[int] = None
    normalized_text: Optional[str] = None


def _collect_system_metrics() -> Dict[str, float]:
    return {
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
    }


def _record_pipeline_duration(debug_info: Dict[str, Any], start_total: float) -> None:
    """Record how long the pipeline ran, from a single clock sample.

    Both duration fields used to be read from two separate ``perf_counter()``
    calls, so they disagreed; and the failure path recorded only the seconds
    field, leaving failure rows with no millisecond duration and no completion
    timestamp to compare against a success row.
    """
    elapsed_seconds = time.perf_counter() - start_total
    debug_info["pipeline_completed_at"] = utc_now().isoformat() + "Z"
    debug_info["total_duration_ms"] = int(elapsed_seconds * 1000)
    debug_info["total_duration"] = round(elapsed_seconds, 3)


def _upstream_error_message(response: Any) -> str:
    """Best-effort reason from a failed upstream reply, never raising."""
    try:
        payload = response.json()
        return payload.get("detail") or payload.get("error") or str(payload)
    except Exception:
        return str(getattr(response, "text", ""))


def _mark_pipeline_failure(
    debug_info: Dict[str, Any], start_total: float, error_message: str
) -> None:
    debug_info["error"] = error_message
    _record_pipeline_duration(debug_info, start_total)
    debug_info["system"] = _collect_system_metrics()


_CONTENT_REJECTION_CODES: frozenset = frozenset({"SPAM_DETECTED", "HARMFUL_CONTENT"})


def _classify_tts_failure(response: Any) -> QualityErrorCode:
    """Both arms of the TTS failure condition, not just the status code.

    The branch fires on a bad status *or* a reply that is not audio, and
    ``classify_upstream_status`` maps every 2xx to ``NONE``. Deriving the code
    from the status alone therefore wrote ``error_code: "none"`` onto a result
    whose ``error`` flag was True, for exactly the case the branch's own
    ``tts_resp.json()`` handling exists to cover: a 200 carrying a JSON error
    body. A 2xx that reaches here was rejected on its content type, which is a
    malformed reply.
    """
    code = classify_upstream_status(getattr(response, "status_code", 0))
    if code is QualityErrorCode.NONE:
        return QualityErrorCode.UPSTREAM_MALFORMED_RESPONSE
    return code


def _classify_text_validation(validation_result: Any) -> QualityErrorCode:
    """Separate "we would not translate this" from "this is not usable text".

    Both are validation failures, but only one is a moderation decision, and a
    dashboard that cannot tell them apart reads a spam filter working correctly
    as a broken client.
    """
    if getattr(validation_result, "error_code", None) in _CONTENT_REJECTION_CODES:
        return QualityErrorCode.CONTENT_REJECTED
    return QualityErrorCode.TEXT_VALIDATION_FAILED


def _upstream_retry_after(response: Any) -> int:
    """The upstream's own Retry-After, or a delay short enough to still be useful."""
    headers = getattr(response, "headers", None) or {}
    try:
        return max(1, int(headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return DEFAULT_UPSTREAM_RETRY_AFTER_SECONDS


def _pipeline_error_result(
    *,
    debug_info: Dict[str, Any],
    start_total: float,
    error_message: str,
    failed_stage: PipelineStage,
    error_code: QualityErrorCode,
    asr_text: Optional[str],
    translation_text: Optional[str],
    audio_bytes: Optional[bytes],
    validation_result: Optional[Any] = None,
    upstream_response: Optional[Any] = None,
    retry_after_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Flattens an upstream failure into the pipeline's result shape.

    ``upstream_response`` exists so a 503 keeps its meaning. Since #190 the GPU
    services shed load with a 503 and a Retry-After, which is transient, but
    every failure here otherwise arrives at the routes as one undifferentiated
    ``error`` — reported as 500 on the audio path and 400 on the text path, both
    of which a client reads as permanent.

    ``retry_after_seconds`` marks a failure retryable when there is no upstream
    response to read it from -- an open circuit refuses before a request is
    sent, so there is no reply and no header, but the caller should still be
    told to come back.

    ``failed_stage`` and ``error_code`` are required rather than inferred. The
    only other places that record what went wrong are ``debug["steps"]``, whose
    entries hold the transcript and the source text, and ``error_message``,
    which holds the raw upstream reply — so anything reading them to classify a
    failure would be reading content.
    """
    _mark_pipeline_failure(debug_info, start_total, error_message)
    debug_info["failed_stage"] = failed_stage.value
    debug_info["error_code"] = error_code.value
    result = {
        "error": True,
        "error_msg": error_message,
        "asr_text": asr_text,
        "translation_text": translation_text,
        "audio_bytes": audio_bytes,
        "debug": debug_info,
    }
    if validation_result is not None:
        result["validation_result"] = validation_result
    if retry_after_seconds is not None:
        result["error_code"] = UPSTREAM_BUSY_ERROR_CODE
        result["retry_after_seconds"] = retry_after_seconds
    elif getattr(upstream_response, "status_code", None) == 503:
        result["error_code"] = UPSTREAM_BUSY_ERROR_CODE
        result["retry_after_seconds"] = _upstream_retry_after(upstream_response)
    return result


# Which pipeline stage a breaker belongs to. The breaker names come from
# ServiceHealthManager._setup_default_services and are the same strings the
# /api/health/services route reports.
_STAGE_BY_SERVICE = {
    "asr": PipelineStage.ASR,
    "translation": PipelineStage.TRANSLATION,
    "tts": PipelineStage.TTS,
}


def _circuit_open_result(
    error: CircuitBreakerOpenError,
    *,
    debug_info: Dict[str, Any],
    start_total: float,
    asr_text: Optional[str],
    translation_text: Optional[str],
) -> Dict[str, Any]:
    """Turns a refused call into the pipeline's ordinary retryable failure.

    An open breaker is transient by construction -- it closes again on its own
    -- so it carries the same ``error_code`` and ``retry_after_seconds`` that
    #190's load shedding already uses, and the session routes turn both into a
    503 with a ``Retry-After`` through ``_raise_if_upstream_busy``. The
    telemetry code stays distinct, because a breaker we opened and a service
    politely shedding load are different operational events.

    The work already done is preserved: a transcript that cost six seconds of
    GPU time should not vanish because the next stage was unreachable.
    """
    stage = _STAGE_BY_SERVICE.get(error.service_name, PipelineStage.UNKNOWN)
    debug_info["steps"].append(
        {
            "step": stage.value.upper(),
            "name": error.service_name or stage.value,
            "input": None,
            "output": None,
            "error": str(error),
            "skipped": True,
            "duration": 0.0,
            "duration_ms": 0,
        }
    )
    return _pipeline_error_result(
        debug_info=debug_info,
        start_total=start_total,
        error_message=f"Service '{error.service_name}' unavailable: circuit breaker open",
        failed_stage=stage,
        error_code=QualityErrorCode.UPSTREAM_CIRCUIT_OPEN,
        asr_text=asr_text,
        translation_text=translation_text,
        audio_bytes=None,
        retry_after_seconds=error.retry_after_seconds,
    )


def _append_text_validation_step(
    debug_info: Dict[str, Any],
    *,
    text_length: int,
    validation_result: TextValidationResult,
    start_validation: float,
) -> None:
    debug_info["steps"].append(
        {
            "step": "Text_Validation",
            "input": {"text_length": text_length, "enable_filtering": True},
            "output": validation_result.is_valid,
            "error": (None if validation_result.is_valid else validation_result.error_message),
            "duration": round(time.perf_counter() - start_validation, 3),
        }
    )


def _validate_and_normalize_text(
    text: str,
    debug_info: Dict[str, Any],
    start_total: float,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    start_validation = time.perf_counter()
    validation_result = validate_text_input(text, enable_content_filtering=True)
    _append_text_validation_step(
        debug_info,
        text_length=len(text),
        validation_result=validation_result,
        start_validation=start_validation,
    )
    if validation_result.is_valid:
        return validation_result.normalized_text, None

    error_message = f"Text validation failed: {validation_result.error_message}"
    return None, _pipeline_error_result(
        debug_info=debug_info,
        start_total=start_total,
        error_message=error_message,
        failed_stage=PipelineStage.VALIDATION,
        error_code=_classify_text_validation(validation_result),
        asr_text=None,
        translation_text=None,
        audio_bytes=None,
        validation_result=validation_result,
    )


def _primary_refinement_status(outcome: RefinementOutcome) -> str:
    """The refinement stage's own status, for the pipeline debug/benchmark record.

    A skip has no error, so `"error" if outcome.error else "success"` recorded
    it as a success with a 0 ms duration -- dragging benchmark latency figures
    down and hiding the skip. Shared by both pipelines so they cannot drift.
    """
    if outcome.error:
        return "error"
    if outcome.skipped_reason:
        return "skipped"
    return "success"


# (response, duration_ms, started_at, completed_at, perf_counter start)
TTSCall = Tuple[requests.Response, int, datetime, datetime, float]


def _tts_error_message(tts_resp: requests.Response) -> str:
    try:
        tts_json = tts_resp.json()
        return tts_json.get("error") or str(tts_json)
    except Exception:
        return tts_resp.text


def _finish_tts_stage(
    tts_call: TTSCall,
    *,
    debug_info: Dict[str, Any],
    start_total: float,
    target_lang: str,
    translation_text: Optional[str],
    asr_text: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Record the TTS step; return the pipeline error result if synthesis failed."""
    tts_resp, tts_duration_ms, tts_started_at, tts_completed_at, start_tts = tts_call
    failed = (
        tts_resp.status_code != 200 or tts_resp.headers.get("content-type", "") != AUDIO_WAV_MIME
    )
    error_msg = _tts_error_message(tts_resp) if failed else None
    _append_tts_debug_step(
        debug_info=debug_info,
        target_lang=target_lang,
        translation_text=translation_text,
        error_msg=error_msg,
        tts_duration_ms=tts_duration_ms,
        tts_started_at=tts_started_at,
        tts_completed_at=tts_completed_at,
        start_tts=start_tts,
        tts_resp=tts_resp,
    )
    if not failed:
        return None
    return _pipeline_error_result(
        debug_info=debug_info,
        start_total=start_total,
        error_message=f"TTS-Fehler: {error_msg}",
        failed_stage=PipelineStage.TTS,
        error_code=_classify_tts_failure(tts_resp),
        asr_text=asr_text,
        translation_text=translation_text,
        audio_bytes=None,
        upstream_response=tts_resp,
    )


def _append_tts_debug_step(
    *,
    debug_info: Dict[str, Any],
    target_lang: str,
    translation_text: Optional[str],
    error_msg: Optional[str],
    tts_duration_ms: int,
    tts_started_at: datetime,
    tts_completed_at: datetime,
    start_tts: float,
    tts_resp: requests.Response,
) -> None:
    tts_step = {
        "step": "TTS",
        "name": "tts",
        "input": {"lang": target_lang, "text": translation_text},
        "output": None if error_msg else AUDIO_WAV_MIME,
        "error": error_msg,
        "duration": round(time.perf_counter() - start_tts, 3),
        "started_at": tts_started_at.isoformat() + "Z",
        "completed_at": tts_completed_at.isoformat() + "Z",
        "duration_ms": tts_duration_ms,
    }
    # The service names the model that rendered the audio, which is not the
    # configured voice when that one failed to import or load.
    model = tts_resp.headers.get("X-TTS-Model")
    if model:
        tts_step["model"] = model
        tts_step["language"] = target_lang
    fallback = tts_resp.headers.get("X-TTS-Fallback")
    if fallback is not None:
        tts_step["fallback"] = fallback.lower() == "true"
    debug_info["steps"].append(tts_step)


def _finalize_pipeline_success(debug_info: Dict[str, Any], start_total: float) -> None:
    _record_pipeline_duration(debug_info, start_total)
    # Written on success too, so a consumer reads the same two keys on every
    # row rather than treating "absent" as a third, untyped outcome.
    debug_info["failed_stage"] = PipelineStage.NONE.value
    debug_info["error_code"] = QualityErrorCode.NONE.value
    debug_info["system"] = _collect_system_metrics()


@dataclass
class _PipelineRun:
    """One message's way through the pipeline, for either input mode.

    The mode's head (ASR, or text validation) and the shared tail record their
    results here, so the one exception handler reports the work already done
    whichever stage raised.
    """

    mode: str
    source_lang: str
    target_lang: str
    session_id: Optional[str]
    debug: bool
    debug_info: Dict[str, Any]
    start_total: float
    source_text: Optional[str] = None
    translation_text: Optional[str] = None


def _start_run(
    mode: str,
    source_lang: str,
    target_lang: str,
    *,
    session_id: Optional[str],
    debug: bool,
    input_size: Dict[str, int],
) -> _PipelineRun:
    started_at = utc_now()
    debug_info: Dict[str, Any] = {
        "frontend_input": {"source_lang": source_lang, "target_lang": target_lang, **input_size},
        "steps": [],
        "pipeline_started_at": started_at.isoformat() + "Z",
    }
    return _PipelineRun(
        mode=mode,
        source_lang=source_lang,
        target_lang=target_lang,
        session_id=session_id,
        debug=debug,
        debug_info=debug_info,
        start_total=time.perf_counter(),
    )


def _translate(run: _PipelineRun, speech: SpeechServices) -> Tuple[Any, Dict[str, Any]]:
    start = time.perf_counter()
    started_at = utc_now()
    payload = {
        "text": run.source_text,
        "source_lang": run.source_lang,
        "target_lang": run.target_lang,
        "model": "m2m100_1.2B",
        "debug": str(run.debug).lower(),
    }
    response = speech.translate(payload)
    completed_at = utc_now()
    body = response.json()
    duration_ms = int((time.perf_counter() - start) * 1000)
    run.debug_info["steps"].append(
        {
            "step": "Translation",
            "name": "translation",
            "input": payload,
            "output": body.get("translations", ""),
            "error": body.get("error"),
            "duration": round(time.perf_counter() - start, 3),
            "started_at": started_at.isoformat() + "Z",
            "completed_at": completed_at.isoformat() + "Z",
            "duration_ms": duration_ms,
        }
    )
    return response, body


def _refine(run: _PipelineRun, refiner: BaseTranslationRefiner) -> None:
    if not refiner.is_active:
        return
    started_at = utc_now()
    outcome: RefinementOutcome = refiner.refine(
        run.translation_text,
        run.source_lang,
        run.target_lang,
        context={"original_text": run.source_text, "pipeline": run.mode},
    )
    completed_at = utc_now()
    run.translation_text = outcome.text
    run.debug_info["steps"].append(
        {
            "step": "LLM_Refinement",
            "name": "refinement",
            "input": {"enabled": True, "changed": outcome.changed},
            "output": run.translation_text,
            "error": outcome.error,
            "duration": round((outcome.latency_ms or 0.0) / 1000, 3),
            "started_at": started_at.isoformat() + "Z",
            "completed_at": completed_at.isoformat() + "Z",
            "duration_ms": int(outcome.latency_ms or 0),
            "model": outcome.model,
            "refinement_comparison": {
                "primary_model": outcome.model,
                "primary_status": _primary_refinement_status(outcome),
                "candidate_model": outcome.candidate_model,
                "candidate_status": outcome.candidate_status,
            },
        }
    )


# One limit for both modes: TTS reads translated text whichever way the
# message arrived.
TTS_TIMEOUT_SECONDS = 45


def _synthesize(run: _PipelineRun, speech: SpeechServices) -> TTSCall:
    start = time.perf_counter()
    started_at = utc_now()
    payload = {
        "text": run.translation_text,
        "lang": run.target_lang,
        "session_id": run.session_id,
        "debug": str(run.debug).lower(),
    }
    response = speech.synthesize(payload, timeout=TTS_TIMEOUT_SECONDS)
    completed_at = utc_now()
    duration_ms = int((time.perf_counter() - start) * 1000)
    return response, duration_ms, started_at, completed_at, start


def _run_translation_tail(
    run: _PipelineRun, *, speech: SpeechServices, refiner: BaseTranslationRefiner
) -> Dict[str, Any]:
    """Translation, refinement and TTS: everything after the source text exists."""
    response, body = _translate(run, speech)
    if response.status_code != 200:
        error_msg = body.get("detail") or str(body)
        return _pipeline_error_result(
            debug_info=run.debug_info,
            start_total=run.start_total,
            error_message=f"Translation-Fehler: {error_msg}",
            failed_stage=PipelineStage.TRANSLATION,
            error_code=classify_upstream_status(response.status_code),
            asr_text=run.source_text,
            translation_text=None,
            audio_bytes=None,
            upstream_response=response,
        )
    run.translation_text = body.get("translations", "")

    _refine(run, refiner)

    tts_call = _synthesize(run, speech)
    tts_failure = _finish_tts_stage(
        tts_call,
        debug_info=run.debug_info,
        start_total=run.start_total,
        target_lang=run.target_lang,
        translation_text=run.translation_text,
        asr_text=run.source_text,
    )
    if tts_failure:
        return tts_failure

    _finalize_pipeline_success(run.debug_info, run.start_total)
    return {
        "error": False,
        "asr_text": run.source_text,
        "translation_text": run.translation_text,
        "audio_bytes": tts_call[0].content,
        "debug": run.debug_info,
    }


def _pipeline_exception_result(error: Exception, run: _PipelineRun) -> Dict[str, Any]:
    """The one place a stage that raised becomes a pipeline result, for both modes."""
    if isinstance(error, CircuitBreakerOpenError):
        # A known, transient condition with a known stage, not an
        # unclassifiable pipeline error.
        return _circuit_open_result(
            error,
            debug_info=run.debug_info,
            start_total=run.start_total,
            asr_text=run.source_text,
            translation_text=run.translation_text,
        )
    # error_msg and debug can reach the browser in a response, and a requests
    # exception carries the internal service hostname and port. The detail goes
    # to the server log; the client gets the stable taxonomy code.
    code = classify_exception(error)
    logging.warning("Pipeline failed (%s)", code.value, exc_info=True)
    return _pipeline_error_result(
        debug_info=run.debug_info,
        start_total=run.start_total,
        error_message=f"Pipeline-Fehler: {code.value}",
        failed_stage=PipelineStage.UNKNOWN,
        error_code=code,
        asr_text=run.source_text,
        translation_text=run.translation_text,
        audio_bytes=None,
    )


def _transcribe(
    run: _PipelineRun, file_bytes: bytes, speech: SpeechServices
) -> Optional[Dict[str, Any]]:
    """Run ASR into ``run.source_text``; the failure result if ASR answered an error."""
    start = time.perf_counter()
    started_at = utc_now()
    response = speech.transcribe(file_bytes, lang=run.source_lang, debug=run.debug)
    completed_at = utc_now()
    duration_ms = int((time.perf_counter() - start) * 1000)

    # The status was never checked here, so a failed transcription became an
    # empty string and went on to be "successfully" translated -- the audio
    # path's failure rows went missing entirely. upstream_response keeps a
    # 503 transient, exactly as the translation and TTS steps already do.
    if response.status_code != 200:
        error_msg = _upstream_error_message(response)
        run.debug_info["steps"].append(
            {
                "step": "ASR",
                "name": "asr",
                "input": {"lang": run.source_lang},
                "output": None,
                "error": error_msg,
                "duration": round(duration_ms / 1000, 3),
                "started_at": started_at.isoformat() + "Z",
                "completed_at": completed_at.isoformat() + "Z",
                "duration_ms": duration_ms,
            }
        )
        return _pipeline_error_result(
            debug_info=run.debug_info,
            start_total=run.start_total,
            error_message=f"ASR-Fehler: {error_msg}",
            failed_stage=PipelineStage.ASR,
            error_code=classify_upstream_status(response.status_code),
            asr_text=None,
            translation_text=None,
            audio_bytes=None,
            upstream_response=response,
        )

    body = response.json()
    run.source_text = body.get("text", "")
    run.debug_info["steps"].append(
        {
            "step": "ASR",
            "name": "asr",
            "input": {"lang": run.source_lang},
            "output": run.source_text,
            "model": body.get("debug", {}).get("model"),
            "error": body.get("error"),
            "duration": round(time.perf_counter() - start, 3),
            "started_at": started_at.isoformat() + "Z",
            "completed_at": completed_at.isoformat() + "Z",
            "duration_ms": duration_ms,
        }
    )
    if not (run.source_text or "").strip():
        result = _pipeline_error_result(
            debug_info=run.debug_info,
            start_total=run.start_total,
            error_message="ASR-Fehler: no speech recognised",
            failed_stage=PipelineStage.ASR,
            error_code=QualityErrorCode.NO_SPEECH_RECOGNIZED,
            asr_text=run.source_text,
            translation_text=None,
            audio_bytes=None,
        )
        result["error_code"] = NO_SPEECH_ERROR_CODE
        return result
    return None


# === Text Validation and Processing ===


def validate_text_input(text: str, enable_content_filtering: bool = True) -> TextValidationResult:
    """
    Comprehensive text validation and content filtering

    Validates:
    - Text length (1-500 characters)
    - UTF-8 encoding
    - Spam detection
    - Harmful content filtering

    Args:
        text: Input text to validate
        enable_content_filtering: Whether to apply content filtering

    Returns:
        TextValidationResult with validation status and details
    """
    start_time = time.perf_counter()
    specs = TextSpecs()

    # Step 1: Basic validation
    if not isinstance(text, str):
        return TextValidationResult(
            is_valid=False,
            error_code="INVALID_TYPE",
            error_message="Input must be a string",
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # Step 2: Length validation
    text_length = len(text)
    if text_length < specs.MIN_LENGTH:
        return TextValidationResult(
            is_valid=False,
            error_code="TEXT_TOO_SHORT",
            error_message=f"Text too short: {text_length} characters. Minimum: {specs.MIN_LENGTH}",
            details={"length": text_length, "min_length": specs.MIN_LENGTH},
            length=text_length,
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    if text_length > specs.MAX_LENGTH:
        return TextValidationResult(
            is_valid=False,
            error_code="TEXT_TOO_LONG",
            error_message=f"Text too long: {text_length} characters. Maximum: {specs.MAX_LENGTH}",
            details={"length": text_length, "max_length": specs.MAX_LENGTH},
            length=text_length,
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # Step 3: Encoding validation
    try:
        text.encode("utf-8")
        encoding = "utf-8"
    except UnicodeEncodeError:
        return TextValidationResult(
            is_valid=False,
            error_code="INVALID_ENCODING",
            error_message="Text contains invalid UTF-8 characters",
            details={"encoding_error": "utf-8 encoding failed"},
            length=text_length,
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # Step 4: Text normalization
    normalized_text = normalize_text(text)

    # Step 5: Content filtering (always detect, optionally block)
    contains_spam = detect_spam(normalized_text)
    contains_harmful_content = detect_harmful_content(normalized_text)

    if enable_content_filtering:
        if contains_spam:
            return TextValidationResult(
                is_valid=False,
                error_code="SPAM_DETECTED",
                error_message="Text appears to be spam",
                details={"spam_patterns": "multiple repetitive patterns detected"},
                length=text_length,
                encoding=encoding,
                contains_spam=True,
                normalized_text=normalized_text,
                validation_time_ms=int((time.perf_counter() - start_time) * 1000),
            )

        if contains_harmful_content:
            return TextValidationResult(
                is_valid=False,
                error_code="HARMFUL_CONTENT",
                error_message="Text contains potentially harmful content",
                details={"content_filter": "harmful patterns detected"},
                length=text_length,
                encoding=encoding,
                contains_harmful_content=True,
                normalized_text=normalized_text,
                validation_time_ms=int((time.perf_counter() - start_time) * 1000),
            )

    # Step 6: Success
    return TextValidationResult(
        is_valid=True,
        length=text_length,
        encoding=encoding,
        contains_spam=contains_spam,
        contains_harmful_content=contains_harmful_content,
        normalized_text=normalized_text,
        validation_time_ms=int((time.perf_counter() - start_time) * 1000),
    )


def normalize_text(text: str) -> str:
    """
    Normalize text for processing

    - Strip whitespace
    - Normalize unicode characters
    - Remove excessive whitespace
    """
    # Strip leading/trailing whitespace
    text = text.strip()

    # Normalize unicode (NFC - canonical composition)
    text = unicodedata.normalize("NFC", text)

    # Replace multiple whitespace with single space
    text = re.sub(r"\s+", " ", text)

    return text


def detect_spam(text: str) -> bool:
    """
    Simple spam detection

    Detects:
    - Excessive repetition
    - ALL CAPS text
    - Common spam patterns
    """
    # Check for excessive repetition
    words = text.lower().split()
    if len(words) > 3 and len(set(words)) < len(words) * 0.5:
        return True

    # Check for excessive caps (more than 60% uppercase letters)
    letter_chars = [c for c in text if c.isalpha()]
    if len(letter_chars) > 10:
        caps_ratio = len([c for c in letter_chars if c.isupper()]) / len(letter_chars)
        if caps_ratio > 0.6:
            return True

    # Check for common spam patterns
    spam_patterns = [
        r"(.)\1{4,}",  # Same character repeated 5+ times
        r"(..)\1{3,}",  # Same 2-char pattern repeated 4+ times
        r"(?i)(buy now|click here|free money|act now).*\1",  # Common spam phrases repeated
        r"!!!.*!!!.*!!!",  # Multiple exclamation patterns
    ]

    for pattern in spam_patterns:
        if re.search(pattern, text):
            return True

    return False


def detect_harmful_content(text: str) -> bool:
    """
    Basic harmful content detection

    Note: This is a simple implementation.
    In production, use dedicated content moderation APIs.
    """
    # Simple keyword-based filtering
    harmful_patterns = [
        r"(?i)(hate|kill|die|death)\s+(all|every)",
        r"(?i)(bomb|weapon|terror|attack)\s+(plan|how to|instructions|making)",
        r"(?i)(suicide|self\s*harm|hurt\s*myself)",
    ]

    for pattern in harmful_patterns:
        if re.search(pattern, text):
            return True

    return False


@dataclass(slots=True)
class SpeechPipeline:
    """What process_wav and process_text_pipeline call out to, for one app.

    Built by build_gateway_dependencies. The conversation service holds this
    one object and passes its parts to the pipeline functions, so every message
    runs with the same speech services, refiner and audio validator.
    """

    speech: SpeechServices
    refiner: BaseTranslationRefiner
    validator: AudioValidator


def process_text_pipeline(
    text: str,
    source_lang: str,
    target_lang: str,
    session_id: str = None,
    debug: bool = False,
    validate_text: bool = True,
    *,
    speech: SpeechServices,
    refiner: BaseTranslationRefiner,
) -> Dict[str, Any]:
    """
    Optimized text processing pipeline that skips ASR

    Pipeline: Text Input → Text Validation → Translation → TTS

    Args:
        text: Input text to process
        source_lang: Source language code
        target_lang: Target language code
        session_id: Session ID for deterministic TTS seed
        debug: Enable debug information
        validate_text: Enable text validation
        speech: The app's speech services
        refiner: The app's translation refiner

    Returns:
        Processing result with translation and audio
    """
    run = _start_run(
        "text",
        source_lang,
        target_lang,
        session_id=session_id,
        debug=debug,
        input_size={"text_length": len(text)},
    )
    try:
        if validate_text:
            processed_text, validation_failure = _validate_and_normalize_text(
                text, run.debug_info, run.start_total
            )
            if validation_failure is not None:
                return validation_failure
            run.source_text = processed_text
        else:
            run.source_text = text
        return _run_translation_tail(run, speech=speech, refiner=refiner)
    except Exception as error:
        return _pipeline_exception_result(error, run)


def process_wav(
    file_bytes,
    source_lang,
    target_lang,
    debug=False,
    *,
    speech: SpeechServices,
    refiner: BaseTranslationRefiner,
    session_id: Optional[str] = None,
):
    """
    Run ASR, translation, refinement and TTS on already-validated WAV bytes.

    Args:
        file_bytes: Raw audio file bytes
        source_lang: Source language code
        target_lang: Target language code
        debug: Enable debug information
        speech: The app's speech services
        refiner: The app's translation refiner
        session_id: Session ID for the deterministic TTS seed

    Returns:
        Dict with processing results including validation info
    """
    run = _start_run(
        "audio",
        source_lang,
        target_lang,
        session_id=session_id,
        debug=debug,
        input_size={"file_size": len(file_bytes)},
    )
    try:
        asr_failure = _transcribe(run, file_bytes, speech)
        if asr_failure is not None:
            return asr_failure
        return _run_translation_tail(run, speech=speech, refiner=refiner)
    except Exception as error:
        return _pipeline_exception_result(error, run)
