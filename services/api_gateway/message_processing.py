"""Message processing for tenant conversations: validation, pipeline, storage, broadcast."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from types import TracebackType
from typing import Any, Dict, Mapping, Optional

from fastapi import HTTPException, Request, UploadFile
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from .audio_storage import AudioVariant, scope_pipeline_audio_urls, scoped_audio_url
from .consent import ConsentStatus
from .log_safety import sanitize_log_value
from .message_models import (
    SUPPORTED_LANGUAGES,
    MessageResponse,
    TextMessageRequest,
    create_error_response,
    utc_now,
)
from .message_telemetry import MessageTelemetryRecorder
from .persistence_authorization import authorize_message_artifacts
from .pipeline_admission import PipelineAdmission, PipelineBusyError, run_pipeline
from .pipeline_logic import (
    DEFAULT_UPSTREAM_RETRY_AFTER_SECONDS,
    UPSTREAM_BUSY_ERROR_CODE,
    SpeechPipeline,
    process_text_pipeline,
    process_wav,
)
from .quality_telemetry import InputMode, QualityTelemetry
from .session_manager import ClientType, SessionMessage, SessionStatus, TenantSessionManager
from .studio_runtime_flow import correlation_id_from_request
from .tenant_session import TenantSessionKey
from .websocket import BroadcastResult, MessageType, WebSocketManager

logger = logging.getLogger(__name__)


def _nothing_delivered() -> BroadcastResult:
    """What a broadcast reports when there is no WebSocket manager to deliver through."""
    return BroadcastResult(
        success=True,
        total_connections=0,
        successful_sends=0,
        failed_sends=0,
        session_has_connections=False,
        errors=[],
    )


_REDACTED_EXCEPTION_MESSAGE = "Exception details redacted"


def _redacted_exception_info(
    error: Exception,
) -> tuple[type[BaseException], BaseException, Optional[TracebackType]]:
    return (
        RuntimeError,
        RuntimeError(_REDACTED_EXCEPTION_MESSAGE),
        error.__traceback__,
    )


def _safe_identifier(value: Optional[str]) -> str:
    if not value:
        return "missing"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _log_session_event(message: str, session_id: Optional[str], **extra: Any) -> None:
    safe_extra = {"session_ref": _safe_identifier(session_id)}
    safe_extra.update(sanitize_log_value(extra))
    logger.info("%s | %s", message, safe_extra)


def validate_session_languages(
    session: Any,
    source_lang: str,
    target_lang: str,
    client_type: ClientType,
) -> None:
    """Validate that message languages match session configuration.

    Expected language pairs:
    - Customer → Admin: customer_language → admin_language (de)
    - Admin → Customer: admin_language (de) → customer_language

    Raises HTTPException if languages don't match.
    """
    _log_session_event(
        "🔍 Validating languages",
        session.id,
        client=client_type.value,
        source_lang=source_lang,
        target_lang=target_lang,
    )

    def create_error_response(error_type: str, message: str, details: Dict) -> Dict:
        return {"error": message, "error_type": error_type, "details": details}

    if client_type == ClientType.CUSTOMER:
        # Customer sends in their language, expects translation to German
        if source_lang != session.customer_language:
            raise HTTPException(
                status_code=400,
                detail=create_error_response(
                    "INVALID_SOURCE_LANGUAGE",
                    f"Customer must send messages in session language '{session.customer_language}', not '{source_lang}'",
                    {
                        "expected_source_lang": session.customer_language,
                        "actual_source_lang": source_lang,
                        "session_id": session.id,
                    },
                ),
            )
        if target_lang != session.admin_language:
            raise HTTPException(
                status_code=400,
                detail=create_error_response(
                    "INVALID_TARGET_LANGUAGE",
                    f"Customer messages must be translated to admin language '{session.admin_language}', not '{target_lang}'",
                    {
                        "expected_target_lang": session.admin_language,
                        "actual_target_lang": target_lang,
                        "session_id": session.id,
                    },
                ),
            )
    elif client_type == ClientType.ADMIN:
        # Admin sends in German, expects translation to customer language
        if source_lang != session.admin_language:
            raise HTTPException(
                status_code=400,
                detail=create_error_response(
                    "INVALID_SOURCE_LANGUAGE",
                    f"Admin must send messages in admin language '{session.admin_language}', not '{source_lang}'",
                    {
                        "expected_source_lang": session.admin_language,
                        "actual_source_lang": source_lang,
                        "session_id": session.id,
                    },
                ),
            )
        if target_lang != session.customer_language:
            raise HTTPException(
                status_code=400,
                detail=create_error_response(
                    "INVALID_TARGET_LANGUAGE",
                    f"Admin messages must be translated to customer language '{session.customer_language}', not '{target_lang}'",
                    {
                        "expected_target_lang": session.customer_language,
                        "actual_target_lang": target_lang,
                        "session_id": session.id,
                    },
                ),
            )


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


def _validate_supported_languages(source_lang: str, target_lang: str) -> None:
    if source_lang in SUPPORTED_LANGUAGES and target_lang in SUPPORTED_LANGUAGES:
        return

    raise HTTPException(
        status_code=400,
        detail=create_error_response(
            "UNSUPPORTED_LANGUAGE",
            f"Unsupported language. Source: {source_lang}, Target: {target_lang}",
            {"supported_languages": list(SUPPORTED_LANGUAGES.keys())},
        ),
    )


async def _parse_audio_form(request: Request) -> tuple[Any, Any, Any]:
    form = await request.form()
    required_fields = ["file", "source_lang", "target_lang"]
    missing_fields = [field for field in required_fields if field not in form]
    if missing_fields:
        raise HTTPException(
            status_code=400,
            detail=create_error_response(
                "MISSING_FIELDS",
                f"Missing required fields: {', '.join(missing_fields)}",
                {"missing_fields": missing_fields},
            ),
        )

    return (
        form["file"],
        form["source_lang"],
        form["target_lang"],
    )


def _validate_audio_file_input(file: Any) -> None:
    if hasattr(file, "read"):
        return

    raise HTTPException(
        status_code=400,
        detail=create_error_response("INVALID_FILE", "Invalid audio file", {}),
    )


def _should_validate_upload_file(file: Any) -> bool:
    return isinstance(file, (UploadFile, StarletteUploadFile))


def _validate_audio_payload(file: Any, file_bytes: bytes) -> bytes:
    if not _should_validate_upload_file(file):
        return file_bytes

    from .pipeline_logic import validate_audio_input

    validation_result = validate_audio_input(file_bytes, normalize=True)
    if validation_result.is_valid:
        return validation_result.processed_audio or file_bytes

    raise HTTPException(
        status_code=400,
        detail=create_error_response(
            validation_result.error_code or "AUDIO_VALIDATION_FAILED",
            validation_result.error_message or "Audio validation failed",
            {
                "validation_details": validation_result.details,
                "validation_time_ms": validation_result.validation_time_ms,
            },
        ),
    )


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


def _session_consent_status(key: TenantSessionKey, sessions: TenantSessionManager) -> ConsentStatus:
    """The session's resolved consent, or `pending` when it cannot be read."""
    session = sessions.get_session(key)
    if session is None:
        return ConsentStatus.PENDING
    return session.consent_status


def _correlation_id_for(request: Request) -> str:
    """The caller's correlation ID, or a fresh one for this write.

    Validated rather than forwarded raw: an unvalidated value reaches the
    policy gate, whose blanket except would turn Studio's `ValueError` into a
    silent refusal to persist -- a retention switch operated by the caller.
    """
    return correlation_id_from_request(request)


def _store_audio_artifacts(
    key: TenantSessionKey,
    _sender: ClientType,
    message_id: str,
    file_bytes: bytes,
) -> bool:
    from .audio_storage import AudioVariant, save_audio

    original_audio_available = False
    try:
        save_audio(key, message_id, AudioVariant.ORIGINAL, file_bytes)
        original_audio_available = True
    except Exception as e:
        # See the translated-audio branch: success is still reported to the
        # caller, so a warning here is invisible in practice.
        logger.exception(
            "⚠️ Failed to save original audio: %s",
            type(e).__name__,
            exc_info=_redacted_exception_info(e),
        )

    return original_audio_available


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


async def _parse_text_request(request: Request) -> TextMessageRequest:
    body = None
    try:
        body = await request.json()
        logger.info(
            "📦 Received JSON payload metadata | %s",
            sanitize_log_value(
                {
                    "keys": sorted(body.keys()) if isinstance(body, dict) else [],
                    "has_text": (bool(body.get("text")) if isinstance(body, dict) else False),
                }
            ),
        )
    except Exception as e:
        logger.exception("❌ Failed to parse JSON", exc_info=_redacted_exception_info(e))
        raise HTTPException(
            status_code=400,
            detail=create_error_response("INVALID_JSON", "Invalid JSON", {}),
        )

    try:
        return TextMessageRequest(**body)
    except ValidationError as e:
        raise _build_text_validation_error(e, body) from e


def _build_text_validation_error(
    e: ValidationError, body: Optional[Dict[str, Any]]
) -> HTTPException:
    error_details: Mapping[str, Any] = e.errors()[0] if e.errors() else {}
    error_type = error_details.get("type", "unknown")
    field_name = error_details.get("loc", ["unknown"])[-1]

    if error_type == "string_too_long":
        max_length = error_details.get("ctx", {}).get("max_length", 500)
        actual_length = len(body.get(field_name, "")) if body and field_name in body else "unknown"
        user_message = (
            f"Der Text ist zu lang. Maximum: {max_length} Zeichen, "
            f"Ihre Eingabe: {actual_length} Zeichen."
        )
    elif error_type == "string_too_short":
        min_length = error_details.get("ctx", {}).get("min_length", 1)
        user_message = f"Der Text ist zu kurz. Minimum: {min_length} Zeichen."
    elif error_type == "missing":
        user_message = f"Pflichtfeld '{field_name}' fehlt."
    else:
        user_message = (
            f"Ungültige Eingabe für Feld '{field_name}': "
            f"{error_details.get('msg', 'Validierungsfehler')}"
        )

    logger.error(
        "❌ Validation failed | %s",
        sanitize_log_value({"field": field_name, "error_type": error_type}),
    )
    return HTTPException(
        status_code=400,
        detail=create_error_response(
            "VALIDATION_ERROR",
            user_message,
            {"field": field_name, "error_type": error_type},
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
    session = sessions.get_session(key)
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
        _log_session_event(
            "💥 Unexpected error in send_unified_message",
            session_id,
            error_type=type(e).__name__,
        )
        logger.exception(
            "Unexpected message processing failure",
            exc_info=_redacted_exception_info(e),
        )
        recorder.record_http_failure(500)
        raise HTTPException(
            status_code=500,
            detail=create_error_response(
                "PROCESSING_ERROR",
                "Message processing failed",
                {},
            ),
        )
    finally:
        recorder.emit(telemetry)


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
    session = sessions.get_session(key)
    if session:
        validate_session_languages(session, source_lang, target_lang, client_type)

    _validate_audio_file_input(file)
    file_bytes = await file.read()
    processed_file_bytes = _validate_audio_payload(file, file_bytes)
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
            validate_audio=False,
            speech=pipeline.speech,
            refiner=pipeline.refiner,
        )
    except PipelineBusyError as busy:
        raise _system_busy_error(busy) from busy

    recorder.record_pipeline_result(result)

    if result.get("error", False):
        _raise_if_upstream_busy(result)
        raise HTTPException(
            status_code=500,
            detail=create_error_response(
                "PIPELINE_ERROR",
                f"Audio pipeline failed: {result.get('error_msg', 'Unknown error')}",
                {"pipeline_result": result},
            ),
        )

    message_id = str(uuid.uuid4())
    audio_bytes = result.get("audio_bytes")
    original_audio_available = _store_audio_artifacts(key, client_type, message_id, file_bytes)

    pipeline_metadata = transform_pipeline_metadata(
        result.get("debug"),
        source_lang,
        target_lang,
        message_id=message_id,
        original_audio_available=original_audio_available,
    )

    message = await create_session_message(
        session_id=key,
        client_type=client_type,
        original_text=result.get("asr_text", ""),
        translated_text=result.get("translation_text", ""),
        audio_bytes=audio_bytes,
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
    )
    message.id = message_id
    return _build_message_response(
        message=message,
        key=key,
        source_lang=source_lang,
        target_lang=target_lang,
        pipeline_type="audio",
        pipeline_metadata=pipeline_metadata,
        start_time=start_time,
        sender=client_type,
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
    session = sessions.get_session(key)
    logger.info(
        "🔎 Session lookup for text input | %s",
        sanitize_log_value(
            {
                "session_ref": _safe_identifier(session_id),
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
            sanitize_log_value({"session_ref": _safe_identifier(session_id)}),
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

    translated_text = pipeline_result.get("translation_text", "")
    audio_bytes = pipeline_result.get("audio_bytes")

    # Generate message_id upfront for use in pipeline_metadata
    message_id = str(uuid.uuid4())

    # Transform pipeline metadata to match spec format
    pipeline_metadata = transform_pipeline_metadata(
        pipeline_result.get("debug"),
        text_request.source_lang,
        text_request.target_lang,
        original_audio_url=None,  # Text pipeline has no audio input
        message_id=message_id,  # Pass message_id for audio URL
    )

    message = await create_session_message(
        session_id=key,
        client_type=client_type,
        original_text=pipeline_result.get("asr_text", text_request.text),
        translated_text=translated_text,
        audio_bytes=audio_bytes,
        source_lang=text_request.source_lang,
        target_lang=text_request.target_lang,
        manager=manager,
        pipeline_metadata=pipeline_metadata,
        original_audio_url=None,
        message_id=message_id,
        correlation_id=correlation_id,
        sessions=sessions,
    )

    return _build_message_response(
        message=message,
        key=key,
        source_lang=text_request.source_lang,
        target_lang=text_request.target_lang,
        pipeline_type="text",
        pipeline_metadata=pipeline_metadata,
        start_time=start_time,
        sender=client_type,
    )


async def create_session_message(
    session_id: TenantSessionKey,
    client_type: ClientType,
    original_text: str,
    translated_text: str,
    audio_bytes: Optional[bytes],
    source_lang: str,
    target_lang: str,
    manager: Optional[WebSocketManager] = None,
    pipeline_metadata: Optional[Dict[str, Any]] = None,
    original_audio_url: Optional[str] = None,
    message_id: Optional[str] = None,  # Allow pre-generated message_id
    correlation_id: Optional[str] = None,
    *,
    sessions: TenantSessionManager,
) -> SessionMessage:
    """Session-Message erstellen und zur Session hinzufügen"""
    import logging

    from .audio_storage import AudioVariant, save_audio

    logger = logging.getLogger(__name__)

    resolved_message_id = message_id or str(uuid.uuid4())
    translated_audio_available = False
    if audio_bytes:
        try:
            save_audio(
                session_id,
                resolved_message_id,
                AudioVariant.TRANSLATED,
                audio_bytes,
            )
            translated_audio_available = True
        except Exception as error:
            # Logged at error, not warning: the pipeline still answers
            # successfully, so this line is the only signal that the reply
            # reached the customer with no audio to play.
            logger.exception(
                "⚠️ Failed to save translated audio: %s",
                type(error).__name__,
                exc_info=_redacted_exception_info(error),
            )

    message = SessionMessage(
        id=resolved_message_id,
        sender=client_type,
        original_text=original_text,
        translated_text=translated_text,
        audio_base64=None,
        source_lang=source_lang,
        target_lang=target_lang,
        timestamp=utc_now(),
        translated_audio_available=translated_audio_available,
        pipeline_metadata=pipeline_metadata,
        original_audio_url=original_audio_url,
    )

    # Zur Session hinzufügen
    sessions.add_message(session_id, message)

    # ✨ WebSocket Broadcasting mit differentiated content
    _log_session_event(
        "🔄 Starte WebSocket-Broadcasting",
        session_id.session_id,
        sender=client_type.value,
    )
    try:
        # Only attempt broadcasting if a WebSocketManager was provided
        if manager is not None:
            result = await broadcast_message_to_session(session_id, message, client_type, manager)
        else:
            # No manager available (e.g., unit tests running without DI)
            result = _nothing_delivered()

        # Task 4.7: Handle broadcast failures
        if result.success:
            _log_session_event(
                "✅ WebSocket-Broadcasting erfolgreich",
                session_id.session_id,
                successful_sends=result.successful_sends,
                total_connections=result.total_connections,
            )
        else:
            logger.error(
                "❌ WebSocket-Broadcasting fehlgeschlagen | %s",
                sanitize_log_value(
                    {
                        "session_ref": _safe_identifier(session_id.session_id),
                        "successful_sends": result.successful_sends,
                        "failed_sends": result.failed_sends,
                        "total_connections": result.total_connections,
                        "error_count": len(result.errors),
                    }
                ),
            )
    except Exception as e:
        logger.exception(
            "❌ WebSocket-Broadcasting-Fehler",
            exc_info=_redacted_exception_info(e),
        )
        # WebSocket-Fehler sollen den HTTP-Request nicht zum Absturz bringen

    # Only now, with every participant served, does persistence get its say.
    # Each artefact carries its own live read; the outcome decides what
    # survives termination, never what the conversation delivered.
    authorization = await authorize_message_artifacts(
        gate=sessions.runtime_policy,
        tenant_id=session_id.tenant_id,
        consent_status=_session_consent_status(session_id, sessions),
        correlation_id=correlation_id or str(uuid.uuid4()),
        has_original_audio=original_audio_url is not None,
        has_translated_audio=translated_audio_available,
    )
    message.record_authorized = authorization.record
    message.original_audio_authorized = authorization.original_audio
    message.translated_audio_authorized = authorization.translated_audio
    try:
        sessions.record_message_authorization(
            session_id,
            resolved_message_id,
            record=authorization.record,
            original_audio=authorization.original_audio,
            translated_audio=authorization.translated_audio,
        )
    except Exception:  # noqa: BLE001 - the message is already delivered
        # The policy reads leave a window in which the session can terminate,
        # and the store then refuses the write-back. Failing the request here
        # would report an error for a message the other party already has, and
        # a retry would duplicate it. The record defaults to refused, so the
        # content this loses is content nothing will retain.
        logger.warning(
            "persistence_authorization_not_recorded | %s",
            sanitize_log_value({"session_ref": _safe_identifier(session_id.session_id)}),
        )

    return message


async def broadcast_message_to_session(
    session_id: TenantSessionKey,
    message: SessionMessage,
    sender_type: ClientType,
    manager: Optional[WebSocketManager] = None,
) -> BroadcastResult:
    """
    🚀 Differentiated Message Broadcasting:
    - Sender erhält original_text (ASR-Bestätigung)
    - Empfänger erhält translated_text + audio

    Args:
        session_id: Session identifier
        message: Message to broadcast
        sender_type: Who sent the message (admin or customer)
        manager: WebSocketManager instance (injected via dependency injection)

    Returns:
        BroadcastResult with success status and metrics
    """
    _log_session_event(
        "📡 Broadcasting message",
        session_id.session_id,
        sender_type=sender_type.value,
    )

    receiver_type = ClientType.CUSTOMER if sender_type is ClientType.ADMIN else ClientType.ADMIN

    pipeline_input = (
        message.pipeline_metadata.get("input")
        if isinstance(message.pipeline_metadata, dict)
        else None
    )
    has_original_audio = bool(message.original_audio_url) or (
        isinstance(pipeline_input, dict) and pipeline_input.get("type") == "audio"
    )

    # Original Message für Sender (ASR-Bestätigung)
    sender_message: Dict[str, Any] = {
        "type": MessageType.MESSAGE.value,
        "message_id": message.id,
        "session_id": session_id.session_id,
        "text": message.original_text,  # 👈 Sender sieht original Text
        "source_lang": message.source_lang,
        "target_lang": message.target_lang,
        "sender": message.sender.value,
        "timestamp": message.timestamp.isoformat(),
        "audio_available": False,  # Sender braucht keine Audio-Bestätigung
        "role": "sender_confirmation",
    }
    # Add pipeline metadata if available
    if message.pipeline_metadata:
        sender_message["pipeline_metadata"] = scope_pipeline_audio_urls(
            message.pipeline_metadata,
            session_id,
            sender_type.value,
            message.id,
        )
    if has_original_audio:
        sender_message["original_audio_url"] = scoped_audio_url(
            session_id, sender_type.value, message.id, AudioVariant.ORIGINAL
        )

    # Translated Message für Empfänger (mit Audio)
    receiver_message: Dict[str, Any] = {
        "type": MessageType.MESSAGE.value,
        "message_id": message.id,
        "session_id": session_id.session_id,
        "text": message.translated_text,  # 👈 Empfänger sieht übersetzten Text
        "source_lang": message.source_lang,
        "target_lang": message.target_lang,
        "sender": message.sender.value,
        "timestamp": message.timestamp.isoformat(),
        "audio_available": message.translated_audio_available,
        "audio_url": (
            scoped_audio_url(
                session_id,
                receiver_type.value,
                message.id,
                AudioVariant.TRANSLATED,
            )
            if message.translated_audio_available
            else None
        ),
        "role": "receiver_message",
    }
    # Add pipeline metadata if available
    if message.pipeline_metadata:
        receiver_message["pipeline_metadata"] = scope_pipeline_audio_urls(
            message.pipeline_metadata,
            session_id,
            receiver_type.value,
            message.id,
        )
    if has_original_audio:
        receiver_message["original_audio_url"] = scoped_audio_url(
            session_id, receiver_type.value, message.id, AudioVariant.ORIGINAL
        )

    # 🎯 Differentiated Broadcasting ausführen
    _log_session_event("📤 Broadcasting differentiated content", session_id.session_id)
    if manager is None:
        # No WebSocketManager provided (e.g., unit tests without DI) -> noop
        result = _nothing_delivered()
    else:
        result = await manager.broadcast_with_differentiated_content(
            session_id=session_id,
            sender_type=sender_type,
            original_message=sender_message,
            translated_message=receiver_message,
        )
    _log_session_event(
        "✅ Broadcast completed",
        session_id.session_id,
        successful_sends=result.successful_sends,
        total_connections=result.total_connections,
    )
    return result
