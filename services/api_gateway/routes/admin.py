# services/api_gateway/routes/admin.py
"""
Admin-Routes für Session-Management
Unterstützt parallele Admin-Sessions
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..session_manager import SessionStatus, session_manager

# Logger setup
logger = logging.getLogger(__name__)

# Router setup
router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_ROUTE_RESPONSES = {
    404: {"description": "Session not found"},
    500: {"description": "Admin session operation failed"},
}


# Request/Response Models
class SessionCreateResponse(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    client_url: str = Field(..., description="URL for client to join session")
    status: str = Field(..., description="Session status")
    created_at: str = Field(..., description="Session creation timestamp")
    message: str = Field(..., description="Success message")


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    customer_language: Optional[str]
    admin_connected: bool
    customer_connected: bool
    message_count: int
    created_at: str
    terminated_at: Optional[str]
    termination_reason: Optional[str]


class SessionHistoryResponse(BaseModel):
    sessions: list[Dict[str, Any]]
    total_count: int
    active_sessions: list[Dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    message: str
    timestamp: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_client_base_url() -> str:
    """Client Frontend Base URL"""
    import os

    # Verwende Environment-Variable oder Fallback auf Production-URL
    return os.environ.get(
        "CLIENT_BASE_URL", "https://translate.smart-village.solutions"
    )


@router.post(
    "/session/create",
    status_code=status.HTTP_201_CREATED,
    summary="Neue Admin-Session erstellen",
    description="Erstellt eine neue Admin-Session. Mehrere parallele Sessions sind erlaubt.",
    responses={500: {"description": "Session creation failed"}},
)
async def create_admin_session() -> SessionCreateResponse:
    """
    Erstellt eine neue Admin-Session für parallele Nutzung

    - Generiert neue Session-UUID
    - Erstellt Client-URL mit embedded Session-ID
    - Sendet WebSocket-Notifications an betroffene Clients

    Returns:
        SessionCreateResponse: Session-Details und Client-URL
    """
    try:
        logger.info("🚀 Admin-Session-Erstellung gestartet")

        session_id = await session_manager.create_admin_session()

        # Session-Details abrufen
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Fehler bei Session-Erstellung",
            )

        # Client-URL generieren
        client_base_url = get_client_base_url()
        client_url = f"{client_base_url}/join/{session_id}"

        logger.info(f"✅ Admin-Session erfolgreich erstellt: {session_id}")
        logger.info(f"🔗 Client-URL generiert: {client_url}")

        return SessionCreateResponse(
            session_id=session_id,
            client_url=client_url,
            status=session.status.value,
            created_at=session.created_at.isoformat(),
            message=f"Session {session_id} erfolgreich erstellt. Verwende diese Session-ID für den Verbindungsaufbau.",
        )

    except Exception as e:
        logger.error(f"❌ Fehler bei Admin-Session-Erstellung: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Session-Erstellung fehlgeschlagen: {str(e)}",
        )


@router.get(
    "/session/current",
    summary="Aktuelle Admin-Session abrufen",
    description="Gibt Details der aktuell aktiven Admin-Session zurück. Optional kann eine Session-ID angegeben werden.",
    responses=ADMIN_ROUTE_RESPONSES,
)
async def get_current_session(
    session_id: Optional[str] = Query(
        default=None, description="Spezifische Session-ID, die geladen werden soll."
    )
) -> SessionStatusResponse:
    """
    Ruft die aktuelle aktive Admin-Session ab

    Returns:
        SessionStatusResponse: Details der aktiven Session
    """
    try:
        active_session_data = session_manager.get_active_session(session_id=session_id)

        if not active_session_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Keine aktive Admin-Session gefunden",
            )

        session_id = active_session_data["id"]
        session = session_manager.get_session(session_id)

        return SessionStatusResponse(
            session_id=session_id,
            status=session.status.value,
            customer_language=session.customer_language,
            admin_connected=session.admin_connected,
            customer_connected=session.customer_connected,
            message_count=len(session.messages),
            created_at=session.created_at.isoformat(),
            terminated_at=(
                session.terminated_at.isoformat() if session.terminated_at else None
            ),
            termination_reason=session.termination_reason,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Fehler beim Abrufen der aktuellen Session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Session: {str(e)}",
        )


@router.delete(
    "/session/{session_id}/terminate",
    status_code=status.HTTP_200_OK,
    summary="Session manuell beenden",
    description="Beendet eine spezifische Session manuell mit graceful cleanup",
    responses=ADMIN_ROUTE_RESPONSES,
)
async def terminate_session(session_id: str) -> JSONResponse:
    """
    Beendet eine Session manuell

    Args:
        session_id: UUID der zu beendenden Session

    Returns:
        JSON-Response mit Erfolgs-/Fehlermeldung
    """
    try:
        session = session_manager.get_session(session_id)

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} nicht gefunden",
            )

        if session.status == SessionStatus.TERMINATED:
            return JSONResponse(
                content={
                    "message": f"Session {session_id} ist bereits beendet",
                    "session_id": session_id,
                    "status": "already_terminated",
                }
            )

        # Session beenden
        await session_manager.terminate_session(session_id, "manual_admin_termination")

        logger.info(f"✅ Session {session_id} manuell beendet")

        return JSONResponse(
            content={
                "message": f"Session {session_id} erfolgreich beendet",
                "session_id": session_id,
                "status": "terminated",
                "timestamp": utc_now().isoformat(),
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Fehler beim Beenden der Session {session_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Beenden der Session: {str(e)}",
        )


@router.get(
    "/session/history",
    summary="Session-Historie abrufen",
    description="Gibt eine Liste der vergangenen Sessions und aktuelle Session zurück",
    responses={500: {"description": "Session history lookup failed"}},
)
async def get_session_history(limit: int = 10) -> SessionHistoryResponse:
    """
    Ruft Session-Historie für Admin-Dashboard ab

    Args:
        limit: Maximale Anzahl vergangener Sessions (default: 10)

    Returns:
        SessionHistoryResponse: Historie und aktuelle Session
    """
    try:
        # Vergangene Sessions
        history = session_manager.get_session_history(limit=limit)

        # Aktuelle Session
        active_sessions = session_manager.get_active_sessions()

        return SessionHistoryResponse(
            sessions=history, total_count=len(history), active_sessions=active_sessions
        )

    except Exception as e:
        logger.error(f"❌ Fehler beim Abrufen der Session-Historie: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Historie: {str(e)}",
        )


@router.get(
    "/session/{session_id}/status",
    summary="Session-Status abrufen",
    description="Gibt detaillierte Informationen über eine spezifische Session zurück",
    responses=ADMIN_ROUTE_RESPONSES,
)
async def get_session_status(session_id: str) -> SessionStatusResponse:
    """
    Ruft Status einer spezifischen Session ab

    Args:
        session_id: UUID der Session

    Returns:
        SessionStatusResponse: Detaillierte Session-Informationen
    """
    try:
        session = session_manager.get_session(session_id)

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} nicht gefunden",
            )

        return SessionStatusResponse(
            session_id=session_id,
            status=session.status.value,
            customer_language=session.customer_language,
            admin_connected=session.admin_connected,
            customer_connected=session.customer_connected,
            message_count=len(session.messages),
            created_at=session.created_at.isoformat(),
            terminated_at=(
                session.terminated_at.isoformat() if session.terminated_at else None
            ),
            termination_reason=session.termination_reason,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Fehler beim Abrufen des Session-Status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen des Status: {str(e)}",
        )


# Note: Exception handlers werden auf App-Level registriert, nicht auf Router-Level
# Error handling erfolgt in den individuellen Route-Funktionen
