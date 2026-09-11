# services/api_gateway/routes/admin.py
"""
Admin-Routes für Session-Management.
"""

import logging
from datetime import datetime, timezone
from hashlib import sha256
from types import TracebackType
from typing import Annotated, Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..audio_storage import AudioVariant
from ..auth import require_ssf_user
from ..conversation_service import conversation_service
from ..log_safety import sanitize_log_value
from ..quality_telemetry import QualityTelemetry, get_quality_telemetry
from ..realtime_ticket import (
    RealtimeTicketStore,
    RealtimeTicketUnavailable,
    realtime_ticket_store,
)
from ..session_access import require_admin_session_key
from ..session_manager import ClientType, SessionStatus, session_manager
from ..studio_runtime_flow import (
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from ..tenant_context import StudioTenantContext, require_studio_tenant_context
from ..tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey
from ..websocket import WebSocketManager, get_websocket_manager

# Logger setup
logger = logging.getLogger(__name__)

# Router setup
router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_ssf_user)]
)

ADMIN_ROUTE_RESPONSES = {
    404: {"description": "Session not found"},
    500: {"description": "Admin session operation failed"},
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
class SessionCreateResponse(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    client_url: str = Field(..., description="URL for client to join session")
    status: str = Field(..., description="Session status")
    created_at: str = Field(..., description="Session creation timestamp")
    message: str = Field(..., description="Success message")


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    customer_language: Optional[str] = None
    admin_connected: bool
    customer_connected: bool
    message_count: int
    created_at: str
    terminated_at: Optional[str] = None
    termination_reason: Optional[str] = None
    warning_at: str
    timeout_at: str


class SessionHistoryResponse(BaseModel):
    sessions: list[Dict[str, Any]]
    total_count: int
    active_sessions: list[Dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    message: str
    timestamp: str


class RealtimeTicketRequest(BaseModel):
    transport: Literal["websocket", "polling"]


class RealtimeTicketResponse(BaseModel):
    ticket: str
    expires_at: str


def _connection_payload(
    manager: WebSocketManager, key: TenantSessionKey
) -> list[dict[str, Any]]:
    connections = manager.get_session_connections(key)
    for connection in connections:
        connection["transport"] = "websocket"
    from ..websocket_polling_routes import polling_store

    connections.extend(
        {
            "transport": "polling",
            "polling_id": client.polling_id,
            "session_id": client.key.session_id,
            "client_type": client.client_type.value,
            "queued_messages": len(client.messages),
            "terminated": client.terminated,
        }
        for client in polling_store.clients.values()
        if client.key == key
    )
    return connections


@router.get("/realtime/connections")
async def list_tenant_realtime_connections(
    context: Annotated[StudioTenantContext, Depends(require_studio_tenant_context)],
    manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
) -> dict[str, object]:
    from ..websocket_polling_routes import polling_store

    connections: list[dict[str, Any]] = []
    keys = {
        key for key in manager.session_connections if isinstance(key, TenantSessionKey)
    }
    keys.update(client.key for client in polling_store.clients.values())
    for key in keys:
        if key.tenant_id == context.tenant_id:
            connections.extend(_connection_payload(manager, key))
    return {"connections": connections, "count": len(connections)}


@router.get(
    "/session/{session_id}/realtime/connections",
    responses=ADMIN_ROUTE_RESPONSES,
)
async def list_session_realtime_connections(
    session_id: str,
    key: Annotated[TenantSessionKey, Depends(require_admin_session_key)],
    manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
) -> dict[str, object]:
    connections = _connection_payload(manager, key)
    return {
        "session_id": session_id,
        "connections": connections,
        "count": len(connections),
    }


def get_realtime_ticket_store() -> RealtimeTicketStore:
    return realtime_ticket_store


@router.post(
    "/session/{session_id}/realtime-ticket",
    response_model=RealtimeTicketResponse,
    responses={
        404: {"description": "Session not found"},
        503: {"description": "Ticket store unavailable"},
    },
)
async def issue_realtime_ticket(
    session_id: str,
    request: RealtimeTicketRequest,
    key: Annotated[TenantSessionKey, Depends(require_admin_session_key)],
    store: Annotated[RealtimeTicketStore, Depends(get_realtime_ticket_store)],
) -> RealtimeTicketResponse:
    try:
        issued = store.issue(key, request.transport, ttl_seconds=60)
    except RealtimeTicketUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Realtime ticket service unavailable",
        ) from None
    return RealtimeTicketResponse(
        ticket=issued.ticket,
        expires_at=issued.expires_at.isoformat(),
    )


@router.post(
    "/session/{session_id}/message",
    summary="Process an admin message",
    responses=ADMIN_ROUTE_RESPONSES,
)
async def send_admin_message(
    session_id: str,
    request: Request,
    key: Annotated[TenantSessionKey, Depends(require_admin_session_key)],
    manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
):
    return await conversation_service.process(key, ClientType.ADMIN, request, manager)


@router.get("/session/{session_id}/messages", responses=ADMIN_ROUTE_RESPONSES)
async def get_admin_messages(
    session_id: str,
    key: Annotated[TenantSessionKey, Depends(require_admin_session_key)],
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "messages": conversation_service.messages(key, ClientType.ADMIN),
    }


@router.get(
    "/session/{session_id}/audio/{message_id}/{variant}.wav",
    responses=ADMIN_ROUTE_RESPONSES,
)
async def get_admin_audio(
    session_id: str,
    message_id: str,
    variant: AudioVariant,
    key: Annotated[TenantSessionKey, Depends(require_admin_session_key)],
) -> Response:
    return conversation_service.audio(key, message_id, variant)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_session_ref(session_id: Optional[str]) -> str:
    if not session_id:
        return "missing"
    return sha256(session_id.encode("utf-8")).hexdigest()[:12]


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
    description="Erstellt eine neue Admin-Session. Vorherige aktive Sessions werden standardmäßig aus Datenschutzgründen beendet.",
    responses={500: {"description": "Session creation failed"}},
)
async def create_admin_session(
    runtime: Annotated[
        ValidatedRuntimeConfiguration,
        Depends(require_validated_runtime_configuration),
    ],
) -> SessionCreateResponse:
    """
    Erstellt eine neue Admin-Session

    - Generiert neue Session-UUID
    - Beendet standardmäßig ältere aktive Sessions
    - Erstellt Client-URL mit embedded Session-ID
    - Sendet WebSocket-Notifications an betroffene Clients

    Returns:
        SessionCreateResponse: Session-Details und Client-URL
    """
    try:
        logger.info("🚀 Admin-Session-Erstellung gestartet")

        session = await session_manager.create_admin_session(
            runtime.context.tenant_id,
            RuntimeConfigurationSnapshot.from_configuration(runtime.configuration),
        )
        session_id = session.id

        # Client-URL generieren
        client_base_url = get_client_base_url()
        client_url = f"{client_base_url}/join/{session_id}"

        logger.info(
            "✅ Admin-Session erfolgreich erstellt | %s",
            sanitize_log_value({"session_ref": _safe_session_ref(session_id)}),
        )
        return SessionCreateResponse(
            session_id=session_id,
            client_url=client_url,
            status=session.status.value,
            created_at=session.created_at.isoformat(),
            message=f"Session {session_id} erfolgreich erstellt. Verwende diese Session-ID für den Verbindungsaufbau.",
        )

    except Exception as e:
        logger.exception(
            "❌ Fehler bei Admin-Session-Erstellung",
            exc_info=_redacted_exception_info(e),
        )
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
    context: Annotated[StudioTenantContext, Depends(require_studio_tenant_context)],
    session_id: Annotated[
        Optional[str],
        Query(description="Spezifische Session-ID, die geladen werden soll."),
    ] = None,
) -> SessionStatusResponse:
    """
    Ruft die aktuelle aktive Admin-Session ab

    Returns:
        SessionStatusResponse: Details der aktiven Session
    """
    try:
        active_session_data = session_manager.get_active_session(
            session_id=session_id,
            tenant_id=context.tenant_id,
        )

        if not active_session_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Session not found"
                    if session_id is not None
                    else "Keine aktive Admin-Session gefunden"
                ),
            )

        session_id = active_session_data["id"]
        session = session_manager.get_session(
            TenantSessionKey(context.tenant_id, session_id)
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
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
            warning_at=session.warning_at().isoformat(),
            timeout_at=session.next_timeout_at().isoformat(),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as e:
        logger.exception(
            "❌ Fehler beim Abrufen der aktuellen Session",
            exc_info=_redacted_exception_info(e),
        )
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
async def terminate_session(
    session_id: str,
    key: Annotated[TenantSessionKey, Depends(require_admin_session_key)],
) -> JSONResponse:
    """
    Beendet eine Session manuell

    Args:
        session_id: UUID der zu beendenden Session

    Returns:
        JSON-Response mit Erfolgs-/Fehlermeldung
    """
    try:
        session = session_manager.get_session(key)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        if session.status == SessionStatus.TERMINATED:
            return JSONResponse(
                content={
                    "message": f"Session {session_id} ist bereits beendet",
                    "session_id": session_id,
                    "status": "already_terminated",
                }
            )

        # Session beenden
        await session_manager.terminate_session(key, "manual_admin_termination")

        logger.info(
            "✅ Session manuell beendet | %s",
            sanitize_log_value({"session_ref": _safe_session_ref(session_id)}),
        )

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
        logger.exception(
            "❌ Fehler beim Beenden der Session",
            exc_info=_redacted_exception_info(e),
        )
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
async def get_session_history(
    context: Annotated[StudioTenantContext, Depends(require_studio_tenant_context)],
    limit: int = 10,
) -> SessionHistoryResponse:
    """
    Ruft Session-Historie für Admin-Dashboard ab

    Args:
        limit: Maximale Anzahl vergangener Sessions (default: 10)

    Returns:
        SessionHistoryResponse: Historie und aktuelle Session
    """
    try:
        # Vergangene Sessions
        history = session_manager.get_session_history(
            limit=limit, tenant_id=context.tenant_id
        )

        # Aktuelle Session
        active_sessions = session_manager.get_active_sessions(
            tenant_id=context.tenant_id
        )

        return SessionHistoryResponse(
            sessions=history, total_count=len(history), active_sessions=active_sessions
        )

    except Exception as e:
        logger.exception(
            "❌ Fehler beim Abrufen der Session-Historie",
            exc_info=_redacted_exception_info(e),
        )
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
async def get_session_status(
    session_id: str,
    key: Annotated[TenantSessionKey, Depends(require_admin_session_key)],
) -> SessionStatusResponse:
    """
    Ruft Status einer spezifischen Session ab

    Args:
        session_id: UUID der Session

    Returns:
        SessionStatusResponse: Detaillierte Session-Informationen
    """
    try:
        session = session_manager.get_session(key)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

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
            warning_at=session.warning_at().isoformat(),
            timeout_at=session.next_timeout_at().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "❌ Fehler beim Abrufen des Session-Status",
            exc_info=_redacted_exception_info(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen des Status: {str(e)}",
        )


class TelemetryProbeResponse(BaseModel):
    event_id: Optional[str] = Field(
        None, description="Generated probe event id, or null when disabled"
    )
    mode: str = Field(..., description="Effective telemetry mode")
    outcome: str = Field(
        ...,
        description=(
            "What actually happened: emitted, export_failed, "
            "dropped_disallowed, or disabled. An event_id without "
            "outcome=emitted will never appear in quality_events."
        ),
    )


@router.post(
    "/telemetry/probe",
    responses=ADMIN_ROUTE_RESPONSES,
    summary="Emit one quality telemetry probe event",
)
async def emit_telemetry_probe(
    telemetry: Annotated[QualityTelemetry, Depends(get_quality_telemetry)],
) -> TelemetryProbeResponse:
    """Emit a single allowlisted probe event. Never fails on telemetry error."""
    result = telemetry.emit_probe(event_type="telemetry_probe")
    return TelemetryProbeResponse(
        event_id=str(result.event_id) if result.event_id is not None else None,
        mode=telemetry.mode.value,
        outcome=result.outcome.value,
    )


# Note: Exception handlers werden auf App-Level registriert, nicht auf Router-Level
# Error handling erfolgt in den individuellen Route-Funktionen
