# services/api_gateway/routes/customer.py
"""
Customer-Routes für Session-Management
Ermöglicht Kunden das Beitreten und Aktivieren von Sessions
"""

import logging
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..session_manager import SessionStatus, session_manager

# Logger setup
logger = logging.getLogger(__name__)

# Router setup
router = APIRouter(prefix="/api/customer", tags=["customer"])

CUSTOMER_ROUTE_RESPONSES = {
    400: {"description": "Invalid customer session request"},
    404: {"description": "Session not found"},
    500: {"description": "Customer session operation failed"},
}


# Request/Response Models
class ActivateSessionRequest(BaseModel):
    session_id: str = Field(..., description="Session ID to activate")
    customer_language: str = Field(
        ..., description="Customer's preferred language code (e.g. 'en', 'de', 'ar')"
    )

    class Config:
        json_schema_extra = {
            "example": {"session_id": "ABC12345", "customer_language": "en"}
        }


class ActivateSessionResponse(BaseModel):
    session_id: str = Field(..., description="Activated session ID")
    status: str = Field(..., description="New session status (should be 'active')")
    customer_language: str = Field(..., description="Customer language that was set")
    message: str = Field(..., description="Success message")
    timestamp: str = Field(..., description="Activation timestamp")


class ErrorResponse(BaseModel):
    error: str
    message: str
    timestamp: str
    session_id: Optional[str] = None


def utc_now() -> datetime:
    return datetime.now(UTC)


@router.post(
    "/session/activate",
    status_code=status.HTTP_200_OK,
    summary="Aktiviert eine pending Session für den Kunden",
    description="Übernimmt eine Session vom pending in den active Status. Idempotent - kann mehrmals aufgerufen werden.",
    responses=CUSTOMER_ROUTE_RESPONSES,
)
async def activate_session(request: ActivateSessionRequest) -> ActivateSessionResponse:
    """
    Aktiviert eine Session für Customer-Teilnahme

    Workflow:
    1. Admin erstellt Session → Status: pending
    2. Kunde scannt QR-Code und wählt Sprache
    3. Frontend ruft diesen Endpoint auf → Status: active
    4. Beide können jetzt Nachrichten austauschen

    Args:
        request: Session-ID und Kundensprache

    Returns:
        ActivateSessionResponse: Bestätigung der Aktivierung

    Raises:
        404: Session nicht gefunden
        400: Session bereits terminiert oder andere Validierungsfehler
    """
    try:
        logger.info(
            f"🎯 Session-Aktivierung angefordert: {request.session_id} mit Sprache: {request.customer_language}"
        )

        # Session validieren
        session = session_manager.get_session(request.session_id)
        if not session:
            logger.warning(f"❌ Session {request.session_id} nicht gefunden")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {request.session_id} nicht gefunden oder abgelaufen",
            )

        # Status prüfen
        if session.status == SessionStatus.TERMINATED:
            logger.warning(f"❌ Session {request.session_id} bereits beendet")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session {request.session_id} wurde bereits beendet und kann nicht aktiviert werden",
            )

        # Idempotenz: Bereits aktive Session
        if session.status == SessionStatus.ACTIVE:
            # Prüfen, ob Sprache geändert werden soll
            if session.customer_language != request.customer_language:
                logger.info(
                    f"🔄 Sprache wird aktualisiert: {session.customer_language} → {request.customer_language}"
                )
                await session_manager.activate_session(
                    request.session_id, request.customer_language
                )
                session = session_manager.get_session(request.session_id)  # Neu laden
            else:
                logger.info(
                    f"ℹ️ Session {request.session_id} bereits aktiv - idempotente Antwort"
                )

            return ActivateSessionResponse(
                session_id=request.session_id,
                status=session.status.value,
                customer_language=session.customer_language,
                message=f"Session {request.session_id} ist bereits aktiv",
                timestamp=utc_now().isoformat(),
            )

        # Sprache validieren (optional - die Implementierung kann erweitert werden)
        supported_languages = [
            "de",
            "en",
            "ar",
            "tr",
            "ru",
            "uk",
            "am",
            "ti",
            "ku",
            "fa",
        ]
        if request.customer_language not in supported_languages:
            logger.warning(f"⚠️ Ununterstützte Sprache: {request.customer_language}")
            # Warnung, aber nicht blockieren - der TTS-Service entscheidet final

        # Session aktivieren
        await session_manager.activate_session(
            request.session_id, request.customer_language
        )

        # Erfolgsmeldung
        logger.info(
            f"✅ Session {request.session_id} erfolgreich aktiviert mit Sprache: {request.customer_language}"
        )

        return ActivateSessionResponse(
            session_id=request.session_id,
            status="active",
            customer_language=request.customer_language,
            message=f"Session {request.session_id} wurde erfolgreich aktiviert",
            timestamp=utc_now().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"❌ Unerwarteter Fehler bei Session-Aktivierung {request.session_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler bei der Session-Aktivierung: {str(e)}",
        )


@router.get(
    "/session/{session_id}/status",
    summary="Session-Status für Kunden abrufen",
    description="Ermöglicht Kunden zu prüfen ob eine Session bereit ist",
    responses=CUSTOMER_ROUTE_RESPONSES,
)
async def get_customer_session_status(session_id: str) -> dict[str, object]:
    """
    Session-Status für Customer-Interface abrufen

    Weniger Details als die Admin-Variante, fokussiert auf Customer-Bedürfnisse
    """
    try:
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} nicht gefunden",
            )

        return {
            "session_id": session_id,
            "status": session.status.value,
            "customer_language": session.customer_language,
            "admin_connected": session.admin_connected,
            "customer_connected": session.customer_connected,
            "is_active": session.status == SessionStatus.ACTIVE,
            "can_send_messages": session.status == SessionStatus.ACTIVE,
            "created_at": session.created_at.isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Fehler beim Abrufen des Customer-Session-Status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen des Session-Status: {str(e)}",
        )


@router.get(
    "/languages/supported",
    summary="Unterstützte Sprachen für Kunden abrufen",
    description="Liste aller verfügbaren Sprachen für die Session-Aktivierung",
    responses={500: {"description": "Supported language lookup failed"}},
)
async def get_supported_languages_for_customers() -> dict[str, object]:
    """
    Customer-spezifische Sprachen-Liste

    Kann sich von der Admin-Liste unterscheiden (z.B. andere Sortierung/Gruppierung)
    """
    # Reuse die existierende Implementierung
    from .session import get_supported_languages

    return await get_supported_languages()
