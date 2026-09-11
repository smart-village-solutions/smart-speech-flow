# services/api_gateway/routes/customer.py
"""
Customer-Routes für Session-Management
Ermöglicht Kunden das Beitreten und Aktivieren von Sessions
"""

import logging
from datetime import datetime, timezone
from hashlib import sha256
from types import TracebackType
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..audio_storage import AudioVariant
from ..auth import optional_ssf_user
from ..conversation_service import conversation_service
from ..log_safety import safe_language_code, sanitize_log_value
from ..session_access import require_customer_session_key
from ..session_manager import ClientType, SessionStatus, session_manager
from ..tenant_session import TenantSessionKey
from ..websocket import WebSocketManager, get_websocket_manager

# Logger setup
logger = logging.getLogger(__name__)

# Router setup
router = APIRouter(prefix="/api/customer", tags=["customer"])

CUSTOMER_ROUTE_RESPONSES = {
    400: {"description": "Invalid customer session request"},
    404: {"description": "Session not found"},
    500: {"description": "Customer session operation failed"},
}
_REDACTED_EXCEPTION_MESSAGE = "Exception details redacted"


def _redacted_exception_info(
    error: Exception,
) -> tuple[type[BaseException], BaseException, Optional[TracebackType]]:
    return (
        RuntimeError,
        RuntimeError(_REDACTED_EXCEPTION_MESSAGE),
        error.__traceback__,
    )


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


@router.post(
    "/session/{session_id}/message",
    summary="Process a customer message",
    responses=CUSTOMER_ROUTE_RESPONSES,
)
async def send_customer_message(
    session_id: str,
    request: Request,
    key: Annotated[TenantSessionKey, Depends(require_customer_session_key)],
    manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
):
    return await conversation_service.process(
        key, ClientType.CUSTOMER, request, manager
    )


@router.get("/session/{session_id}/messages", responses=CUSTOMER_ROUTE_RESPONSES)
async def get_customer_messages(
    session_id: str,
    key: Annotated[TenantSessionKey, Depends(require_customer_session_key)],
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "messages": conversation_service.messages(key, ClientType.CUSTOMER),
    }


@router.get(
    "/session/{session_id}/audio/{message_id}/{variant}.wav",
    responses=CUSTOMER_ROUTE_RESPONSES,
)
async def get_customer_audio(
    session_id: str,
    message_id: str,
    variant: AudioVariant,
    key: Annotated[TenantSessionKey, Depends(require_customer_session_key)],
) -> Response:
    return conversation_service.audio(key, message_id, variant)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_session_ref(session_id: Optional[str]) -> str:
    if not session_id:
        return "missing"
    return sha256(session_id.encode("utf-8")).hexdigest()[:12]


@router.post(
    "/session/activate",
    status_code=status.HTTP_200_OK,
    summary="Aktiviert eine pending Session für den Kunden",
    description="Übernimmt eine Session vom pending in den active Status. Idempotent - kann mehrmals aufgerufen werden.",
    responses=CUSTOMER_ROUTE_RESPONSES,
)
async def activate_session(
    request: ActivateSessionRequest,
    principal: Annotated[dict[str, Any] | None, Depends(optional_ssf_user)],
) -> ActivateSessionResponse:
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
            "🎯 Session-Aktivierung angefordert | session_ref=%s customer_language=%s",
            _safe_session_ref(request.session_id),
            safe_language_code(request.customer_language),
        )

        # Session validieren
        key = require_customer_session_key(request.session_id, principal)
        session = session_manager.get_session(key)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # Status prüfen
        if session.status == SessionStatus.TERMINATED:
            logger.warning(
                "❌ Session bereits beendet | %s",
                sanitize_log_value(
                    {"session_ref": _safe_session_ref(request.session_id)}
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session {request.session_id} wurde bereits beendet und kann nicht aktiviert werden",
            )

        # Idempotenz: Bereits aktive Session
        if session.status == SessionStatus.ACTIVE:
            # Prüfen, ob Sprache geändert werden soll
            if session.customer_language != request.customer_language:
                logger.info(
                    "🔄 Sprache wird aktualisiert | %s",
                    sanitize_log_value(
                        {
                            "session_ref": _safe_session_ref(request.session_id),
                            "previous_language": session.customer_language,
                            "new_language": request.customer_language,
                        }
                    ),
                )
                await session_manager.activate_session(key, request.customer_language)
                session = session_manager.get_session(key)
            else:
                logger.info(
                    "ℹ️ Session bereits aktiv - idempotente Antwort | %s",
                    sanitize_log_value(
                        {"session_ref": _safe_session_ref(request.session_id)}
                    ),
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
            logger.warning("⚠️ Nicht unterstützte Kundensprache angefordert")
            # Warnung, aber nicht blockieren - der TTS-Service entscheidet final

        # Session aktivieren
        await session_manager.activate_session(key, request.customer_language)

        # Erfolgsmeldung
        logger.info(
            "✅ Session erfolgreich aktiviert | %s",
            sanitize_log_value(
                {
                    "session_ref": _safe_session_ref(request.session_id),
                    "customer_language": request.customer_language,
                }
            ),
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
        logger.exception(
            "❌ Unerwarteter Fehler bei Session-Aktivierung",
            exc_info=_redacted_exception_info(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler bei der Session-Aktivierung: {str(e)}",
        )


@router.get(
    "/session/{session_id}",
    summary="Session-Status für Kunden abrufen",
    description="Ermöglicht Kunden zu prüfen ob eine Session bereit ist",
    responses=CUSTOMER_ROUTE_RESPONSES,
)
async def get_customer_session_status(
    session_id: str,
    key: Annotated[TenantSessionKey, Depends(require_customer_session_key)],
) -> dict[str, object]:
    """
    Session-Status für Customer-Interface abrufen

    Weniger Details als die Admin-Variante, fokussiert auf Customer-Bedürfnisse
    """
    try:
        session = session_manager.get_session(key)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        return {
            "session_id": session_id,
            "status": session.status.value,
            "customer_language": session.customer_language,
            "admin_connected": session.admin_connected,
            "customer_connected": session.customer_connected,
            "is_active": session.status == SessionStatus.ACTIVE,
            "can_send_messages": session.status == SessionStatus.ACTIVE,
            "created_at": session.created_at.isoformat(),
            "warning_at": session.warning_at().isoformat(),
            "timeout_at": session.next_timeout_at().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "❌ Fehler beim Abrufen des Customer-Session-Status",
            exc_info=_redacted_exception_info(e),
        )
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
