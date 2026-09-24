# services/api_gateway/routes/session.py
from __future__ import annotations

"""
Session-Management Endpunkte für Admin-Kunde Gespräche
Erweitert das bestehende API Gateway um Session-Funktionalität
Enhanced with Unified Message Endpoint for Audio/Text Input
"""

import asyncio
import base64
import logging
from typing import Annotated, Any, Dict, List, Mapping, Optional, Protocol

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field

from ..message_models import SUPPORTED_LANGUAGES, ErrorResponse, iso_utc_now
from ..session_manager import (
    Session,
    SessionStatus,
)
from ..websocket import WebSocketManager, get_websocket_manager

router = APIRouter()
logger = logging.getLogger(__name__)

SESSION_NOT_FOUND_MESSAGE = "Session nicht gefunden"


class _UnscopedSessions(Protocol):
    """What the unregistered str-keyed helpers below read; only a legacy manager has it."""

    @property
    def sessions(self) -> Mapping[str, Session]: ...

    def get_session(self, session_id: str) -> Optional[Session]: ...

    def update_session_activity(self, session_id: str) -> None: ...


async def _apply_activity_update_to_session_connections(
    manager: WebSocketManager,
    session_id: str,
    activity: "ClientActivityUpdate",
) -> tuple[List[int], List[str]]:
    new_intervals: List[int] = []
    optimization_tips: List[str] = []

    # Iterate over a snapshot so disconnect cleanup cannot mutate the live dict
    # while we are awaiting polling interval updates.
    connections = list(manager.session_connections.get(session_id, {}).values())
    for connection in connections:
        old_interval = connection.current_polling_interval
        new_interval = manager.client_status.adaptive_polling.update_client_status(
            connection,
            is_mobile=activity.is_mobile,
            tab_active=activity.tab_active,
            battery_level=activity.battery_level,
            network_quality=activity.network_quality,
        )

        new_intervals.append(new_interval)
        optimization_tips.extend(
            manager.client_status.adaptive_polling.get_battery_optimization_tips(connection)
        )

        if new_interval != old_interval:
            await manager.client_status.send_polling_interval_update(
                connection, new_interval, reason="client_activity_update"
            )

    return new_intervals, optimization_tips


ManagerDependency = Annotated[
    WebSocketManager,
    Depends(get_websocket_manager),
]


BAD_REQUEST_RESPONSE = {400: {"model": ErrorResponse, "description": "Bad request"}}
NOT_FOUND_RESPONSE = {404: {"model": ErrorResponse, "description": "Not found"}}
SERVER_ERROR_RESPONSE = {500: {"model": ErrorResponse, "description": "Internal server error"}}
# Pipeline capacity is bounded (#191): one GPU hosts ASR, translation and TTS.
# Carries error_code SYSTEM_BUSY and a Retry-After header; retrying works.
SERVICE_BUSY_RESPONSE = {
    503: {
        "model": ErrorResponse,
        "description": (
            "Pipeline at capacity. Returns error_code SYSTEM_BUSY and a "
            "Retry-After header in whole seconds; the request may be retried."
        ),
        "headers": {
            "Retry-After": {
                "description": "Whole seconds to wait before retrying; never below 1.",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    }
}
MESSAGE_ROUTE_RESPONSES = {
    **BAD_REQUEST_RESPONSE,
    **NOT_FOUND_RESPONSE,
    **SERVICE_BUSY_RESPONSE,
    **SERVER_ERROR_RESPONSE,
}
ACTIVITY_ROUTE_RESPONSES = {
    **BAD_REQUEST_RESPONSE,
    **NOT_FOUND_RESPONSE,
}


# 📱 Mobile-Optimization Models


class ClientActivityUpdate(BaseModel):
    """Client-Activity-Status-Update für Mobile-Optimization"""

    is_mobile: Optional[bool] = Field(None, description="Whether client is mobile device")
    tab_active: Optional[bool] = Field(None, description="Whether tab is currently active/visible")
    battery_level: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Battery level (0.0-1.0)"
    )
    is_charging: Optional[bool] = Field(None, description="Whether device is charging")
    network_quality: Optional[str] = Field(None, description="Network quality: good, slow, offline")
    connection_type: Optional[str] = Field(
        None, description="Connection type: wifi, cellular, offline"
    )
    screen_orientation: Optional[str] = Field(
        None, description="Screen orientation: portrait, landscape"
    )


class ActivityUpdateResponse(BaseModel):
    """Response für Activity-Update"""

    status: str = Field(..., description="Update status")
    new_polling_interval: int = Field(..., description="New polling interval in seconds")
    optimization_tips: List[str] = Field(..., description="Battery/Performance optimization tips")
    session_id: str = Field(..., description="Session ID")
    timestamp: str = Field(..., description="Update timestamp")


async def get_session_messages(session_id: str, sessions: _UnscopedSessions) -> Dict[str, Any]:
    """Nachrichten einer Session abrufen"""
    session = await asyncio.to_thread(sessions.get_session, session_id)
    if not session:
        raise HTTPException(404, SESSION_NOT_FOUND_MESSAGE)

    return {
        "session_id": session_id,
        "messages": [msg.to_dict() for msg in session.messages],
    }


async def get_message_audio(message_id: str, sessions: _UnscopedSessions):
    """Audio-Datei einer Nachricht abrufen (übersetztes Audio)"""
    from fastapi.responses import Response

    # Message in allen Sessions suchen
    for session in sessions.sessions.values():
        for message in session.messages:
            if message.id == message_id and message.audio_base64:
                audio_bytes = await asyncio.to_thread(base64.b64decode, message.audio_base64)
                return Response(
                    content=audio_bytes,
                    media_type="audio/wav",
                    headers={"Content-Disposition": f"inline; filename=message_{message_id}.wav"},
                )

    raise HTTPException(404, "Audio file not found")


async def get_original_audio(message_id: str):
    """
    Original-Audio einer Nachricht abrufen (Sprecher-Aufnahme)

    Hinweis: Original-Audio wird für 24 Stunden gespeichert und dann automatisch gelöscht.
    """
    from fastapi.responses import FileResponse

    from ..audio_storage import get_audio_file_path

    # Suche Original-Audio-Datei
    filename = f"input_{message_id}.wav"
    filepath = await asyncio.to_thread(get_audio_file_path, filename)

    if filepath is None or not await asyncio.to_thread(filepath.exists):
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


async def update_client_activity(
    session_id: str,
    activity: ClientActivityUpdate,
    manager: ManagerDependency,
    sessions: _UnscopedSessions,
) -> ActivityUpdateResponse:
    """
    📱 Client-Activity-Status aktualisieren für Mobile-Optimization
    Ermöglicht adaptive Polling-Intervalle basierend auf Device-Status
    """
    # Session validieren
    session = sessions.get_session(session_id)
    if not session:
        raise HTTPException(404, SESSION_NOT_FOUND_MESSAGE)

    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(400, "Session ist nicht aktiv")

    if not manager.get_session_connections(session_id):
        raise HTTPException(400, "Keine aktiven WebSocket-Verbindungen für diese Session")

    new_intervals, optimization_tips = await _apply_activity_update_to_session_connections(
        manager, session_id, activity
    )

    # Session-Aktivität aktualisieren (für Timeout-Management)
    sessions.update_session_activity(session_id)

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


async def websocket_endpoint(websocket: WebSocket, _session_id: str, _client_type: str) -> None:
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
