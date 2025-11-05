# services/api_gateway/routes/session.py
"""
Session-Management Endpunkte für Admin-Kunde Gespräche
Erweitert das bestehende API Gateway um Session-Funktionalität
Enhanced with Unified Message Endpoint for Audio/Text Input
"""

import base64
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Import der bestehenden Pipeline-Logik
from ..pipeline_logic import process_text_pipeline, process_wav
from ..session_manager import ClientType, SessionMessage, SessionStatus, session_manager
from ..websocket import MessageType, WebSocketManager, get_websocket_manager

router = APIRouter()

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


@router.post("/session/create")
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


@router.get("/session/{session_id}")
async def get_session_info(session_id: str) -> Dict[str, Any]:
    """Session-Informationen abrufen"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session nicht gefunden")

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


@router.post("/session/{session_id}/message", response_model=MessageResponse)
async def send_unified_message(
    session_id: str,
    request: Request,
    manager: WebSocketManager = Depends(get_websocket_manager)
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
    logger.info(f"🚀 Processing message for session {session_id}")

    # Session-Validation
    logger.debug(f"🔍 Validating session {session_id}")
    session = session_manager.get_session(session_id)
    if not session:
        logger.error(f"❌ Session nicht gefunden: {session_id}")
        raise HTTPException(
            status_code=404,
            detail=create_error_response(
                "SESSION_NOT_FOUND",
                "Session not found or expired",
                {"session_id": session_id},
            ),
        )

    if session.status != SessionStatus.ACTIVE:
        logger.error(f"❌ Session nicht aktiv: {session_id}, Status: {session.status.value}")
        raise HTTPException(
            status_code=400,
            detail=create_error_response(
                "SESSION_NOT_ACTIVE",
                f"Session is not active (status: {session.status.value})",
                {"session_id": session_id, "session_status": session.status.value},
            ),
        )

    logger.info(f"✅ Session-Validation erfolgreich: {session_id}")

    # Content-Type-basierte Auto-Detection
    content_type = request.headers.get("content-type", "")
    logger.info(f"📋 Content-Type: {content_type}")

    try:
        if content_type.startswith("multipart/form-data"):
            # Audio-Pipeline
            logger.info(f"🎵 Starte Audio-Pipeline für {session_id}...")
            result = await process_audio_input(session_id, request, start_time, manager)
            logger.info(f"✅ Audio-Pipeline erfolgreich: {session_id}")
            return result
        elif content_type.startswith("application/json"):
            # Text-Pipeline
            logger.info(f"📝 Starte Text-Pipeline für {session_id}...")
            result = await process_text_input(session_id, request, start_time, manager)
            logger.info(f"✅ Text-Pipeline erfolgreich: {session_id}")
            return result
        else:
            logger.error(f"❌ Unsupported Content-Type: {content_type}")
            raise HTTPException(
                status_code=400,
                detail=create_error_response(
                    "UNSUPPORTED_CONTENT_TYPE",
                    f"Unsupported content type: {content_type}. Use multipart/form-data for audio or application/json for text.",
                    {"content_type": content_type},
                ),
            )

    except HTTPException:
        logger.info(f"⚠️ HTTPException in send_unified_message für {session_id}")
        raise
    except Exception as e:
        logger.error(f"💥 UNEXPECTED ERROR in send_unified_message für {session_id}: {e}")
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
    session_id: str, request: Request, start_time: float, manager: WebSocketManager
) -> MessageResponse:
    """Audio-Input verarbeiten (multipart/form-data)"""

    # Form-Data parsen
    form = await request.form()

    # Required fields validation
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

    file = form["file"]
    source_lang = form["source_lang"]
    target_lang = form["target_lang"]
    client_type = ClientType(form["client_type"])

    # Audio-Datei validation
    if not hasattr(file, "read"):
        raise HTTPException(
            status_code=400,
            detail=create_error_response("INVALID_FILE", "Invalid audio file", {}),
        )

    # Audio-Pipeline ausführen mit integrierter Validation
    file_bytes = await file.read()

    # Comprehensive Audio Validation
    from ..pipeline_logic import validate_audio_input

    try:
        from starlette.datastructures import UploadFile as StarletteUploadFile

        upload_file_types = (UploadFile, StarletteUploadFile)
    except ImportError:  # pragma: no cover - defensive fallback
        upload_file_types = (UploadFile,)

    should_validate_audio = isinstance(file, upload_file_types)
    if should_validate_audio:
        validation_result = validate_audio_input(file_bytes, normalize=True)

        if not validation_result.is_valid:
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

    # Language validation
    if source_lang not in SUPPORTED_LANGUAGES or target_lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=create_error_response(
                "UNSUPPORTED_LANGUAGE",
                f"Unsupported language. Source: {source_lang}, Target: {target_lang}",
                {"supported_languages": list(SUPPORTED_LANGUAGES.keys())},
            ),
        )

    # Audio-Pipeline ausführen (Validation bereits durchgeführt)
    result = process_wav(
        file_bytes, source_lang, target_lang, validate_audio=False
    )  # Skip validation da bereits gemacht

    if result.get("error", False):
        raise HTTPException(
            status_code=500,
            detail=create_error_response(
                "PIPELINE_ERROR",
                f"Audio pipeline failed: {result.get('error_msg', 'Unknown error')}",
                {"pipeline_result": result},
            ),
        )

    # Session-Message erstellen
    message = await create_session_message(
        session_id=session_id,
        client_type=client_type,
        original_text=result.get("asr_text", ""),
        translated_text=result.get("translation_text", ""),
        audio_bytes=result.get("audio_bytes"),
        source_lang=source_lang,
        target_lang=target_lang,
        manager=manager,
    )

    # Response erstellen
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
        pipeline_type="audio",
        source_lang=source_lang,
        target_lang=target_lang,
        timestamp=message.timestamp.isoformat(),
    )


async def process_text_input(
    session_id: str, request: Request, start_time: float, manager: WebSocketManager
) -> MessageResponse:
    """Text-Input verarbeiten (application/json)"""

    # JSON-Payload parsen
    try:
        body = await request.json()
        text_request = TextMessageRequest(**body)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=create_error_response(
                "INVALID_JSON", f"Invalid JSON payload: {str(e)}", {}
            ),
        )

    # Language validation
    if (
        text_request.source_lang not in SUPPORTED_LANGUAGES
        or text_request.target_lang not in SUPPORTED_LANGUAGES
    ):
        raise HTTPException(
            status_code=400,
            detail=create_error_response(
                "UNSUPPORTED_LANGUAGE",
                f"Unsupported language. Source: {text_request.source_lang}, Target: {text_request.target_lang}",
                {"supported_languages": list(SUPPORTED_LANGUAGES.keys())},
            ),
        )

    # Text-Pipeline ausführen (ASR überspringen)
    pipeline_result = process_text_pipeline(
        text_request.text, text_request.source_lang, text_request.target_lang
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

    # Session-Message erstellen
    message = await create_session_message(
        session_id=session_id,
        client_type=text_request.client_type,
        original_text=pipeline_result.get(
            "asr_text", text_request.text
        ),  # Use processed text
        translated_text=translated_text,
        audio_bytes=audio_bytes,
        source_lang=text_request.source_lang,
        target_lang=text_request.target_lang,
        manager=manager,
    )

    # Response erstellen
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
        pipeline_type="text",
        source_lang=text_request.source_lang,
        target_lang=text_request.target_lang,
        timestamp=message.timestamp.isoformat(),
    )


async def create_session_message(
    session_id: str,
    client_type: ClientType,
    original_text: str,
    translated_text: str,
    audio_bytes: Optional[bytes],
    source_lang: str,
    target_lang: str,
    manager: WebSocketManager,
) -> SessionMessage:
    """Session-Message erstellen und zur Session hinzufügen"""
    import logging
    logger = logging.getLogger(__name__)

    message = SessionMessage(
        id=str(uuid.uuid4()),
        sender=client_type,
        original_text=original_text,
        translated_text=translated_text,
        audio_base64=base64.b64encode(audio_bytes).decode() if audio_bytes else None,
        source_lang=source_lang,
        target_lang=target_lang,
        timestamp=datetime.now(),
    )

    # Zur Session hinzufügen
    session_manager.add_message(session_id, message)

    # ✨ WebSocket Broadcasting mit differentiated content
    logger.info(f"🔄 Starte WebSocket-Broadcasting für session={session_id}, sender={client_type}")
    try:
        result = await broadcast_message_to_session(session_id, message, client_type, manager)

        # Task 4.7: Handle broadcast failures
        if result.success:
            logger.info(
                f"✅ WebSocket-Broadcasting erfolgreich für {session_id}: "
                f"{result.successful_sends}/{result.total_connections} zugestellt"
            )
        else:
            logger.error(
                f"❌ WebSocket-Broadcasting fehlgeschlagen für {session_id}: "
                f"{result.successful_sends} erfolgreich, {result.failed_sends} fehlgeschlagen "
                f"von {result.total_connections} Verbindungen. "
                f"Fehler: {', '.join(result.errors)}"
            )
    except Exception as e:
        logger.error(f"❌ WebSocket-Broadcasting-Fehler für {session_id}: {e}")
        # WebSocket-Fehler sollen den HTTP-Request nicht zum Absturz bringen
        import traceback
        traceback.print_exc()

    return message


async def broadcast_message_to_session(
    session_id: str, message: SessionMessage, sender_type: ClientType, manager: WebSocketManager
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
    import logging
    logger = logging.getLogger(__name__)

    logger.info(f"📡 Broadcasting message in session {session_id} from {sender_type.value}")

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

    # 🎯 Differentiated Broadcasting ausführen
    logger.info(f"📤 Broadcasting differentiated content to session {session_id}")
    result = await manager.broadcast_with_differentiated_content(
        session_id=session_id,
        sender_type=sender_type,
        original_message=sender_message,
        translated_message=receiver_message,
    )
    logger.info(
        f"✅ Broadcast completed for session {session_id}: "
        f"{result.successful_sends}/{result.total_connections} delivered"
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
        timestamp=datetime.now().isoformat(),
    ).model_dump()


@router.get("/session/{session_id}/messages")
async def get_session_messages(session_id: str) -> Dict[str, Any]:
    """Nachrichten einer Session abrufen"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session nicht gefunden")

    return {
        "session_id": session_id,
        "messages": [msg.to_dict() for msg in session.messages],
    }


@router.get("/audio/{message_id}.wav")
async def get_message_audio(message_id: str):
    """Audio-Datei einer Nachricht abrufen"""
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


@router.get("/languages/supported")
async def get_supported_languages() -> Dict[str, Any]:
    """Verfügbare Sprachen für Frontends"""
    return {
        "languages": SUPPORTED_LANGUAGES,
        "admin_default": "de",
        "popular": ["en", "ar", "tr", "ru", "fa"],  # Häufige Verwaltungssprachen
    }


@router.post("/session/{session_id}/activity")
async def update_client_activity(
    session_id: str,
    activity: ClientActivityUpdate,
    manager: WebSocketManager = Depends(get_websocket_manager)
) -> ActivityUpdateResponse:
    """
    📱 Client-Activity-Status aktualisieren für Mobile-Optimization
    Ermöglicht adaptive Polling-Intervalle basierend auf Device-Status
    """
    # Session validieren
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session nicht gefunden")

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

    for connection_dict in session_connections:
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
            tips = manager.adaptive_polling.get_battery_optimization_tips(
                connection
            )
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
        timestamp=datetime.now().isoformat(),
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
