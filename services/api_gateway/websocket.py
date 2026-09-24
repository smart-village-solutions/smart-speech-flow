# services/api_gateway/websocket.py
"""
WebSocket Management für bidirektionale Echtzeit-Kommunikation
Features:
- Session-basierte Connection-Pools
- Graceful-Disconnect bei Session-Termination
- Heartbeat-System für Connection-Health
- Polling-Fallback bei WebSocket-Problemen
- Auto-Reconnect mit exponential backoff
"""

import asyncio
import logging
import os
import re
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, WebSocket, WebSocketDisconnect

from .client_origin import configured_client_origin
from .dependencies import get_realtime_ticket_store, get_session_manager, get_websocket_manager
from .log_safety import sanitize_log_value
from .realtime_client_status import AdaptivePollingManager, ClientStatusHandler
from .realtime_connection import WebSocketConnection, safe_identifier, utc_now
from .realtime_dispatch import BroadcastDispatcher, BroadcastResult
from .realtime_heartbeat import Heartbeat
from .realtime_protocol import (
    ConnectionState,
    Frame,
    MessageType,
    SessionTerminatedFrame,
    client_joined_frame,
    client_left_frame,
    connection_ack_frame,
    disconnecting_frame,
    error_frame,
    relayed_message_frame,
    session_terminated_frame,
    typing_frame,
)
from .realtime_registry import ConnectionRegistry
from .realtime_ticket import RealtimeTicketStore, RealtimeTicketUnavailable
from .session_access import require_customer_session_key
from .session_manager import ClientType, SessionRegistry, SessionStatus, TenantSessionManager
from .tenant_session import TenantSessionKey
from .websocket_monitor import DisconnectReason, WebSocketMonitor

if TYPE_CHECKING:
    from .websocket_polling_routes import TenantPollingStore

# === Logging Setup ===
logger = logging.getLogger(__name__)
_SESSION_NOT_FOUND = "Session not found"


def _localhost_origin_prefixes() -> tuple[str, str]:
    return (f"{'http'}://localhost", f"{'https'}://localhost")


# === Origin Validation for WebSocket Connections ===
async def validate_websocket_origin(origin: Optional[str]) -> bool:
    """
    Validate WebSocket origin against allowed origins
    """
    await asyncio.sleep(0)

    # Development environment - mehr permissive Regeln
    environment = os.environ.get("ENVIRONMENT", "production")
    if environment == "development":
        # Erlaube fehlende Origin-Header in Development (für Tests)
        if not origin:
            return True

        # Erlaube alle localhost Origins
        if origin.startswith(_localhost_origin_prefixes()):
            return True

        # Allow configured development origins
        dev_origins = os.environ.get("DEVELOPMENT_CORS_ORIGINS", "").split(",")
        dev_origins = [o.strip() for o in dev_origins if o.strip()]
        if origin in dev_origins:
            return True

        # In Development auch Origins ohne explizite Konfiguration erlauben
        # Das hilft bei Tests und lokaler Entwicklung
        return True

    # Production environment - strict validation
    if not origin:
        return False  # Reject connections without Origin header in production

    if origin == configured_client_origin():
        return True

    # ✅ FIX: Korrektes Regex-Pattern (* → .*)
    production_pattern = r"https://.*\.figma\.site|https://.*\.smart-village\.solutions"
    return bool(re.fullmatch(production_pattern, origin))


# RFC 6455 close codes, mapped onto the wire reasons DisconnectReason.from_wire
# understands. A WebSocketDisconnect carries the code, and treating them all as
# a clean client exit is what hid network and server failures from the
# unexpected-disconnect KPI and WebSocketConnectionFailures.
_CLOSE_CODE_REASONS = {
    1000: "client_disconnect",  # normal closure
    1001: "client_disconnect",  # going away: tab closed, navigation
    1005: "client_disconnect",  # close frame carried no code
    1002: "protocol_error",
    1003: "protocol_error",  # unsupported data
    1007: "protocol_error",  # invalid payload
    1008: "protocol_error",  # policy violation
    1009: "protocol_error",  # message too big
    1010: "protocol_error",  # mandatory extension missing
    1006: "connection_error",  # abnormal closure: no close frame at all
    1011: "connection_error",  # internal server error
    1012: "connection_error",  # service restart
    1013: "connection_error",  # try again later
    1014: "connection_error",  # bad gateway
    1015: "connection_error",  # TLS handshake failure
}


def disconnect_reason_for_close_code(code: Optional[int]) -> str:
    """Classify a WebSocket close code into a disconnect reason.

    An unrecognised code is a connection error, not a clean exit -- the same
    rule DisconnectReason.from_wire applies to unrecognised wire reasons.
    """
    if code is None:
        return "connection_error"
    return _CLOSE_CODE_REASONS.get(code, "connection_error")


class WebSocketManager:
    """
    Erweiterte WebSocket-Verwaltung mit Session-basierter Organisation

    A facade over the app's realtime collaborators: the connection registry,
    the broadcast dispatcher, the heartbeat and the client-status handler. It
    keeps the socket lifecycle (connect, disconnect, session termination) and
    the dispatch of inbound frames. The session manager, the conversation
    service, the routes and the lifespan hold only this object.
    """

    def __init__(
        self,
        session_manager: SessionRegistry[TenantSessionKey],
        polling_store: Optional["TenantPollingStore"] = None,
        *,
        monitor: WebSocketMonitor,
    ):
        self.session_manager = session_manager
        self.session_manager.register_websocket_manager(self)
        self.polling_store = polling_store
        self.monitor = monitor

        self.registry = ConnectionRegistry()
        self.dispatcher = BroadcastDispatcher(self.registry, polling_store, monitor)
        self.heartbeat = Heartbeat(self.registry, monitor, self)
        # 📱 Mobile-Optimization
        self.client_status = ClientStatusHandler(AdaptivePollingManager())

        # Auto-Reconnect Configuration
        self.max_reconnect_attempts = 5
        self.base_reconnect_delay = 1  # Sekunden (exponential backoff)

        logger.info("🔗 WebSocketManager initialisiert")

    @property
    def session_connections(self) -> Dict[TenantSessionKey, Dict[str, WebSocketConnection]]:
        return self.registry.session_connections

    @property
    def all_connections(self) -> Dict[str, WebSocketConnection]:
        return self.registry.all_connections

    @property
    def heartbeat_interval(self) -> float:
        return self.heartbeat.interval

    @heartbeat_interval.setter
    def heartbeat_interval(self, seconds: float) -> None:
        self.heartbeat.interval = seconds

    @property
    def heartbeat_timeout(self) -> float:
        return self.heartbeat.timeout

    @heartbeat_timeout.setter
    def heartbeat_timeout(self, seconds: float) -> None:
        self.heartbeat.timeout = seconds

    async def start_heartbeat_system(self) -> None:
        """Startet das Heartbeat-Überwachungssystem"""
        await self.heartbeat.start()

    async def stop_heartbeat_system(self) -> None:
        """Stoppt das Heartbeat-System"""
        await self.heartbeat.stop()

    async def connect_websocket(
        self,
        websocket: WebSocket,
        session_id: TenantSessionKey,
        client_type: ClientType,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        WebSocket-Verbindung herstellen und zu Session-Pool hinzufügen
        Returns: connection_id für Tracking
        """
        await websocket.accept()

        session = self.session_manager.get_session(session_id)
        if session is None or session.status == SessionStatus.TERMINATED:
            await websocket.close(code=4404, reason=_SESSION_NOT_FOUND)
            raise RuntimeError("Session unavailable")

        # Connection-ID generieren
        connection_id = self.registry.build_connection_id(session_id, client_type)
        public_session_id = session_id.session_id

        # 📱 Mobile-Detection aus client_info
        is_mobile = False
        battery_level = 1.0
        network_quality = "good"

        if client_info:
            is_mobile = client_info.get("is_mobile", False)
            battery_level = client_info.get("battery_level", 1.0)
            network_quality = client_info.get("network_quality", "good")

        # Connection-Objekt erstellen
        connection = WebSocketConnection(
            websocket=websocket,
            client_type=client_type,
            session_id=public_session_id,
            connected_at=utc_now(),
            last_heartbeat=utc_now(),
            state=ConnectionState.CONNECTED,
            client_info=client_info,
            key=session_id,
            # 📱 Mobile-Optimization
            is_mobile=is_mobile,
            tab_active=True,  # Initial aktiv
            battery_level=battery_level,
            network_quality=network_quality,
        )

        # 📱 Optimales Polling-Intervall berechnen
        optimal_interval = self.client_status.adaptive_polling.get_optimal_interval(connection)
        connection.current_polling_interval = optimal_interval

        # Session-Manager integrieren
        try:
            await self.session_manager.add_websocket_connection(session_id, client_type, websocket)
        except KeyError:
            await websocket.close(code=4404, reason=_SESSION_NOT_FOUND)
            raise RuntimeError("Session unavailable") from None

        # Commit the registry only after tenant presence succeeds. A session
        # termination that wins the preceding await cannot leave a live entry.
        self.registry.add(connection_id, connection)

        # 📊 Monitoring: Connection established
        origin = client_info.get("origin") if client_info else None
        self.monitor.connection_established(
            connection_id=connection_id,
            session_id=safe_identifier(public_session_id),
            client_type=client_type.value,
            origin=origin,
            resource_key=session_id,
        )

        # Stats aktualisieren
        self.registry.connection_stats["total_connections"] += 1
        self.registry.update_active_connections_count()

        # Connection-Bestätigung senden
        await self._send_connection_ack(connection)

        # Heartbeat-System starten falls noch nicht aktiv
        await self.start_heartbeat_system()

        logger.info(
            "websocket_connected tenant_ref=%s session_ref=%s client_type=%s",
            session_id.tenant_ref,
            safe_identifier(public_session_id),
            client_type.value,
        )

        # Anderen Clients in der Session mitteilen
        await self._broadcast_client_joined(session_id, client_type, connection_id)

        return connection_id

    async def disconnect_websocket(
        self, connection_id: str, reason: str = "client_disconnect", code: int = 1000
    ) -> None:
        """
        WebSocket-Verbindung graceful trennen
        """
        connection = self.registry.get(connection_id)
        if not connection:
            return

        connection.state = ConnectionState.DISCONNECTING

        try:
            # Disconnect-Nachricht senden
            await self._send_disconnect_message(connection, reason)

            # WebSocket schließen
            if connection.websocket.client_state != connection.websocket.client_state.DISCONNECTED:
                await connection.websocket.close(code=code, reason=reason)

        except Exception as e:
            logger.warning(
                f"⚠️ Fehler beim Schließen der WebSocket-Verbindung {connection_id}: {e}"
            )

        finally:
            # Connection-Cleanup
            await self.release_connection(connection_id, DisconnectReason.from_wire(reason))

            # Anderen Clients mitteilen
            await self._broadcast_client_left(
                connection.key,
                connection.client_type,
                connection_id,
                reason,
            )

    async def handle_session_termination(
        self, session_id: TenantSessionKey, reason: str = "session_ended"
    ) -> None:
        """
        Alle WebSocket-Verbindungen einer Session graceful beenden
        """
        if self.registry.session(session_id) is None:
            return

        connections = self.registry.pop_session(session_id)
        for connection in connections:
            connection.state = ConnectionState.DISCONNECTING
        public_session_id = session_id.session_id
        logger.info(
            "websocket_session_terminating session_ref=%s connections=%d",
            safe_identifier(public_session_id),
            len(connections),
        )

        # Termination-Nachricht an alle Clients senden
        termination_message = session_terminated_frame(public_session_id, reason)

        # Parallel alle Verbindungen benachrichtigen und schließen
        disconnect_tasks: list[Coroutine[Any, Any, None]] = []
        for connection in connections:
            disconnect_tasks.append(
                self._disconnect_connection_with_message(connection, termination_message)
            )

        if disconnect_tasks:
            await asyncio.gather(*disconnect_tasks, return_exceptions=True)

        logger.info(
            "websocket_session_terminated session_ref=%s",
            safe_identifier(public_session_id),
        )

    async def broadcast_to_session(
        self,
        session_id: TenantSessionKey,
        message: Frame,
        exclude_connection: Optional[str] = None,
        target_client_type: Optional[ClientType] = None,
        include_polling: bool = True,
    ) -> None:
        """
        Nachricht an alle Clients einer Session broadcasten
        """
        await self.dispatcher.broadcast_to_session(
            session_id,
            message,
            exclude_connection=exclude_connection,
            target_client_type=target_client_type,
            include_polling=include_polling,
        )

    async def broadcast_with_differentiated_content(
        self,
        session_id: TenantSessionKey,
        sender_type: ClientType,
        original_message: Frame,
        translated_message: Frame,
    ) -> BroadcastResult:
        """
        Differentiated Broadcasting: der Sender erhält original_text, der Empfänger
        translated_text + audio.
        """
        return await self.dispatcher.broadcast_with_differentiated_content(
            session_id, sender_type, original_message, translated_message
        )

    async def handle_websocket_message(self, connection_id: str, message: Dict[str, Any]) -> None:
        """
        Eingehende WebSocket-Nachrichten verarbeiten
        """
        connection = self.registry.get(connection_id)
        if not connection:
            return

        if connection.state is not ConnectionState.CONNECTED:
            return
        session = self.session_manager.get_session(connection.key)
        if session is None or session.status == SessionStatus.TERMINATED:
            connection.state = ConnectionState.DISCONNECTING
            return

        message_type = message.get("type")

        if message_type == MessageType.HEARTBEAT_PONG.value:
            await self.heartbeat.handle_pong(connection_id, connection, message)

        elif message_type == MessageType.MESSAGE.value:
            await self._handle_client_message(connection, message)

        elif message_type == MessageType.TYPING_INDICATOR.value:
            await self._handle_typing_indicator(connection, message)

        # 📱 Mobile-Optimization Messages
        elif message_type == MessageType.TAB_VISIBILITY_CHANGE.value:
            await self.client_status.handle_tab_visibility_change(connection, message)

        elif message_type == MessageType.BATTERY_STATUS_UPDATE.value:
            await self.client_status.handle_battery_status_update(connection, message)

        elif message_type == MessageType.NETWORK_STATUS_CHANGE.value:
            await self.client_status.handle_network_status_change(connection, message)

        else:
            logger.warning(
                "⚠️ Unbekannter Message-Type: %s",
                sanitize_log_value(message_type),
            )

    def get_connection_stats(self) -> Dict[str, Any]:
        """
        WebSocket-Verbindungsstatistiken für Monitoring
        """
        self.registry.update_active_connections_count()

        # Session-Stats
        session_stats: Dict[TenantSessionKey, Dict[str, Any]] = {}
        for session_id, connections in self.registry.session_connections.items():
            session_stats[session_id] = {
                "total_connections": len(connections),
                "active_connections": sum(1 for c in connections.values() if c.is_alive()),
                "client_types": list(
                    {connection.client_type.value for connection in connections.values()}
                ),
            }

        return {
            "global_stats": self.registry.connection_stats,
            "session_stats": session_stats,
            "heartbeat_active": self.heartbeat.active,
        }

    def get_session_connections(self, session_id: TenantSessionKey) -> List[Dict[str, Any]]:
        """
        Verbindungen einer Session für Debugging/Monitoring
        """
        connections = self.registry.session(session_id)
        if connections is None:
            return []

        return [connection.to_dict() for connection in connections.values()]

    async def release_connection(
        self,
        connection_id: str,
        reason: DisconnectReason = DisconnectReason.CLIENT_DISCONNECT,
    ) -> None:
        """
        Connection-Cleanup nach Disconnect
        """
        connection = self.registry.get(connection_id)
        if not connection:
            return

        connection.state = ConnectionState.DISCONNECTED
        self.registry.remove(connection_id)

        # Recorded in the same step as the removal above: the monitor's cleanup
        # purges any record the registry no longer holds, and it can run during
        # the await below.
        self.monitor.connection_closed(
            connection_id=connection_id,
            reason=reason,
        )

        # Session-Manager informieren
        await self.session_manager.remove_websocket_connection(
            connection.key, connection.client_type
        )

        self.registry.update_active_connections_count()
        logger.debug(f"🧹 Connection-Cleanup abgeschlossen: {connection_id}")

    # === Private Methods ===

    async def _handle_client_message(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ) -> None:
        """
        Client-Message verarbeiten und weiterleiten
        """
        # Message an alle anderen Clients der Session weiterleiten
        forward_message = relayed_message_frame(
            connection.client_type, connection.session_id, message.get("content")
        )

        await self.broadcast_to_session(
            connection.key,
            forward_message,
            exclude_connection=self.registry.registered_connection_id(connection),
        )

    async def _handle_typing_indicator(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ) -> None:
        """
        Typing-Indicator weiterleiten
        """
        typing_message = typing_frame(
            connection.client_type, connection.session_id, message.get("is_typing", False)
        )

        await self.broadcast_to_session(
            connection.key,
            typing_message,
            exclude_connection=self.registry.registered_connection_id(connection),
        )

    async def _send_connection_ack(self, connection: WebSocketConnection) -> None:
        """
        Connection-Bestätigung senden
        """
        ack_message = connection_ack_frame(
            connection.session_id, connection.client_type, self.heartbeat.interval
        )

        try:
            await connection.websocket.send_json(ack_message)
        except Exception as e:
            logger.warning(f"⚠️ Connection-ACK-Fehler: {e}")

    async def _send_disconnect_message(self, connection: WebSocketConnection, reason: str) -> None:
        """
        Disconnect-Nachricht vor dem Schließen senden
        """
        disconnect_message = disconnecting_frame(reason)

        try:
            await connection.websocket.send_json(disconnect_message)
        except Exception:
            pass  # Ignore Fehler beim Disconnect

    async def _disconnect_connection_with_message(
        self, connection: WebSocketConnection, termination_message: SessionTerminatedFrame
    ) -> None:
        """
        Verbindung mit spezifischer Nachricht trennen
        """
        try:
            await connection.websocket.send_json(termination_message)
            await asyncio.sleep(0.1)  # Kurz warten damit Message ankommt

            if connection.websocket.client_state != connection.websocket.client_state.DISCONNECTED:
                await connection.websocket.close(
                    code=1000,
                    reason=termination_message.get("reason", "session_terminated"),
                )

        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Trennen der Verbindung: {e}")

        finally:
            connection_id = self.registry.tracked_connection_id(connection)

            if connection_id:
                # The termination message already carries the real cause
                # (session_timeout, new_session_created). Recording every one
                # of them as CONNECTION_ERROR would feed routine session ends
                # into a critical alert.
                await self.release_connection(
                    connection_id,
                    DisconnectReason.from_wire(termination_message.get("reason", "session_ended")),
                )

    async def _broadcast_client_joined(
        self, session_id: TenantSessionKey, client_type: ClientType, connection_id: str
    ) -> None:
        """
        Client-Join-Event an andere Session-Teilnehmer senden
        """
        # Include customer_language when customer joins
        customer_language = None
        if client_type == ClientType.CUSTOMER:
            session = self.session_manager.get_session(session_id)
            if session:
                customer_language = session.customer_language
        join_message = client_joined_frame(
            session_id.session_id, client_type, connection_id, customer_language
        )

        await self.broadcast_to_session(session_id, join_message, exclude_connection=connection_id)

    async def _broadcast_client_left(
        self, session_id: TenantSessionKey, client_type: ClientType, connection_id: str, reason: str
    ) -> None:
        """
        Client-Leave-Event an andere Session-Teilnehmer senden
        """
        leave_message = client_left_frame(session_id.session_id, client_type, connection_id, reason)

        await self.broadcast_to_session(session_id, leave_message)

    def _calculate_reconnect_delay(self, attempt: int) -> float:
        """
        Exponential backoff für Reconnect-Delays
        """
        delay: float = self.base_reconnect_delay * (2**attempt)
        max_delay = 60  # Maximum 60 Sekunden
        return min(delay, max_delay)


# === FastAPI WebSocket Endpoints ===

router = APIRouter()

WebSocketManagerDependency = Annotated[
    WebSocketManager,
    Depends(get_websocket_manager),
]
SessionManagerDependency = Annotated[TenantSessionManager, Depends(get_session_manager)]


@router.websocket("/ws/admin/{session_id}")
async def admin_websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    ticket: str,
    manager: WebSocketManagerDependency,
    sessions: SessionManagerDependency,
    tickets: Annotated[RealtimeTicketStore, Depends(get_realtime_ticket_store)],
    origin: Annotated[Optional[str], Header()] = None,
) -> None:
    try:
        key = tickets.consume_key(ticket, session_id, "websocket")
    except RealtimeTicketUnavailable:
        await websocket.close(code=1013, reason="Realtime service unavailable")
        return
    if key is None or sessions.get_session(key) is None:
        await websocket.close(code=4404, reason=_SESSION_NOT_FOUND)
        return
    await websocket_endpoint(websocket, key, ClientType.ADMIN, manager, sessions, origin)


@router.websocket("/ws/customer/{session_id}")
async def customer_websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    key: Annotated[TenantSessionKey, Depends(require_customer_session_key)],
    manager: WebSocketManagerDependency,
    sessions: SessionManagerDependency,
    origin: Annotated[Optional[str], Header()] = None,
) -> None:
    await websocket_endpoint(websocket, key, ClientType.CUSTOMER, manager, sessions, origin)


async def websocket_endpoint(
    websocket: WebSocket,
    key: TenantSessionKey,
    client_type: ClientType,
    manager: WebSocketManager,
    sessions: TenantSessionManager,
    origin: Optional[str] = None,
) -> None:
    """
    Enhanced WebSocket endpoint with explicit CORS validation
    """
    # 1. CORS Origin Validation (before WebSocket accept)
    if not await validate_websocket_origin(origin):
        manager.monitor.record_rejected_connection(DisconnectReason.ORIGIN_NOT_ALLOWED)
        await websocket.close(code=1008, reason="Origin not allowed")
        logger.warning(
            "❌ WebSocket connection rejected - invalid origin: %s",
            sanitize_log_value(origin),
        )
        return

    # 2. Session validieren
    session = sessions.get_session(key)
    if not session:
        await websocket.close(code=1003, reason=_SESSION_NOT_FOUND)
        return

    if session.status == SessionStatus.TERMINATED:
        await websocket.close(code=1003, reason="Session terminated")
        return

    connection_id = None
    # A close frame replaces this with the reason its code classifies to, and
    # every non-close exit path sets connection_error. Reporting an abnormal
    # termination as a clean client exit is what kept the unexpected-disconnect
    # rate reading near zero.
    exit_reason = "client_disconnect"

    try:
        # 4. WebSocket-Verbindung herstellen mit origin logging
        logger.info(
            "🔗 WebSocket connection from origin: %s",
            sanitize_log_value(origin),
        )
        connection_id = await manager.connect_websocket(
            websocket, key, client_type, client_info={"origin": origin}
        )

        # Message-Handler-Loop
        while True:
            try:
                # Auf Nachrichten warten
                data = await websocket.receive_json()
                await manager.handle_websocket_message(connection_id, data)

            except WebSocketDisconnect as disconnect:
                exit_reason = disconnect_reason_for_close_code(disconnect.code)
                logger.info(
                    "🔌 WebSocket-Disconnect: %s (code %s, reason %s)",
                    sanitize_log_value(str(connection_id)),
                    disconnect.code,
                    exit_reason,
                )
                break

            except Exception:
                logger.exception("WebSocket message processing failed")
                # Error-Message an Client senden
                error_message = error_frame("Message processing failed")
                try:
                    await websocket.send_json(error_message)
                except Exception:
                    exit_reason = "connection_error"
                    break

    except Exception:
        exit_reason = "connection_error"
        logger.exception("WebSocket connection failed")

    finally:
        # Cleanup bei Disconnect
        if connection_id:
            await manager.disconnect_websocket(connection_id, exit_reason)


async def get_websocket_stats(
    manager: WebSocketManagerDependency,
) -> Dict[str, Any]:
    """
    WebSocket-Statistiken für Monitoring
    """
    return await asyncio.to_thread(manager.get_connection_stats)


async def websocket_connection_test(
    origin: Annotated[Optional[str], Header()] = None,
    user_agent: Annotated[Optional[str], Header()] = None,
) -> Dict[str, Any]:
    """
    Debug endpoint to test WebSocket connection feasibility
    """
    origin_allowed = await validate_websocket_origin(origin) if origin else False
    environment = os.environ.get("ENVIRONMENT", "production")

    suggestions = []
    if not origin:
        suggestions.append("Origin header is missing - ensure frontend sends Origin header")
    elif not origin_allowed:
        if environment == "development":
            suggestions.append("Add your origin to DEVELOPMENT_CORS_ORIGINS environment variable")
        else:
            suggestions.append(
                "Origin must match production pattern: *.figma.site or translate.smart-village.solutions"
            )
        suggestions.append("Check if origin is correctly formatted (include protocol)")
    else:
        suggestions.append("Origin is allowed for WebSocket connections")
        suggestions.append("Ensure WebSocket upgrade headers are included in request")

    if environment == "production":
        suggestions.append("Use wss:// protocol for production connections")

    return {
        "timestamp": utc_now().isoformat(),
        "origin": origin,
        "user_agent": user_agent,
        "origin_allowed": origin_allowed,
        "cors_headers": {
            "Access-Control-Allow-Origin": origin if origin_allowed else None,
            "Access-Control-Allow-Headers": "Upgrade, Connection, Sec-WebSocket-Key, Sec-WebSocket-Version",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
        },
        "websocket_endpoint": "/ws/{session_id}/{client_type}",
        "environment": environment,
        "configuration": {
            "development_origins": (
                os.environ.get("DEVELOPMENT_CORS_ORIGINS", "").split(",")
                if environment == "development"
                else "Hidden in production"
            ),
            "production_pattern": (
                "https://.*\\.figma\\.site|https://translate\\.smart-village\\.solutions"
                if environment == "production"
                else None
            ),
        },
        "suggestions": suggestions,
    }
