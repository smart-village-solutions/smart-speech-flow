# services/api_gateway/routes/session.py
"""
Session-Management Endpunkte für Admin-Kunde Gespräche
Erweitert das bestehende API Gateway um Session-Funktionalität
"""

import asyncio
import base64
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

# Import der bestehenden Pipeline-Logik
from services.api_gateway.pipeline_logic import process_wav
from services.api_gateway.session_manager import (
    ClientType,
    SessionMessage,
    session_manager,
)

router = APIRouter()
SESSION_NOT_FOUND_DETAIL = "Session nicht gefunden"

# Unterstützte Sprachen basierend auf TTS-Service
SUPPORTED_LANGUAGES = {
    "de": {"name": "Deutsch", "native": "Deutsch"},
    "en": {"name": "English", "native": "English"},
    "ar": {"name": "Arabic", "native": "العربية"},
    "tr": {"name": "Turkish", "native": "Türkçe"},
    "ru": {"name": "Russian", "native": "Русский"},
    "uk": {"name": "Ukrainian", "native": "Українська"},
    "am": {"name": "Amharic", "native": "አማርኛ"},
    "fa": {"name": "Persian", "native": "فارسی"},
}


@router.post("/session/create")
async def create_session(customer_language: str):
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
async def get_session_info(session_id: str):
    """Session-Informationen abrufen"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, SESSION_NOT_FOUND_DETAIL)

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
async def get_active_sessions():
    """Aktive Sessions für Admin-Übersicht"""
    return {"sessions": session_manager.get_active_sessions()}


@router.post("/session/{session_id}/message")
async def send_session_message(
    session_id: str,
    client_type: ClientType,
    file: Annotated[UploadFile, File(...)],
    source_lang: Annotated[str, Form(...)],
    target_lang: Annotated[str, Form(...)],
):
    """Neue Audio-Nachricht zur Session hinzufügen"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, SESSION_NOT_FOUND_DETAIL)

    try:
        # Nutze bestehende Pipeline-Logik
        file_bytes = await file.read()
        result = await asyncio.to_thread(
            process_wav, file_bytes, source_lang, target_lang
        )

        if result.get("error"):
            raise HTTPException(
                500, f"Pipeline-Fehler: {result.get('error_msg', 'Unbekannt')}"
            )

        # Session-Nachricht erstellen
        message = SessionMessage(
            id=str(uuid.uuid4()),
            sender=client_type,
            original_text=result["asr_text"],
            translated_text=result["translation_text"],
            audio_base64=(
                base64.b64encode(result["audio_bytes"]).decode()
                if result["audio_bytes"]
                else None
            ),
            source_lang=source_lang,
            target_lang=target_lang,
            timestamp=datetime.now(timezone.utc),
        )

        # Zur Session hinzufügen
        session_manager.add_message(session_id, message)

        return {
            "status": "success",
            "message_id": message.id,
            "original_text": message.original_text,
            "translated_text": message.translated_text,
            "audio_available": message.audio_base64 is not None,
        }

    except Exception as e:
        raise HTTPException(500, f"Fehler bei Nachrichtenverarbeitung: {str(e)}")


@router.get("/session/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Nachrichten einer Session abrufen"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, SESSION_NOT_FOUND_DETAIL)

    return {
        "session_id": session_id,
        "messages": [msg.to_dict() for msg in session.messages],
    }


@router.get("/languages/supported")
async def get_supported_languages():
    """Verfügbare Sprachen für Frontends"""
    return {
        "languages": SUPPORTED_LANGUAGES,
        "admin_default": "de",
        "popular": ["en", "ar", "tr", "ru", "fa"],  # Häufige Verwaltungssprachen
    }


@router.websocket("/ws/{session_id}/{client_type}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, client_type: str):
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
