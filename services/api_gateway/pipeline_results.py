"""The pipeline's result shape: timing, failure classification and the error result."""

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import psutil

from .circuit_breaker import CircuitBreakerOpenError
from .quality_telemetry import PipelineStage, QualityErrorCode, classify_upstream_status

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


def _finalize_pipeline_success(debug_info: Dict[str, Any], start_total: float) -> None:
    _record_pipeline_duration(debug_info, start_total)
    # Written on success too, so a consumer reads the same two keys on every
    # row rather than treating "absent" as a third, untyped outcome.
    debug_info["failed_stage"] = PipelineStage.NONE.value
    debug_info["error_code"] = QualityErrorCode.NONE.value
    debug_info["system"] = _collect_system_metrics()
