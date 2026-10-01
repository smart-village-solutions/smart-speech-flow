import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests

from .audio_processing import AudioValidator
from .circuit_breaker import CircuitBreakerOpenError
from .pipeline_results import (
    NO_SPEECH_ERROR_CODE,
    _circuit_open_result,
    _classify_text_validation,
    _classify_tts_failure,
    _finalize_pipeline_success,
    _pipeline_error_result,
    _upstream_error_message,
    utc_now,
)
from .quality_telemetry import classify_exception, classify_upstream_status
from .quality_telemetry_schema import PipelineStage, QualityErrorCode
from .speech_services import AUDIO_WAV_MIME, SpeechServices
from .text_validation import TextValidationResult, validate_text_input
from .translation_refiner import BaseTranslationRefiner, RefinementOutcome


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
