# services/api_gateway/routes/session.py
from __future__ import annotations

"""
Session-Management Endpunkte für Admin-Kunde Gespräche
Erweitert das bestehende API Gateway um Session-Funktionalität
Enhanced with Unified Message Endpoint for Audio/Text Input
"""

import base64
import hashlib
import inspect
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..log_safety import sanitize_log_value

# Import der bestehenden Pipeline-Logik
from ..pipeline_logic import process_text_pipeline, process_wav
from ..session_manager import ClientType, SessionMessage, SessionStatus, session_manager
from ..websocket import MessageType, WebSocketManager, get_websocket_manager

router = APIRouter()
logger = logging.getLogger(__name__)

SESSION_NOT_FOUND_MESSAGE = "Session nicht gefunden"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now() -> str:
    return utc_now().isoformat()


def _safe_identifier(value: Optional[str]) -> str:
    if not value:
        return "missing"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _log_session_event(message: str, session_id: Optional[str], **extra: Any) -> None:
    safe_extra = {"session_ref": _safe_identifier(session_id)}
    safe_extra.update(sanitize_log_value(extra))
    logger.info("%s | %s", message, safe_extra)


ManagerDependency = Annotated[
    WebSocketManager,
    Depends(get_websocket_manager),
]
OptionalManagerDependency = Annotated[
    Optional[WebSocketManager],
    Depends(get_websocket_manager),
]


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
) -> Optional[Dict[str, Any]]:
    """
    Transform pipeline debug_info to spec-compliant pipeline_metadata format.

    Args:
        debug_info: Raw debug information from pipeline_logic
        source_lang: Source language code
        target_lang: Target language code
        original_audio_url: URL to original audio input (if audio pipeline)
        message_id: Message ID for audio URL generation

    Returns:
        Spec-compliant pipeline_metadata dict or None if no debug_info
    """
    if not debug_info:
        return None

    steps = debug_info.get("steps", [])
    if not steps:
        return None

    # Build pipeline metadata according to spec
    pipeline_metadata = {
        "input": {
            "type": "audio" if original_audio_url else "text",
            "source_lang": source_lang,
        },
        "steps": [],
        "total_duration_ms": debug_info.get("total_duration_ms", 0),
        "pipeline_started_at": debug_info.get("pipeline_started_at", ""),
        "pipeline_completed_at": debug_info.get("pipeline_completed_at", ""),
    }

    # Add audio URL if available
    if original_audio_url:
        pipeline_metadata["input"]["audio_url"] = original_audio_url

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
        transformed_step["output"] = {"text": step.get("output", "")}
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
        }
    elif step_name == "tts":
        transformed_step["output"] = _build_tts_step_output(
            step, target_lang, message_id
        )

    return transformed_step


def _build_tts_step_output(
    step: Dict[str, Any], target_lang: str, message_id: Optional[str]
) -> Dict[str, Any]:
    output_value = step.get("output", "")
    if not (isinstance(output_value, str) and "audio" in output_value):
        return {}

    audio_url = (
        f"/api/audio/{message_id}.wav" if message_id else "/api/audio/unknown.wav"
    )
    return {
        "audio_url": audio_url,
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


async def _parse_audio_form(request: Request) -> tuple[Any, str, str, ClientType]:
    form = await request.form()
    required_fields = ["file", "source_lang", "target_lang", "client_type"]
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
        ClientType(form["client_type"]),
    )


def _validate_audio_file_input(file: Any) -> None:
    if hasattr(file, "read"):
        return

    raise HTTPException(
        status_code=400,
        detail=create_error_response("INVALID_FILE", "Invalid audio file", {}),
    )


def _should_validate_upload_file(file: Any) -> bool:
    try:
        from starlette.datastructures import UploadFile as StarletteUploadFile

        upload_file_types = (UploadFile, StarletteUploadFile)
    except ImportError:  # pragma: no cover - defensive fallback
        upload_file_types = (UploadFile,)

    return isinstance(file, upload_file_types)


def _validate_audio_payload(file: Any, file_bytes: bytes) -> bytes:
    if not _should_validate_upload_file(file):
        return file_bytes

    from ..pipeline_logic import validate_audio_input

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


def _supports_extended_session_message_args() -> bool:
    signature = inspect.signature(create_session_message)
    return all(
        parameter_name in signature.parameters
        for parameter_name in (
            "manager",
            "pipeline_metadata",
            "original_audio_url",
            "message_id",
        )
    )


def _store_audio_artifacts(
    message_id: str, file_bytes: bytes, audio_bytes: Optional[bytes]
) -> Optional[str]:
    from ..audio_storage import save_original_audio, save_translated_audio

    original_audio_url = None
    try:
        original_audio_b64 = base64.b64encode(file_bytes).decode()
        original_audio_url = save_original_audio(message_id, original_audio_b64)
    except Exception as e:
        logger.warning("⚠️ Failed to save original audio: %s", type(e).__name__)

    if audio_bytes:
        try:
            translated_audio_b64 = base64.b64encode(audio_bytes).decode()
            save_translated_audio(message_id, translated_audio_b64)
        except Exception as e:
            logger.warning("⚠️ Failed to save translated audio: %s", type(e).__name__)

    return original_audio_url


async def _create_session_message_with_fallback(
    *,
    session_id: str,
    client_type: ClientType,
    original_text: str,
    translated_text: str,
    audio_bytes: Optional[bytes],
    source_lang: str,
    target_lang: str,
    manager: Optional[WebSocketManager],
    pipeline_metadata: Optional[Dict[str, Any]],
    original_audio_url: Optional[str],
    message_id: str,
) -> SessionMessage:
    if _supports_extended_session_message_args():
        return await create_session_message(
            session_id=session_id,
            client_type=client_type,
            original_text=original_text,
            translated_text=translated_text,
            audio_bytes=audio_bytes,
            source_lang=source_lang,
            target_lang=target_lang,
            manager=manager,
            pipeline_metadata=pipeline_metadata,
            original_audio_url=original_audio_url,
            message_id=message_id,
        )

    return await create_session_message(
        session_id,
        client_type,
        original_text,
        translated_text,
        audio_bytes,
        source_lang,
        target_lang,
    )


def _build_message_response(
    *,
    message: SessionMessage,
    session_id: str,
    source_lang: str,
    target_lang: str,
    pipeline_type: str,
    pipeline_metadata: Optional[Dict[str, Any]],
    start_time: float,
) -> MessageResponse:
    processing_time_ms = max(1, int((time.perf_counter() - start_time) * 1000))
    return MessageResponse(
        status="success",
        message_id=message.id,
        session_id=session_id,
        original_text=message.original_text,
        translated_text=message.translated_text,
        audio_available=message.audio_base64 is not None,
        audio_url=f"/api/audio/{message.id}.wav" if message.audio_base64 else None,
        processing_time_ms=processing_time_ms,
        pipeline_type=pipeline_type,
        source_lang=source_lang,
        target_lang=target_lang,
        timestamp=message.timestamp.isoformat(),
        pipeline_metadata=pipeline_metadata,
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
                    "has_text": (
                        bool(body.get("text")) if isinstance(body, dict) else False
                    ),
                }
            ),
        )
    except Exception as e:
        logger.error("❌ Failed to parse JSON: %s", type(e).__name__)
        raise HTTPException(
            status_code=400,
            detail=create_error_response("INVALID_JSON", f"Invalid JSON: {str(e)}", {}),
        )

    try:
        return TextMessageRequest(**body)
    except ValidationError as e:
        raise _build_text_validation_error(e, body) from e


def _build_text_validation_error(
    e: ValidationError, body: Optional[Dict[str, Any]]
) -> HTTPException:
    error_details = e.errors()[0] if e.errors() else {}
    error_type = error_details.get("type", "unknown")
    field_name = error_details.get("loc", ["unknown"])[-1]

    if error_type == "string_too_long":
        max_length = error_details.get("ctx", {}).get("max_length", 500)
        actual_length = (
            len(body.get(field_name, "")) if body and field_name in body else "unknown"
        )
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


# === Pydantic Models für Unified Message Endpoint ===


class TextMessageRequest(BaseModel):
    """Request-Model für Text-Input"""

    text: str = Field(
        ..., min_length=1, max_length=500, description="Text content to translate"
    )
    source_lang: str = Field(..., description="Source language code")
    target_lang: str = Field(..., description="Target language code")
    client_type: ClientType = Field(..., description="Client type (admin or customer)")

    @field_validator("text")
    @classmethod
    def validate_text_content(cls, v):
        if not v.strip():
            raise ValueError("Text content cannot be empty")
        return v.strip()


class MessageResponse(BaseModel):
    """Unified Response-Model für Message-Endpunkt"""

    status: str = Field(..., description="Request status")
    message_id: str = Field(..., description="Unique message identifier")
    session_id: str = Field(..., description="Session identifier")

    # Message Content
    original_text: str = Field(..., description="Original/ASR text")
    translated_text: str = Field(..., description="Translated text")

    # Audio Information
    audio_available: bool = Field(..., description="Whether audio is available")
    audio_url: Optional[str] = Field(None, description="URL to audio file if available")

    # Processing Information
    processing_time_ms: int = Field(
        ..., description="Total processing time in milliseconds"
    )
    pipeline_type: str = Field(..., description="Pipeline used (audio or text)")

    # Language Information
    source_lang: str = Field(..., description="Source language")
    target_lang: str = Field(..., description="Target language")

    # Timestamps
    timestamp: str = Field(..., description="Message timestamp (ISO format)")

    # Pipeline Metadata (optional, for debugging/monitoring)
    pipeline_metadata: Optional[Dict[str, Any]] = Field(
        None, description="Detailed pipeline processing metadata"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "message_id": "msg_12345",
                "session_id": "ABC123",
                "original_text": "Hallo, wie kann ich helfen?",
                "translated_text": "Hello, how can I help?",
                "audio_available": True,
                "audio_url": "/api/audio/msg_12345.wav",
                "processing_time_ms": 2500,
                "pipeline_type": "audio",
                "source_lang": "de",
                "target_lang": "en",
                "timestamp": "2025-09-28T14:30:00Z",
            }
        }
    )


class ErrorResponse(BaseModel):
    """Error-Response-Model"""

    status: str = Field(default="error", description="Error status")
    error_code: str = Field(..., description="Error code")
    error_message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(
        None, description="Additional error details"
    )
    timestamp: str = Field(..., description="Error timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "error",
                "error_code": "SESSION_NOT_FOUND",
                "error_message": "Session not found or expired",
                "details": {"session_id": "ABC123"},
                "timestamp": "2025-09-28T14:30:00Z",
            }
        }
    )


BAD_REQUEST_RESPONSE = {400: {"model": ErrorResponse, "description": "Bad request"}}
NOT_FOUND_RESPONSE = {404: {"model": ErrorResponse, "description": "Not found"}}
SERVER_ERROR_RESPONSE = {
    500: {"model": ErrorResponse, "description": "Internal server error"}
}
MESSAGE_ROUTE_RESPONSES = {
    **BAD_REQUEST_RESPONSE,
    **NOT_FOUND_RESPONSE,
    **SERVER_ERROR_RESPONSE,
}
ACTIVITY_ROUTE_RESPONSES = {
    **BAD_REQUEST_RESPONSE,
    **NOT_FOUND_RESPONSE,
}


# 📱 Mobile-Optimization Models


class ClientActivityUpdate(BaseModel):
    """Client-Activity-Status-Update für Mobile-Optimization"""

    is_mobile: Optional[bool] = Field(
        None, description="Whether client is mobile device"
    )
    tab_active: Optional[bool] = Field(
        None, description="Whether tab is currently active/visible"
    )
    battery_level: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Battery level (0.0-1.0)"
    )
    is_charging: Optional[bool] = Field(None, description="Whether device is charging")
    network_quality: Optional[str] = Field(
        None, description="Network quality: good, slow, offline"
    )
    connection_type: Optional[str] = Field(
        None, description="Connection type: wifi, cellular, offline"
    )
    screen_orientation: Optional[str] = Field(
        None, description="Screen orientation: portrait, landscape"
    )


class ActivityUpdateResponse(BaseModel):
    """Response für Activity-Update"""

    status: str = Field(..., description="Update status")
    new_polling_interval: int = Field(
        ..., description="New polling interval in seconds"
    )
    optimization_tips: List[str] = Field(
        ..., description="Battery/Performance optimization tips"
    )
    session_id: str = Field(..., description="Session ID")
    timestamp: str = Field(..., description="Update timestamp")


# Unterstützte Sprachen basierend auf TTS-Service
SUPPORTED_LANGUAGES: Dict[str, Dict[str, str]] = {
    "de": {"name": "Deutsch", "native": "Deutsch"},
    "en": {"name": "English", "native": "English"},
    "ar": {"name": "Arabic", "native": "العربية"},
    "tr": {"name": "Turkish", "native": "Türkçe"},
    "ru": {"name": "Russian", "native": "Русский"},
    "uk": {"name": "Ukrainian", "native": "Українська"},
    "am": {"name": "Amharic", "native": "አማርኛ"},
    "ti": {"name": "Tigrinya", "native": "ትግርኛ"},
    "ku": {"name": "Kurdish", "native": "Kurmancî"},
    "fa": {"name": "Persian", "native": "فارسی"},
}


@router.post("/session/create", responses=BAD_REQUEST_RESPONSE)
async def create_session(customer_language: str) -> Dict[str, Any]:
    """Neue Session für Admin-Kunde Gespräch erstellen"""
    if customer_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Sprache '{customer_language}' nicht unterstützt")

    session_id = session_manager.create_session(customer_language)

    return {
        "session_id": session_id,
        "customer_language": customer_language,
        "admin_url": f"/admin?session={session_id}",
        "customer_url": f"/customer?session={session_id}",
        "status": "created",
    }


@router.get("/session/{session_id}", responses=NOT_FOUND_RESPONSE)
async def get_session_info(session_id: str) -> Dict[str, Any]:
    """Session-Informationen abrufen"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, SESSION_NOT_FOUND_MESSAGE)

    return {
        "id": session.id,
        "customer_language": session.customer_language,
        "admin_language": session.admin_language,
        "status": session.status,
        "created_at": session.created_at.isoformat(),
        "message_count": len(session.messages),
        "admin_connected": session.admin_connected,
        "customer_connected": session.customer_connected,
    }


@router.get("/sessions/active")
async def get_active_sessions() -> Dict[str, Any]:
    """Aktive Sessions für Admin-Übersicht"""
    return {"sessions": session_manager.get_active_sessions()}


@router.post("/session/{session_id}/message", responses=MESSAGE_ROUTE_RESPONSES)
async def send_unified_message(
    session_id: str,
    request: Request,
    manager: OptionalManagerDependency = None,
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

    start_time = time.perf_counter()
    _log_session_event("🚀 Processing message", session_id)

    # Session-Validation
    logger.debug("🔍 Validating session")
    session = session_manager.get_session(session_id)
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
            _log_session_event("🎵 Starte Audio-Pipeline", session_id)
            result = await process_audio_input(session_id, request, start_time, manager)
            _log_session_event("✅ Audio-Pipeline erfolgreich", session_id)
            return result
        elif content_type.startswith("application/json"):
            # Text-Pipeline
            _log_session_event("📝 Starte Text-Pipeline", session_id)
            result = await process_text_input(session_id, request, start_time, manager)
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

    except HTTPException:
        _log_session_event("⚠️ HTTPException in send_unified_message", session_id)
        raise
    except Exception as e:
        _log_session_event(
            "💥 Unexpected error in send_unified_message",
            session_id,
            error_type=type(e).__name__,
        )
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=create_error_response(
                "PROCESSING_ERROR",
                f"Error processing message: {str(e)}",
                {"session_id": session_id, "error_details": str(e)},
            ),
        )


async def process_audio_input(
    session_id: str,
    request: Request,
    start_time: float,
    manager: Optional[WebSocketManager] = None,
) -> MessageResponse:
    """Audio-Input verarbeiten (multipart/form-data)"""
    file, source_lang, target_lang, client_type = await _parse_audio_form(request)

    # Validate languages match session configuration
    session = session_manager.get_session(session_id)
    if session:
        validate_session_languages(session, source_lang, target_lang, client_type)

    _validate_audio_file_input(file)
    file_bytes = await file.read()
    processed_file_bytes = _validate_audio_payload(file, file_bytes)
    _validate_supported_languages(source_lang, target_lang)

    # Audio-Pipeline ausführen (Validation bereits durchgeführt)
    result = process_wav(
        processed_file_bytes, source_lang, target_lang, validate_audio=False
    )

    if result.get("error", False):
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
    original_audio_url = _store_audio_artifacts(message_id, file_bytes, audio_bytes)

    pipeline_metadata = transform_pipeline_metadata(
        result.get("debug"), source_lang, target_lang, original_audio_url, message_id
    )

    message = await _create_session_message_with_fallback(
        session_id=session_id,
        client_type=client_type,
        original_text=result.get("asr_text", ""),
        translated_text=result.get("translation_text", ""),
        audio_bytes=audio_bytes,
        source_lang=source_lang,
        target_lang=target_lang,
        manager=manager,
        pipeline_metadata=pipeline_metadata,
        original_audio_url=original_audio_url,
        message_id=message_id,
    )
    message.id = message_id
    return _build_message_response(
        message=message,
        session_id=session_id,
        source_lang=source_lang,
        target_lang=target_lang,
        pipeline_type="audio",
        pipeline_metadata=pipeline_metadata,
        start_time=start_time,
    )


async def process_text_input(
    session_id: str,
    request: Request,
    start_time: float,
    manager: Optional[WebSocketManager] = None,
) -> MessageResponse:
    """Text-Input verarbeiten (application/json)"""
    text_request = await _parse_text_request(request)

    # Language validation
    logger.info(
        "🔍 Starting language validation for text request | %s",
        sanitize_log_value(
            {
                "source_lang": text_request.source_lang,
                "target_lang": text_request.target_lang,
                "client_type": text_request.client_type.value,
            }
        ),
    )
    _validate_supported_languages(text_request.source_lang, text_request.target_lang)

    # Validate languages match session configuration
    session = session_manager.get_session(session_id)
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
            text_request.client_type,
        )
    else:
        logger.warning(
            "⚠️ Session not found for language validation - skipping check | %s",
            sanitize_log_value({"session_ref": _safe_identifier(session_id)}),
        )

    # Text-Pipeline ausführen (ASR überspringen)
    pipeline_result = process_text_pipeline(
        text_request.text,
        text_request.source_lang,
        text_request.target_lang,
        session_id=session_id,
    )

    # Fehlerbehandlung
    if pipeline_result.get("error"):
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

    message = await _create_session_message_with_fallback(
        session_id=session_id,
        client_type=text_request.client_type,
        original_text=pipeline_result.get("asr_text", text_request.text),
        translated_text=translated_text,
        audio_bytes=audio_bytes,
        source_lang=text_request.source_lang,
        target_lang=text_request.target_lang,
        manager=manager,
        pipeline_metadata=pipeline_metadata,
        original_audio_url=None,
        message_id=message_id,
    )

    return _build_message_response(
        message=message,
        session_id=session_id,
        source_lang=text_request.source_lang,
        target_lang=text_request.target_lang,
        pipeline_type="text",
        pipeline_metadata=pipeline_metadata,
        start_time=start_time,
    )


async def create_session_message(
    session_id: str,
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
) -> SessionMessage:
    """Session-Message erstellen und zur Session hinzufügen"""
    import logging

    logger = logging.getLogger(__name__)

    message = SessionMessage(
        id=message_id or str(uuid.uuid4()),  # Use provided ID or generate new one
        sender=client_type,
        original_text=original_text,
        translated_text=translated_text,
        audio_base64=base64.b64encode(audio_bytes).decode() if audio_bytes else None,
        source_lang=source_lang,
        target_lang=target_lang,
        timestamp=utc_now(),
        pipeline_metadata=pipeline_metadata,
        original_audio_url=original_audio_url,
    )

    # Zur Session hinzufügen
    session_manager.add_message(session_id, message)

    # ✨ WebSocket Broadcasting mit differentiated content
    _log_session_event(
        "🔄 Starte WebSocket-Broadcasting",
        session_id,
        sender=client_type.value,
    )
    try:
        # Only attempt broadcasting if a WebSocketManager was provided
        if manager is not None:
            result = await broadcast_message_to_session(
                session_id, message, client_type, manager
            )
        else:
            # No manager available (e.g., unit tests running without DI)
            # Return a noop-like result object to keep behaviour consistent
            class _NoopResult:
                success = True
                total_connections = 0
                successful_sends = 0
                failed_sends = 0
                session_has_connections = False
                errors = []

            result = _NoopResult()

        # Task 4.7: Handle broadcast failures
        if result.success:
            _log_session_event(
                "✅ WebSocket-Broadcasting erfolgreich",
                session_id,
                successful_sends=result.successful_sends,
                total_connections=result.total_connections,
            )
        else:
            logger.error(
                "❌ WebSocket-Broadcasting fehlgeschlagen | %s",
                sanitize_log_value(
                    {
                        "session_ref": _safe_identifier(session_id),
                        "successful_sends": result.successful_sends,
                        "failed_sends": result.failed_sends,
                        "total_connections": result.total_connections,
                        "error_count": len(result.errors),
                    }
                ),
            )
    except Exception as e:
        logger.error(
            "❌ WebSocket-Broadcasting-Fehler | %s",
            sanitize_log_value(
                {
                    "session_ref": _safe_identifier(session_id),
                    "error_type": type(e).__name__,
                }
            ),
        )
        # WebSocket-Fehler sollen den HTTP-Request nicht zum Absturz bringen
        import traceback

        traceback.print_exc()

    return message


async def broadcast_message_to_session(
    session_id: str,
    message: SessionMessage,
    sender_type: ClientType,
    manager: Optional[WebSocketManager] = None,
):
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
        session_id,
        sender_type=sender_type.value,
    )

    # Original Message für Sender (ASR-Bestätigung)
    sender_message = {
        "type": MessageType.MESSAGE.value,
        "message_id": message.id,
        "session_id": session_id,
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
        sender_message["pipeline_metadata"] = message.pipeline_metadata
    if message.original_audio_url:
        sender_message["original_audio_url"] = message.original_audio_url

    # Translated Message für Empfänger (mit Audio)
    receiver_message = {
        "type": MessageType.MESSAGE.value,
        "message_id": message.id,
        "session_id": session_id,
        "text": message.translated_text,  # 👈 Empfänger sieht übersetzten Text
        "source_lang": message.source_lang,
        "target_lang": message.target_lang,
        "sender": message.sender.value,
        "timestamp": message.timestamp.isoformat(),
        "audio_available": message.audio_base64 is not None,
        "audio_url": f"/api/audio/{message.id}.wav" if message.audio_base64 else None,
        "role": "receiver_message",
    }
    # Add pipeline metadata if available
    if message.pipeline_metadata:
        receiver_message["pipeline_metadata"] = message.pipeline_metadata
    if message.original_audio_url:
        receiver_message["original_audio_url"] = message.original_audio_url

    # 🎯 Differentiated Broadcasting ausführen
    _log_session_event("📤 Broadcasting differentiated content", session_id)
    if manager is None:
        # No WebSocketManager provided (e.g., unit tests without DI) -> noop
        class _NoopResult:
            success = True
            total_connections = 0
            successful_sends = 0
            failed_sends = 0
            session_has_connections = False
            errors = []

        result = _NoopResult()
    else:
        result = await manager.broadcast_with_differentiated_content(
            session_id=session_id,
            sender_type=sender_type,
            original_message=sender_message,
            translated_message=receiver_message,
        )
    _log_session_event(
        "✅ Broadcast completed",
        session_id,
        successful_sends=result.successful_sends,
        total_connections=result.total_connections,
    )
    return result


def create_error_response(
    error_code: str, error_message: str, details: Dict[str, Any]
) -> Dict[str, Any]:
    """Standardisierte Error-Response erstellen"""
    return ErrorResponse(
        error_code=error_code,
        error_message=error_message,
        details=details,
        timestamp=iso_utc_now(),
    ).model_dump()


@router.get("/session/{session_id}/messages", responses=NOT_FOUND_RESPONSE)
async def get_session_messages(session_id: str) -> Dict[str, Any]:
    """Nachrichten einer Session abrufen"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, SESSION_NOT_FOUND_MESSAGE)

    return {
        "session_id": session_id,
        "messages": [msg.to_dict() for msg in session.messages],
    }


@router.get("/audio/{message_id}.wav", responses=NOT_FOUND_RESPONSE)
async def get_message_audio(message_id: str):
    """Audio-Datei einer Nachricht abrufen (übersetztes Audio)"""
    from fastapi.responses import Response

    # Message in allen Sessions suchen
    for session in session_manager.sessions.values():
        for message in session.messages:
            if message.id == message_id and message.audio_base64:
                audio_bytes = base64.b64decode(message.audio_base64)
                return Response(
                    content=audio_bytes,
                    media_type="audio/wav",
                    headers={
                        "Content-Disposition": f"inline; filename=message_{message_id}.wav"
                    },
                )

    raise HTTPException(404, "Audio file not found")


@router.get("/audio/input_{message_id}.wav", responses=NOT_FOUND_RESPONSE)
async def get_original_audio(message_id: str):
    """
    Original-Audio einer Nachricht abrufen (Sprecher-Aufnahme)

    Hinweis: Original-Audio wird für 24 Stunden gespeichert und dann automatisch gelöscht.
    """
    from fastapi.responses import FileResponse

    from ..audio_storage import get_audio_file_path

    # Suche Original-Audio-Datei
    filename = f"input_{message_id}.wav"
    filepath = get_audio_file_path(filename)

    if filepath is None or not filepath.exists():
        raise HTTPException(
            404,
            detail={
                "error_code": "AUDIO_NOT_FOUND",
                "error_message": "Original audio file not found or has been deleted (24h retention)",
                "message_id": message_id,
                "retention_policy": "24 hours",
            },
        )

    # Datei zurückgeben
    return FileResponse(
        path=str(filepath),
        media_type="audio/wav",
        headers={"Content-Disposition": f"inline; filename=input_{message_id}.wav"},
    )


@router.get("/languages/supported")
async def get_supported_languages() -> Dict[str, Any]:
    """Verfügbare Sprachen für Frontends"""
    return {
        "languages": SUPPORTED_LANGUAGES,
        "admin_default": "de",
        "popular": ["en", "ar", "tr", "ru", "fa"],  # Häufige Verwaltungssprachen
    }


@router.post("/session/{session_id}/activity", responses=ACTIVITY_ROUTE_RESPONSES)
async def update_client_activity(
    session_id: str,
    activity: ClientActivityUpdate,
    manager: ManagerDependency,
) -> ActivityUpdateResponse:
    """
    📱 Client-Activity-Status aktualisieren für Mobile-Optimization
    Ermöglicht adaptive Polling-Intervalle basierend auf Device-Status
    """
    # Session validieren
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, SESSION_NOT_FOUND_MESSAGE)

    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(400, "Session ist nicht aktiv")

    # Aktive WebSocket-Verbindungen für diese Session finden
    session_connections = manager.get_session_connections(session_id)

    if not session_connections:
        raise HTTPException(
            400, "Keine aktiven WebSocket-Verbindungen für diese Session"
        )

    # Activity-Update für alle Verbindungen der Session anwenden
    new_intervals = []
    optimization_tips = []

    for _ in session_connections:
        # Connection-Objekt aus all_connections holen
        connection_id = None
        for conn_id, conn in manager.all_connections.items():
            if conn.session_id == session_id:
                connection_id = conn_id
                connection = conn
                break

        if connection_id and connection:
            # Status aktualisieren
            old_interval = connection.current_polling_interval
            new_interval = manager.adaptive_polling.update_client_status(
                connection,
                is_mobile=activity.is_mobile,
                tab_active=activity.tab_active,
                battery_level=activity.battery_level,
                network_quality=activity.network_quality,
            )

            new_intervals.append(new_interval)
            tips = manager.adaptive_polling.get_battery_optimization_tips(connection)
            optimization_tips.extend(tips)

            # WebSocket-Notification senden falls Intervall sich geändert hat
            if new_interval != old_interval:
                await manager._send_polling_interval_update(
                    connection, new_interval, reason="client_activity_update"
                )

    # Session-Aktivität aktualisieren (für Timeout-Management)
    session_manager.update_session_activity(session_id)

    # Response zusammenstellen
    avg_interval = int(sum(new_intervals) / len(new_intervals)) if new_intervals else 5
    unique_tips = list(set(optimization_tips))

    return ActivityUpdateResponse(
        status="success",
        new_polling_interval=avg_interval,
        optimization_tips=unique_tips[:3],  # Max 3 Tips
        session_id=session_id,
        timestamp=iso_utc_now(),
    )


@router.websocket("/ws/{session_id}/{client_type}")
async def websocket_endpoint(
    websocket: WebSocket, session_id: str, client_type: str
) -> None:
    """WebSocket für Echtzeit-Updates (optional für später)"""
    await websocket.accept()

    try:
        # Für jetzt nur Verbindung aufrecht erhalten
        while True:
            data = await websocket.receive_text()
            # Echo für Heartbeat
            await websocket.send_text(f"pong: {data}")

    except WebSocketDisconnect:
        pass
