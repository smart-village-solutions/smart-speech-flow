"""Message processing for tenant conversations: validation, pipeline, storage, broadcast."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

from .audio_storage import AudioStore, AudioVariant, scope_pipeline_audio_urls, scoped_audio_url
from .content_retention import captured_retention_hours
from .log_safety import safe_session_ref, sanitize_log_value
from .message_delivery import create_session_message
from .message_models import MessageResponse, create_error_response
from .message_requests import (
    _correlation_id_for,
    _log_session_event,
    _parse_audio_form,
    _parse_text_request,
    _store_audio_artifacts,
    _store_translated_audio,
    _validate_audio_file_input,
    _validate_audio_payload,
    _validate_supported_languages,
    validate_session_languages,
)
from .message_telemetry import MessageTelemetryRecorder
from .pipeline_admission import PipelineAdmission, PipelineBusyError, run_pipeline
from .pipeline_logic import SpeechPipeline, process_text_pipeline, process_wav
from .pipeline_results import (
    DEFAULT_UPSTREAM_RETRY_AFTER_SECONDS,
    NO_SPEECH_ERROR_CODE,
    UPSTREAM_BUSY_ERROR_CODE,
)
from .quality_telemetry import QualityTelemetry
from .quality_telemetry_schema import InputMode
from .session_manager import TenantSessionManager
from .session_models import ClientType, SessionMessage, SessionStatus
from .tenant_session import TenantSessionKey
from .websocket import WebSocketManager

logger = logging.getLogger(__name__)


def transform_pipeline_metadata(
    debug_info: Optional[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
    original_audio_url: Optional[str] = None,
    message_id: Optional[str] = None,
    *,
    original_audio_available: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """
    Transform pipeline debug_info to spec-compliant pipeline_metadata format.

    Args:
        debug_info: Raw debug information from pipeline_logic
        source_lang: Source language code
        target_lang: Target language code
        original_audio_url: Legacy availability indicator; never copied to output
        message_id: Message ID used when marking generated audio available
        original_audio_available: Explicit original-audio availability

    Returns:
        Spec-compliant pipeline_metadata dict or None if no debug_info
    """
    if not debug_info:
        return None

    steps = debug_info.get("steps", [])
    if not steps:
        return None

    # Build pipeline metadata according to spec
    has_original_audio = (
        original_audio_available
        if original_audio_available is not None
        else original_audio_url is not None
    )
    pipeline_metadata = {
        "input": {
            "type": "audio" if has_original_audio else "text",
            "source_lang": source_lang,
        },
        "steps": [],
        "total_duration_ms": debug_info.get("total_duration_ms", 0),
        "pipeline_started_at": debug_info.get("pipeline_started_at", ""),
        "pipeline_completed_at": debug_info.get("pipeline_completed_at", ""),
    }

    for step in steps:
        transformed_step = _transform_pipeline_step(step, target_lang, message_id)
        if transformed_step is not None:
            pipeline_metadata["steps"].append(transformed_step)

    return pipeline_metadata


def _transform_pipeline_step(
    step: Dict[str, Any], target_lang: str, message_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    step_name = step.get("name") or step.get("step", "").lower()
    if "validation" in step_name.lower():
        return None

    transformed_step = {
        "name": step_name,
        "input": step.get("input", {}),
        "output": {},
        "started_at": step.get("started_at", ""),
        "completed_at": step.get("completed_at", ""),
        "duration_ms": step.get("duration_ms", 0),
    }

    if step_name == "asr":
        transformed_step["output"] = {
            "text": step.get("output", ""),
            "model": step.get("model") or step.get("debug", {}).get("model", "unknown"),
        }
    elif step_name == "translation":
        transformed_step["output"] = {
            "text": step.get("output", ""),
            "model": step.get("input", {}).get("model", "m2m100_1.2B"),
        }
    elif step_name in {"refinement", "llm_refinement"}:
        transformed_step["name"] = "refinement"
        transformed_step["output"] = {
            "text": step.get("output", ""),
            "changed": step.get("input", {}).get("changed", False),
            "model": step.get("model")
            or step.get("refinement_comparison", {}).get("primary_model", "unknown"),
        }
        if step.get("refinement_comparison"):
            transformed_step["refinement_comparison"] = step["refinement_comparison"]
    elif step_name == "tts":
        transformed_step["output"] = _build_tts_step_output(step, target_lang, message_id)

    return transformed_step


def _build_tts_step_output(
    step: Dict[str, Any], target_lang: str, _message_id: Optional[str]
) -> Dict[str, Any]:
    output_value = step.get("output", "")
    if not (isinstance(output_value, str) and "audio" in output_value):
        return {}

    return {
        "audio_available": True,
        "format": "wav",
        "model": step.get("model", "unknown"),
        "language": step.get("language", target_lang),
    }


def _system_busy_error(busy: PipelineBusyError) -> HTTPException:
    """503 for a saturated pipeline (#191).

    Uses the same envelope as every other failure on this endpoint, so the
    frontend needs no new parsing; it maps any 5xx to its generic server error.
    """
    return HTTPException(
        status_code=503,
        detail=create_error_response(
            "SYSTEM_BUSY",
            "The translation pipeline is at capacity. Please retry shortly.",
            {
                "max_concurrent_pipelines": busy.max_concurrent,
                # Deliberately the same value as the Retry-After header, so a
                # client reading the body cannot retry sooner than advised.
                "retry_after_seconds": busy.retry_after_seconds,
                "queue_wait_seconds": busy.queue_wait_seconds,
                "waited_seconds": round(busy.waited_seconds, 3),
            },
        ),
        headers={"Retry-After": busy.retry_after_header},
    )


def _raise_if_upstream_busy(result: Dict[str, Any]) -> None:
    """Re-raises an upstream capacity rejection as a retryable 503 (#190).

    A GPU service that shed load answered 503 with a Retry-After, which clears
    on its own. The pipeline flattens it into ``result["error"]`` like any other
    failure, and without this the audio path would report 500 PIPELINE_ERROR and
    the text path 400 TEXT_PIPELINE_ERROR — the latter blaming the client for a
    condition it did not cause. Same envelope as _system_busy_error, so the
    frontend needs no new parsing whichever layer ran out of capacity.
    """
    if result.get("error_code") != UPSTREAM_BUSY_ERROR_CODE:
        return

    retry_after = int(result.get("retry_after_seconds", DEFAULT_UPSTREAM_RETRY_AFTER_SECONDS))
    raise HTTPException(
        status_code=503,
        detail=create_error_response(
            "SYSTEM_BUSY",
            "The translation pipeline is at capacity. Please retry shortly.",
            {
                "retry_after_seconds": retry_after,
                "upstream_error": result.get("error_msg"),
            },
        ),
        headers={"Retry-After": str(retry_after)},
    )


def _raise_if_no_speech(result: Dict[str, Any]) -> None:
    """A recording in which ASR heard nothing is the speaker's to repeat (422).

    Same envelope as every other failure on this endpoint. The code, not the
    status, identifies it: FastAPI answers 422 for invalid fields too.
    """
    if result.get("error_code") != NO_SPEECH_ERROR_CODE:
        return
    raise HTTPException(
        status_code=422,
        detail=create_error_response(
            NO_SPEECH_ERROR_CODE, "No speech was recognised in the recording.", {}
        ),
    )


def _build_message_response(
    *,
    message: SessionMessage,
    key: TenantSessionKey,
    source_lang: str,
    target_lang: str,
    pipeline_type: str,
    pipeline_metadata: Optional[Dict[str, Any]],
    start_time: float,
    sender: ClientType,
) -> MessageResponse:
    processing_time_ms = max(1, int((time.perf_counter() - start_time) * 1000))
    return MessageResponse(
        status="success",
        message_id=message.id,
        session_id=key.session_id,
        original_text=message.original_text,
        translated_text=message.translated_text,
        audio_available=message.translated_audio_available,
        audio_url=(
            scoped_audio_url(key, sender.value, message.id, AudioVariant.TRANSLATED)
            if message.translated_audio_available
            else None
        ),
        processing_time_ms=processing_time_ms,
        pipeline_type=pipeline_type,
        source_lang=source_lang,
        target_lang=target_lang,
        timestamp=message.timestamp.isoformat(),
        pipeline_metadata=scope_pipeline_audio_urls(
            pipeline_metadata, key, sender.value, message.id
        ),
    )


async def send_unified_message(
    key: TenantSessionKey,
    sender: ClientType,
    request: Request,
    manager: Optional[WebSocketManager] = None,
    *,
    sessions: TenantSessionManager,
    pipeline: SpeechPipeline,
    audio_store: AudioStore,
    admission: Optional[PipelineAdmission] = None,
    telemetry: Optional[QualityTelemetry] = None,
) -> MessageResponse:
    """
    Unified Message Endpoint für Audio- und Text-Input

    Automatische Content-Type-Detection:
    - multipart/form-data: Audio-Input (WAV-Datei)
    - application/json: Text-Input (JSON-Payload)

    Returns einheitliches MessageResponse-Format
    """
    import logging

    logger = logging.getLogger(__name__)

    session_id = key.session_id
    start_time = time.perf_counter()
    # One row per processed message, assembled across every exit below and
    # emitted once from the `finally`. See message_telemetry.py.
    recorder = MessageTelemetryRecorder(
        session_id=key, start_time=start_time, pseudonymizer=sessions.pseudonymizer
    )
    _log_session_event("🚀 Processing message", session_id)

    # Session-Validation
    logger.debug("🔍 Validating session")
    session = await sessions.get_session(key)
    if not session:
        _log_session_event("❌ Session nicht gefunden", session_id)
        raise HTTPException(
            status_code=404,
            detail=create_error_response(
                "SESSION_NOT_FOUND",
                "Session not found or expired",
                {"session_id": session_id},
            ),
        )

    if session.status != SessionStatus.ACTIVE:
        _log_session_event(
            "❌ Session nicht aktiv", session_id, session_status=session.status.value
        )
        raise HTTPException(
            status_code=400,
            detail=create_error_response(
                "SESSION_NOT_ACTIVE",
                f"Session is not active (status: {session.status.value})",
                {"session_id": session_id, "session_status": session.status.value},
            ),
        )

    _log_session_event("✅ Session-Validation erfolgreich", session_id)

    # Content-Type-basierte Auto-Detection
    content_type = request.headers.get("content-type", "")
    logger.info(
        "📋 Content-Type received | %s",
        sanitize_log_value({"content_type": content_type}),
    )

    try:
        if content_type.startswith("multipart/form-data"):
            # Audio-Pipeline
            recorder.arm(InputMode.AUDIO)
            _log_session_event("🎵 Starte Audio-Pipeline", session_id)
            result = await process_audio_input(
                key,
                sender,
                request,
                start_time,
                manager,
                recorder=recorder,
                sessions=sessions,
                pipeline=pipeline,
                audio_store=audio_store,
                admission=admission,
            )
            _log_session_event("✅ Audio-Pipeline erfolgreich", session_id)
            return result
        elif content_type.startswith("application/json"):
            # Text-Pipeline
            recorder.arm(InputMode.TEXT)
            _log_session_event("📝 Starte Text-Pipeline", session_id)
            result = await process_text_input(
                key,
                sender,
                request,
                start_time,
                manager,
                recorder=recorder,
                sessions=sessions,
                pipeline=pipeline,
                audio_store=audio_store,
                admission=admission,
            )
            _log_session_event("✅ Text-Pipeline erfolgreich", session_id)
            return result
        else:
            logger.error(
                "❌ Unsupported Content-Type received | %s",
                sanitize_log_value({"content_type": content_type}),
            )
            raise HTTPException(
                status_code=400,
                detail=create_error_response(
                    "UNSUPPORTED_CONTENT_TYPE",
                    f"Unsupported content type: {content_type}. Use multipart/form-data for audio or application/json for text.",
                    {"content_type": content_type},
                ),
            )

    except HTTPException as exc:
        recorder.record_http_failure(exc.status_code)
        _log_session_event("⚠️ HTTPException in send_unified_message", session_id)
        raise
    except Exception as e:
        # The unhandled-error middleware answers and logs it; this row must still
        # say the message failed, and the log must still name the session.
        _log_session_event(
            "💥 Unexpected error in send_unified_message",
            session_id,
            error_type=type(e).__name__,
        )
        recorder.record_http_failure(500)
        raise
    finally:
        recorder.emit(telemetry)


async def _complete_message(
    *,
    key: TenantSessionKey,
    client_type: ClientType,
    result: Dict[str, Any],
    source_lang: str,
    target_lang: str,
    original_text: str,
    original_audio: Optional[bytes],
    pipeline_type: str,
    manager: Optional[WebSocketManager],
    correlation_id: str,
    sessions: TenantSessionManager,
    audio_store: AudioStore,
    start_time: float,
    retention_hours: Optional[int],
) -> MessageResponse:
    """Store, record and answer a message the pipeline produced, for either mode.

    `retention_hours` is the session's captured retention, written beside its
    audio for the cleanup; None leaves the audio to the short default.
    """
    message_id = str(uuid.uuid4())
    original_audio_available = (
        _store_audio_artifacts(
            key,
            client_type,
            message_id,
            original_audio,
            audio_store=audio_store,
            retention_hours=retention_hours,
        )
        if original_audio is not None
        else False
    )
    pipeline_metadata = transform_pipeline_metadata(
        result.get("debug"),
        source_lang,
        target_lang,
        message_id=message_id,
        original_audio_available=original_audio_available,
    )
    translated_audio_available = _store_translated_audio(
        key,
        message_id,
        result.get("audio_bytes"),
        audio_store=audio_store,
        retention_hours=retention_hours,
    )
    message = await create_session_message(
        session_id=key,
        client_type=client_type,
        original_text=original_text,
        translated_text=result.get("translation_text", ""),
        source_lang=source_lang,
        target_lang=target_lang,
        manager=manager,
        pipeline_metadata=pipeline_metadata,
        # Internal availability marker only. Role-scoped URLs are built at
        # HTTP/WebSocket response boundaries and are never persisted.
        original_audio_url="available" if original_audio_available else None,
        message_id=message_id,
        correlation_id=correlation_id,
        sessions=sessions,
        translated_audio_available=translated_audio_available,
    )
    return _build_message_response(
        message=message,
        key=key,
        source_lang=source_lang,
        target_lang=target_lang,
        pipeline_type=pipeline_type,
        pipeline_metadata=pipeline_metadata,
        start_time=start_time,
        sender=client_type,
    )


async def process_audio_input(
    key: TenantSessionKey,
    client_type: ClientType,
    request: Request,
    start_time: float,
    manager: Optional[WebSocketManager] = None,
    recorder: Optional[MessageTelemetryRecorder] = None,
    *,
    sessions: TenantSessionManager,
    pipeline: SpeechPipeline,
    audio_store: AudioStore,
    admission: Optional[PipelineAdmission] = None,
) -> MessageResponse:
    """Audio-Input verarbeiten (multipart/form-data)"""
    # A recorder nobody armed emits nothing, so a direct caller -- every test
    # that drives this function without the route -- needs to pass nothing.
    recorder = recorder or MessageTelemetryRecorder(
        session_id=key, start_time=start_time, pseudonymizer=sessions.pseudonymizer
    )
    # Before the pipeline: a malformed header is the caller's mistake and must
    # not cost a pipeline run.
    correlation_id = _correlation_id_for(request)
    file, source_lang, target_lang = await _parse_audio_form(request)
    recorder.record_request(
        client_type=client_type, source_lang=source_lang, target_lang=target_lang
    )

    # Validate languages match session configuration
    session = await sessions.get_session(key)
    if session:
        validate_session_languages(session, source_lang, target_lang, client_type)

    _validate_audio_file_input(file)
    file_bytes = await file.read()
    processed_file_bytes = _validate_audio_payload(file, file_bytes, pipeline.validator)
    _validate_supported_languages(source_lang, target_lang)

    # Audio-Pipeline ausführen (Validation bereits durchgeführt).
    # process_wav is synchronous and spends its time in blocking HTTP calls to
    # ASR/translation/TTS, so it runs on a worker thread to keep the gateway
    # event loop free for other sessions, health checks and WS heartbeats.
    # run_pipeline also bounds how many reach the GPU at once, and covers only
    # the GPU call: form parsing and audio storage need no capacity.
    try:
        result = await run_pipeline(
            admission,
            process_wav,
            processed_file_bytes,
            source_lang,
            target_lang,
            session_id=key.session_id,
            speech=pipeline.speech,
            refiner=pipeline.refiner,
        )
    except PipelineBusyError as busy:
        raise _system_busy_error(busy) from busy

    recorder.record_pipeline_result(result)

    if result.get("error", False):
        _raise_if_upstream_busy(result)
        _raise_if_no_speech(result)
        raise HTTPException(
            status_code=500,
            detail=create_error_response(
                "PIPELINE_ERROR",
                f"Audio pipeline failed: {result.get('error_msg', 'Unknown error')}",
                {"pipeline_result": result},
            ),
        )

    return await _complete_message(
        key=key,
        client_type=client_type,
        result=result,
        source_lang=source_lang,
        target_lang=target_lang,
        original_text=result.get("asr_text", ""),
        original_audio=file_bytes,
        pipeline_type="audio",
        manager=manager,
        correlation_id=correlation_id,
        sessions=sessions,
        audio_store=audio_store,
        start_time=start_time,
        retention_hours=captured_retention_hours(session),
    )


async def process_text_input(
    key: TenantSessionKey,
    client_type: ClientType,
    request: Request,
    start_time: float,
    manager: Optional[WebSocketManager] = None,
    recorder: Optional[MessageTelemetryRecorder] = None,
    *,
    sessions: TenantSessionManager,
    pipeline: SpeechPipeline,
    audio_store: AudioStore,
    admission: Optional[PipelineAdmission] = None,
) -> MessageResponse:
    """Text-Input verarbeiten (application/json)"""
    session_id = key.session_id
    recorder = recorder or MessageTelemetryRecorder(
        session_id=key, start_time=start_time, pseudonymizer=sessions.pseudonymizer
    )
    correlation_id = _correlation_id_for(request)
    text_request = await _parse_text_request(request)
    recorder.record_request(
        client_type=client_type,
        source_lang=text_request.source_lang,
        target_lang=text_request.target_lang,
    )

    # Language validation
    logger.info(
        "🔍 Starting language validation for text request | %s",
        sanitize_log_value(
            {
                "source_lang": text_request.source_lang,
                "target_lang": text_request.target_lang,
                "client_type": client_type.value,
            }
        ),
    )
    _validate_supported_languages(text_request.source_lang, text_request.target_lang)

    # Validate languages match session configuration
    session = await sessions.get_session(key)
    logger.info(
        "🔎 Session lookup for text input | %s",
        sanitize_log_value(
            {
                "session_ref": safe_session_ref(session_id),
                "session_found": session is not None,
            }
        ),
    )
    if session:
        validate_session_languages(
            session,
            text_request.source_lang,
            text_request.target_lang,
            client_type,
        )
    else:
        logger.warning(
            "⚠️ Session not found for language validation - skipping check | %s",
            sanitize_log_value({"session_ref": safe_session_ref(session_id)}),
        )

    # Text-Pipeline ausführen (ASR überspringen). Offloaded for the same reason
    # as the audio pipeline: blocking translation/TTS calls must not hold the loop.
    try:
        pipeline_result = await run_pipeline(
            admission,
            process_text_pipeline,
            text_request.text,
            text_request.source_lang,
            text_request.target_lang,
            session_id=session_id,
            speech=pipeline.speech,
            refiner=pipeline.refiner,
        )
    except PipelineBusyError as busy:
        raise _system_busy_error(busy) from busy

    recorder.record_pipeline_result(pipeline_result)

    # Fehlerbehandlung
    if pipeline_result.get("error"):
        _raise_if_upstream_busy(pipeline_result)
        raise HTTPException(
            status_code=400,
            detail=create_error_response(
                "TEXT_PIPELINE_ERROR",
                pipeline_result.get("error_msg", "Text processing failed"),
                pipeline_result.get("debug", {}),
            ),
        )

    return await _complete_message(
        key=key,
        client_type=client_type,
        result=pipeline_result,
        source_lang=text_request.source_lang,
        target_lang=text_request.target_lang,
        original_text=pipeline_result.get("asr_text", text_request.text),
        original_audio=None,
        pipeline_type="text",
        manager=manager,
        correlation_id=correlation_id,
        sessions=sessions,
        audio_store=audio_store,
        start_time=start_time,
        retention_hours=captured_retention_hours(session),
    )
