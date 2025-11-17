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
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from .session_manager import ClientType, SessionManager, SessionStatus
from .websocket_fallback import FallbackReason, fallback_manager
from .websocket_monitor import DisconnectReason, get_websocket_monitor

# === Logging Setup ===
logger = logging.getLogger(__name__)


# === Origin Validation for WebSocket Connections ===
async def validate_websocket_origin(origin: Optional[str]) -> bool:
    """
    Validate WebSocket origin against allowed origins
    """
    # Development environment - mehr permissive Regeln
    environment = os.environ.get("ENVIRONMENT", "production")
    if environment == "development":
        # Erlaube fehlende Origin-Header in Development (für Tests)
        if not origin:
            return True

        # Erlaube alle localhost Origins
        if origin.startswith(("http://localhost", "https://localhost")):
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

    # ✅ FIX: Korrektes Regex-Pattern (* → .*)
    production_pattern = r"https://.*\.figma\.site|https://.*\.smart-village\.solutions"
    return bool(re.match(production_pattern, origin))


class ConnectionState(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    ERROR = "error"


class MessageType(str, Enum):
    # System Messages
    CONNECTION_ACK = "connection_ack"
    HEARTBEAT_PING = "heartbeat_ping"
    HEARTBEAT_PONG = "heartbeat_pong"
    SESSION_TERMINATED = "session_terminated"
    CONNECTION_STATUS = "connection_status"

    # Communication Messages
    MESSAGE = "message"
    TYPING_INDICATOR = "typing_indicator"
    CLIENT_JOINED = "client_joined"
    CLIENT_LEFT = "client_left"

    # 📱 Mobile-Optimization Messages
    TAB_VISIBILITY_CHANGE = "tab_visibility_change"
    BATTERY_STATUS_UPDATE = "battery_status_update"
    NETWORK_STATUS_CHANGE = "network_status_change"
    DEVICE_ORIENTATION_CHANGE = "device_orientation_change"
    POLLING_INTERVAL_UPDATE = "polling_interval_update"

    # Error Messages
    ERROR = "error"
    RECONNECT_REQUIRED = "reconnect_required"


@dataclass
class BroadcastResult:
    """Result of a broadcast operation"""

    success: bool
    total_connections: int
    successful_sends: int
    failed_sends: int
    session_has_connections: bool
    errors: List[str]


@dataclass
class WebSocketConnection:
    """WebSocket-Verbindung mit Metadata"""

    websocket: WebSocket
    client_type: ClientType
    session_id: str
    connected_at: datetime
    last_heartbeat: datetime
    state: ConnectionState = ConnectionState.CONNECTING
    reconnect_count: int = 0
    client_info: Optional[Dict[str, Any]] = None

    # 📱 Mobile-Optimization Fields
    is_mobile: bool = False
    tab_active: bool = True
    battery_level: float = 1.0
    network_quality: str = "good"  # "good", "slow", "offline"
    current_polling_interval: int = 5  # Sekunden

    def is_alive(self) -> bool:
        """Prüft ob die Verbindung noch aktiv ist"""
        if self.state in [ConnectionState.DISCONNECTED, ConnectionState.ERROR]:
            return False

        # Heartbeat-Timeout prüfen (60 Sekunden)
        timeout_threshold = datetime.now() - timedelta(seconds=60)
        return self.last_heartbeat > timeout_threshold

    def to_dict(self) -> Dict[str, Any]:
        """Serialisierung für Monitoring"""
        return {
            "client_type": self.client_type.value,
            "session_id": self.session_id,
            "connected_at": self.connected_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "state": self.state.value,
            "reconnect_count": self.reconnect_count,
            # 📱 Mobile-Optimization Info
            "is_mobile": self.is_mobile,
            "tab_active": self.tab_active,
            "battery_level": self.battery_level,
            "network_quality": self.network_quality,
            "current_polling_interval": self.current_polling_interval,
            "is_alive": self.is_alive(),
            "client_info": self.client_info,
        }


class AdaptivePollingManager:
    """
    📱 Mobile-optimiertes adaptives Polling-System
    Passt Polling-Intervalle basierend auf Device-Status an
    """

    # Polling-Intervall-Konfiguration (Sekunden)
    POLLING_INTERVALS = {
        "active_desktop": 3,  # Sehr responsiv für Desktop
        "active_mobile": 5,  # Standard responsiv für Mobile
        "background_desktop": 10,  # Reduziert für Desktop-Background
        "background_mobile": 30,  # Stark reduziert für Mobile-Background
        "battery_saver": 60,  # Minimal für Battery-Saver-Mode
        "slow_network": 15,  # Angepasst für langsame Verbindungen
        "offline_mode": 120,  # Sehr selten für Offline-Detection
    }

    def __init__(self):
        self.client_profiles: Dict[str, Dict[str, Any]] = {}

    def get_optimal_interval(self, connection: WebSocketConnection) -> int:
        """
        Berechnet optimales Polling-Intervall basierend auf Client-Status
        """
        # Battery-Saver hat höchste Priorität
        if connection.battery_level < 0.2:  # <20% Battery
            return self.POLLING_INTERVALS["battery_saver"]

        # Network-Quality berücksichtigen
        if connection.network_quality == "slow":
            return self.POLLING_INTERVALS["slow_network"]
        elif connection.network_quality == "offline":
            return self.POLLING_INTERVALS["offline_mode"]

        # Mobile vs Desktop + Tab-Status
        if connection.is_mobile:
            if connection.tab_active:
                return self.POLLING_INTERVALS["active_mobile"]
            else:
                return self.POLLING_INTERVALS["background_mobile"]
        else:
            if connection.tab_active:
                return self.POLLING_INTERVALS["active_desktop"]
            else:
                return self.POLLING_INTERVALS["background_desktop"]

    def update_client_status(
        self,
        connection: WebSocketConnection,
        is_mobile: Optional[bool] = None,
        tab_active: Optional[bool] = None,
        battery_level: Optional[float] = None,
        network_quality: Optional[str] = None,
    ) -> int:
        """
        Client-Status aktualisieren und neues Intervall zurückgeben
        """
        if is_mobile is not None:
            connection.is_mobile = is_mobile
        if tab_active is not None:
            connection.tab_active = tab_active
        if battery_level is not None:
            connection.battery_level = max(0.0, min(1.0, battery_level))
        if network_quality is not None:
            connection.network_quality = network_quality

        # Neues optimales Intervall berechnen
        new_interval = self.get_optimal_interval(connection)
        connection.current_polling_interval = new_interval

        return new_interval

    def get_battery_optimization_tips(
        self, connection: WebSocketConnection
    ) -> List[str]:
        """
        Battery-Optimierungs-Tipps für Client
        """
        tips = []

        if connection.battery_level < 0.3:
            tips.append("🔋 Niedriger Akkustand - Polling-Intervall auf 60s erhöht")

        if not connection.tab_active and connection.is_mobile:
            tips.append("📱 Tab im Hintergrund - Reduzierte Update-Frequenz aktiviert")

        if connection.network_quality == "slow":
            tips.append("📶 Langsame Verbindung erkannt - Polling angepasst")

        return tips


class WebSocketManager:
    """
    Erweiterte WebSocket-Verwaltung mit Session-basierter Organisation
    """

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self.session_manager.register_websocket_manager(self)

        # Session-basierte Connection-Pools
        self.session_connections: Dict[str, Dict[str, WebSocketConnection]] = {}

        # Global Connection Tracking für Monitoring
        self.all_connections: Dict[str, WebSocketConnection] = {}

        # Heartbeat-System
        # Use the canonical 60s timeout for tests and reasonable production defaults.
        self.heartbeat_interval = 30  # Sekunden
        self.heartbeat_timeout = 60  # Sekunden (heartbeat timeout threshold)
        self.heartbeat_task: Optional[asyncio.Task] = None

        # Polling-Fallback Configuration
        self.polling_clients: Set[str] = set()
        self.polling_interval = 5  # Sekunden für Polling-Clients (Legacy)

        # 📱 Mobile-Optimization
        self.adaptive_polling = AdaptivePollingManager()

        # Auto-Reconnect Configuration
        self.max_reconnect_attempts = 5
        self.base_reconnect_delay = 1  # Sekunden (exponential backoff)

        # Monitoring
        self.connection_stats = {
            "total_connections": 0,
            "active_connections": 0,
            "failed_connections": 0,
            "heartbeat_timeouts": 0,
            "reconnects": 0,
            "polling_fallbacks": 0,
        }

        logger.info("🔗 WebSocketManager initialisiert")

    async def start_heartbeat_system(self):
        """Startet das Heartbeat-Überwachungssystem"""
        if self.heartbeat_task and not self.heartbeat_task.done():
            return

        self.heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
        logger.info("💓 Heartbeat-System gestartet")

    async def stop_heartbeat_system(self):
        """Stoppt das Heartbeat-System"""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
            self.heartbeat_task = None
        logger.info("💓 Heartbeat-System gestoppt")

    async def connect_websocket(
        self,
        websocket: WebSocket,
        session_id: str,
        client_type: ClientType,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        WebSocket-Verbindung herstellen und zu Session-Pool hinzufügen
        Returns: connection_id für Tracking
        """
        await websocket.accept()

        # Connection-ID generieren
        connection_id = f"{session_id}_{client_type.value}_{int(time.time())}"

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
            session_id=session_id,
            connected_at=datetime.now(),
            last_heartbeat=datetime.now(),
            state=ConnectionState.CONNECTED,
            client_info=client_info,
            # 📱 Mobile-Optimization
            is_mobile=is_mobile,
            tab_active=True,  # Initial aktiv
            battery_level=battery_level,
            network_quality=network_quality,
        )

        # 📱 Optimales Polling-Intervall berechnen
        optimal_interval = self.adaptive_polling.get_optimal_interval(connection)
        connection.current_polling_interval = optimal_interval

        # Zu Session-Pool hinzufügen
        if session_id not in self.session_connections:
            self.session_connections[session_id] = {}

        self.session_connections[session_id][connection_id] = connection
        self.all_connections[connection_id] = connection

        # Session-Manager integrieren
        await self.session_manager.add_websocket_connection(
            session_id, client_type, websocket
        )

        # 📊 Monitoring: Connection established
        origin = client_info.get("origin") if client_info else None
        get_websocket_monitor().connection_established(
            connection_id=connection_id,
            session_id=session_id,
            client_type=client_type.value,
            origin=origin,
        )

        # Stats aktualisieren
        self.connection_stats["total_connections"] += 1
        self._update_active_connections_count()

        # Connection-Bestätigung senden
        await self._send_connection_ack(connection)

        # Heartbeat-System starten falls noch nicht aktiv
        await self.start_heartbeat_system()

        logger.info(
            f"🔗 WebSocket verbunden: {connection_id} (Session: {session_id}, Type: {client_type.value})"
        )

        # Anderen Clients in der Session mitteilen
        await self._broadcast_client_joined(session_id, client_type, connection_id)

        return connection_id

    async def disconnect_websocket(
        self, connection_id: str, reason: str = "client_disconnect", code: int = 1000
    ):
        """
        WebSocket-Verbindung graceful trennen
        """
        connection = self.all_connections.get(connection_id)
        if not connection:
            return

        connection.state = ConnectionState.DISCONNECTING

        try:
            # Disconnect-Nachricht senden
            await self._send_disconnect_message(connection, reason)

            # WebSocket schließen
            if (
                connection.websocket.client_state
                != connection.websocket.client_state.DISCONNECTED
            ):
                await connection.websocket.close(code=code, reason=reason)

        except Exception as e:
            logger.warning(
                f"⚠️ Fehler beim Schließen der WebSocket-Verbindung {connection_id}: {e}"
            )

        finally:
            # Connection-Cleanup
            await self._cleanup_connection(connection_id)

            # Anderen Clients mitteilen
            await self._broadcast_client_left(
                connection.session_id, connection.client_type, connection_id, reason
            )

    async def handle_session_termination(
        self, session_id: str, reason: str = "session_ended"
    ):
        """
        Alle WebSocket-Verbindungen einer Session graceful beenden
        """
        if session_id not in self.session_connections:
            return

        connections = list(self.session_connections[session_id].values())
        logger.info(
            f"🔚 Beende {len(connections)} WebSocket-Verbindungen für Session {session_id}"
        )

        # Termination-Nachricht an alle Clients senden
        termination_message = {
            "type": MessageType.SESSION_TERMINATED.value,
            "session_id": session_id,
            "reason": reason,
            "message": self._get_termination_message(reason),
            "timestamp": datetime.now().isoformat(),
            "reconnect_allowed": False,
        }

        # Parallel alle Verbindungen benachrichtigen und schließen
        disconnect_tasks = []
        for connection in connections:
            disconnect_tasks.append(
                self._disconnect_connection_with_message(
                    connection, termination_message
                )
            )

        if disconnect_tasks:
            await asyncio.gather(*disconnect_tasks, return_exceptions=True)

        # Session-Connection-Pool leeren
        if session_id in self.session_connections:
            del self.session_connections[session_id]

        logger.info(f"✅ Session {session_id} WebSocket-Verbindungen beendet")

    async def broadcast_to_session(
        self,
        session_id: str,
        message: Dict[str, Any],
        exclude_connection: Optional[str] = None,
        target_client_type: Optional[ClientType] = None,
    ):
        """
        Nachricht an alle Clients einer Session broadcasten
        """
        if session_id not in self.session_connections:
            logger.warning(f"⚠️ Keine WebSocket-Verbindungen für Session {session_id}")
            return

        connections = self.session_connections[session_id]
        successful_sends = 0
        failed_sends = 0

        for connection_id, connection in connections.items():
            # Skip ausgeschlossene Verbindungen
            if connection_id == exclude_connection:
                continue

            # Skip wenn spezifischer Client-Type gewünscht
            if target_client_type and connection.client_type != target_client_type:
                continue

            if not connection.is_alive():
                continue

            try:
                await connection.websocket.send_json(message)
                successful_sends += 1

                # 📊 Monitoring: Message sent
                message_type = message.get("type", "unknown")
                get_websocket_monitor().message_sent(
                    connection_id=connection_id,
                    message_data=str(message),
                    message_type=message_type,
                )

            except Exception as e:
                logger.warning(f"⚠️ Broadcast-Fehler zu {connection_id}: {e}")
                failed_sends += 1

                # 📊 Monitoring: Error occurred
                get_websocket_monitor().record_error(
                    connection_id=connection_id,
                    error_type="broadcast_error",
                    error_details=str(e),
                )

                # 🔄 Evaluate if fallback should be triggered
                await self._evaluate_connection_error(connection, e, "broadcast_error")

                # Connection als tot markieren
                connection.state = ConnectionState.ERROR

        logger.debug(
            f"📢 Broadcast zu Session {session_id}: {successful_sends} erfolgreich, {failed_sends} fehlgeschlagen"
        )

    async def broadcast_with_differentiated_content(
        self,
        session_id: str,
        sender_type: ClientType,
        original_message: Dict[str, Any],
        translated_message: Dict[str, Any],
    ) -> BroadcastResult:
        """
        Differentiated Broadcasting with validation and error handling:
        - Sender erhält original_text (ASR-Bestätigung)
        - Empfänger erhält translated_text + audio

        Returns:
            BroadcastResult with success status and detailed metrics
        """
        # Task 4.8: Record broadcast attempt
        monitor = get_websocket_monitor()
        monitor.broadcast_total.labels(
            session_id=session_id, sender_type=sender_type.value
        ).inc()

        errors = []
        successful_sends = 0
        failed_sends = 0

        # Task 4.1 & 4.2: Validate session has connections
        if session_id not in self.session_connections:
            logger.warning(
                f"⚠️ Broadcasting to session {session_id} with no connections"
            )

            # Task 4.8: Record failure reason
            monitor.broadcast_failure_total.labels(
                session_id=session_id,
                sender_type=sender_type.value,
                reason="no_connections",
            ).inc()

            return BroadcastResult(
                success=False,
                total_connections=0,
                successful_sends=0,
                failed_sends=0,
                session_has_connections=False,
                errors=["Session has no active connections"],
            )

        connections = self.session_connections[session_id]
        total_connections = len(connections)

        # Task 4.3: Log connection count before broadcast
        logger.info(
            f"📡 Broadcasting to session {session_id}: {total_connections} connection(s)"
        )

        # Task 4.4: Check if manager has any connections at all
        if len(self.all_connections) == 0:
            error_msg = "WebSocketManager has no connections at all"
            logger.error(f"❌ {error_msg}")
            errors.append(error_msg)

        for connection_id, connection in connections.items():
            if not connection.is_alive():
                failed_sends += 1
                errors.append(f"Connection {connection_id} is not alive")
                continue

            try:
                if connection.client_type == sender_type:
                    # Sender erhält original_text zur Bestätigung
                    await connection.websocket.send_json(original_message)
                    successful_sends += 1
                    logger.debug(f"✓ Sent original message to sender {connection_id}")
                else:
                    # Empfänger erhält translated_text + audio
                    await connection.websocket.send_json(translated_message)
                    successful_sends += 1
                    logger.debug(
                        f"✓ Sent translated message to receiver {connection_id}"
                    )
            except Exception as e:
                failed_sends += 1
                error_msg = f"Failed to send to {connection_id}: {str(e)}"
                logger.warning(f"⚠️ {error_msg}")
                errors.append(error_msg)

        # Task 4.5 & 4.6: Return detailed status
        success = successful_sends > 0 and failed_sends == 0

        # Task 4.8: Record metrics
        if success:
            logger.info(
                f"✅ Broadcast successful: {successful_sends}/{total_connections} delivered"
            )
            monitor.broadcast_success_total.labels(
                session_id=session_id, sender_type=sender_type.value
            ).inc()
        else:
            logger.warning(
                f"⚠️ Broadcast partial/failed: {successful_sends} succeeded, "
                f"{failed_sends} failed out of {total_connections}"
            )
            monitor.broadcast_failure_total.labels(
                session_id=session_id,
                sender_type=sender_type.value,
                reason=(
                    "partial_failure" if successful_sends > 0 else "complete_failure"
                ),
            ).inc()

        # Record individual message delivery counts
        if successful_sends > 0:
            monitor.broadcast_messages_delivered.labels(
                session_id=session_id, sender_type=sender_type.value
            ).inc(successful_sends)

        if failed_sends > 0:
            monitor.broadcast_messages_failed.labels(
                session_id=session_id, sender_type=sender_type.value
            ).inc(failed_sends)

        return BroadcastResult(
            success=success,
            total_connections=total_connections,
            successful_sends=successful_sends,
            failed_sends=failed_sends,
            session_has_connections=True,
            errors=errors,
        )

    async def handle_websocket_message(
        self, connection_id: str, message: Dict[str, Any]
    ):
        """
        Eingehende WebSocket-Nachrichten verarbeiten
        """
        connection = self.all_connections.get(connection_id)
        if not connection:
            return

        message_type = message.get("type")

        if message_type == MessageType.HEARTBEAT_PONG.value:
            await self._handle_heartbeat_pong(connection)

        elif message_type == MessageType.MESSAGE.value:
            await self._handle_client_message(connection, message)

        elif message_type == MessageType.TYPING_INDICATOR.value:
            await self._handle_typing_indicator(connection, message)

        # 📱 Mobile-Optimization Messages
        elif message_type == MessageType.TAB_VISIBILITY_CHANGE.value:
            await self._handle_tab_visibility_change(connection, message)

        elif message_type == MessageType.BATTERY_STATUS_UPDATE.value:
            await self._handle_battery_status_update(connection, message)

        elif message_type == MessageType.NETWORK_STATUS_CHANGE.value:
            await self._handle_network_status_change(connection, message)

        else:
            logger.warning(f"⚠️ Unbekannter Message-Type: {message_type}")

    async def enable_polling_fallback(
        self, session_id: str, client_type: ClientType
    ) -> str:
        """
        Polling-Fallback für Client aktivieren
        """
        polling_id = f"poll_{session_id}_{client_type.value}_{int(time.time())}"
        self.polling_clients.add(polling_id)
        self.connection_stats["polling_fallbacks"] += 1

        logger.info(f"📡 Polling-Fallback aktiviert: {polling_id}")
        return polling_id

    async def get_polling_messages(self, polling_id: str) -> List[Dict[str, Any]]:
        """
        Nachrichten für Polling-Client abrufen
        TODO: Message-Queue-Implementation für Polling-Clients
        """
        if polling_id not in self.polling_clients:
            return []

        # Placeholder: In echter Implementation würde hier eine Message-Queue abgefragt
        # Für jetzt leere Liste zurückgeben
        return []

    def get_connection_stats(self) -> Dict[str, Any]:
        """
        WebSocket-Verbindungsstatistiken für Monitoring
        """
        self._update_active_connections_count()

        # Session-Stats
        session_stats = {}
        for session_id, connections in self.session_connections.items():
            session_stats[session_id] = {
                "total_connections": len(connections),
                "active_connections": sum(
                    1 for c in connections.values() if c.is_alive()
                ),
                "client_types": list(
                    set(c.client_type.value for c in connections.values())
                ),
            }

        return {
            "global_stats": self.connection_stats,
            "session_stats": session_stats,
            "polling_clients": len(self.polling_clients),
            "heartbeat_active": self.heartbeat_task is not None
            and not self.heartbeat_task.done(),
        }

    def get_session_connections(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Verbindungen einer Session für Debugging/Monitoring
        """
        if session_id not in self.session_connections:
            return []

        return [
            connection.to_dict()
            for connection in self.session_connections[session_id].values()
        ]

    # === Private Methods ===

    async def _heartbeat_monitor(self):
        """
        Heartbeat-Überwachung im Hintergrund
        """
        logger.info("💓 Heartbeat-Monitor gestartet")

        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                await self._send_heartbeat_pings()
                await self._check_heartbeat_timeouts()

        except asyncio.CancelledError:
            logger.info("💓 Heartbeat-Monitor gestoppt")
            raise
        except Exception as e:
            logger.error(f"❌ Heartbeat-Monitor-Fehler: {e}")

    async def _send_heartbeat_pings(self):
        """
        Heartbeat-Pings an alle aktive Verbindungen senden
        """
        ping_message = {
            "type": MessageType.HEARTBEAT_PING.value,
            "timestamp": datetime.now().isoformat(),
        }

        dead_connections = []

        for connection_id, connection in self.all_connections.items():
            if connection.state != ConnectionState.CONNECTED:
                continue

            try:
                await connection.websocket.send_json(ping_message)
            except Exception as e:
                logger.warning(f"💓 Heartbeat-Ping-Fehler {connection_id}: {e}")
                dead_connections.append(connection_id)

        # Tote Verbindungen cleanup
        for connection_id in dead_connections:
            await self._cleanup_connection(connection_id)

    async def _check_heartbeat_timeouts(self):
        """
        Heartbeat-Timeouts prüfen und tote Verbindungen entfernen
        """
        timeout_threshold = datetime.now() - timedelta(seconds=self.heartbeat_timeout)
        timeout_connections = []

        for connection_id, connection in self.all_connections.items():
            if connection.last_heartbeat < timeout_threshold:
                timeout_connections.append(connection_id)
                self.connection_stats["heartbeat_timeouts"] += 1

        for connection_id in timeout_connections:
            logger.warning(f"💓 Heartbeat-Timeout: {connection_id}")
            await self.disconnect_websocket(connection_id, "heartbeat_timeout", 1001)

    async def _handle_heartbeat_pong(self, connection: WebSocketConnection):
        """
        Heartbeat-Pong verarbeiten
        """
        connection.last_heartbeat = datetime.now()
        connection.state = ConnectionState.CONNECTED

    async def _handle_client_message(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ):
        """
        Client-Message verarbeiten und weiterleiten
        """
        # Message an alle anderen Clients der Session weiterleiten
        forward_message = {
            "type": MessageType.MESSAGE.value,
            "from": connection.client_type.value,
            "session_id": connection.session_id,
            "content": message.get("content"),
            "timestamp": datetime.now().isoformat(),
        }

        await self.broadcast_to_session(
            connection.session_id,
            forward_message,
            exclude_connection=f"{connection.session_id}_{connection.client_type.value}_{int(connection.connected_at.timestamp())}",
        )

    async def _handle_typing_indicator(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ):
        """
        Typing-Indicator weiterleiten
        """
        typing_message = {
            "type": MessageType.TYPING_INDICATOR.value,
            "from": connection.client_type.value,
            "session_id": connection.session_id,
            "is_typing": message.get("is_typing", False),
            "timestamp": datetime.now().isoformat(),
        }

        await self.broadcast_to_session(
            connection.session_id,
            typing_message,
            exclude_connection=f"{connection.session_id}_{connection.client_type.value}_{int(connection.connected_at.timestamp())}",
        )

    async def _send_connection_ack(self, connection: WebSocketConnection):
        """
        Connection-Bestätigung senden
        """
        ack_message = {
            "type": MessageType.CONNECTION_ACK.value,
            "session_id": connection.session_id,
            "client_type": connection.client_type.value,
            "timestamp": datetime.now().isoformat(),
            "heartbeat_interval": self.heartbeat_interval,
        }

        try:
            await connection.websocket.send_json(ack_message)
        except Exception as e:
            logger.warning(f"⚠️ Connection-ACK-Fehler: {e}")

    async def _send_disconnect_message(
        self, connection: WebSocketConnection, reason: str
    ):
        """
        Disconnect-Nachricht vor dem Schließen senden
        """
        disconnect_message = {
            "type": MessageType.CONNECTION_STATUS.value,
            "status": "disconnecting",
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }

        try:
            await connection.websocket.send_json(disconnect_message)
        except Exception:
            pass  # Ignore Fehler beim Disconnect

    async def _disconnect_connection_with_message(
        self, connection: WebSocketConnection, termination_message: Dict[str, Any]
    ):
        """
        Verbindung mit spezifischer Nachricht trennen
        """
        try:
            await connection.websocket.send_json(termination_message)
            await asyncio.sleep(0.1)  # Kurz warten damit Message ankommt

            if (
                connection.websocket.client_state
                != connection.websocket.client_state.DISCONNECTED
            ):
                await connection.websocket.close(
                    code=1000,
                    reason=termination_message.get("reason", "session_terminated"),
                )

        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Trennen der Verbindung: {e}")

        finally:
            # Connection-ID aus all_connections entfernen
            connection_id = None
            for cid, conn in self.all_connections.items():
                if conn == connection:
                    connection_id = cid
                    break

            if connection_id:
                await self._cleanup_connection(connection_id)

    async def _cleanup_connection(self, connection_id: str):
        """
        Connection-Cleanup nach Disconnect
        """
        connection = self.all_connections.get(connection_id)
        if not connection:
            return

        connection.state = ConnectionState.DISCONNECTED

        # Aus Session-Pool entfernen
        if connection.session_id in self.session_connections:
            self.session_connections[connection.session_id].pop(connection_id, None)

            # Wenn Session keine Verbindungen mehr hat, Pool löschen
            if not self.session_connections[connection.session_id]:
                del self.session_connections[connection.session_id]

        # Aus globalem Pool entfernen
        self.all_connections.pop(connection_id, None)

        # Session-Manager informieren
        await self.session_manager.remove_websocket_connection(
            connection.session_id, connection.client_type
        )

        # 📊 Monitoring: Connection closed
        get_websocket_monitor().connection_closed(
            connection_id=connection_id,
            reason=DisconnectReason.CLIENT_DISCONNECT,  # Default reason
        )

        self._update_active_connections_count()
        logger.debug(f"🧹 Connection-Cleanup abgeschlossen: {connection_id}")

    async def _evaluate_connection_error(
        self, connection: WebSocketConnection, error: Exception, error_context: str
    ):
        """
        Evaluate WebSocket connection error and potentially trigger fallback
        """
        try:
            # Prepare error details for evaluation
            error_details = {
                "message": str(error),
                "type": type(error).__name__,
                "context": error_context,
                "connection_id": f"{connection.session_id}_{connection.client_type.value}_{int(time.time())}",
            }

            # Extract additional error information
            if hasattr(error, "code"):
                error_details["code"] = error.code
            if hasattr(error, "reason"):
                error_details["reason"] = error.reason

            # Get origin from connection client_info
            origin = None
            if connection.client_info:
                origin = connection.client_info.get("origin")

            # Evaluate if fallback should be triggered
            should_fallback = await fallback_manager.evaluate_websocket_failure(
                session_id=connection.session_id,
                client_type=connection.client_type.value,
                origin=origin,
                error_details=error_details,
            )

            if should_fallback:
                # Determine fallback reason based on error
                fallback_reason = self._classify_error_for_fallback(
                    error, error_context
                )

                # Activate polling fallback
                polling_id = await fallback_manager.activate_polling_fallback(
                    session_id=connection.session_id,
                    client_type=connection.client_type.value,
                    origin=origin,
                    reason=fallback_reason,
                )

                # Send fallback notification to client if connection is still alive
                if connection.state != ConnectionState.DISCONNECTED:
                    await self._send_fallback_activation_message(
                        connection, polling_id, fallback_reason
                    )

                logger.info(
                    f"🔄 Polling fallback activated for {connection.session_id}: {polling_id}"
                )

        except Exception as fallback_error:
            logger.error(f"Error in fallback evaluation: {fallback_error}")

    def _classify_error_for_fallback(
        self, error: Exception, context: str
    ) -> FallbackReason:
        """Classify error type for appropriate fallback reason"""
        error_message = str(error).lower()
        error_type = type(error).__name__.lower()

        # WebSocket specific errors
        if "websocket" in error_type:
            if "1003" in error_message or "unsupported data" in error_message:
                return FallbackReason.WEBSOCKET_HANDSHAKE_FAILED
            return FallbackReason.WEBSOCKET_CONNECTION_FAILED

        # CORS related errors
        if "cors" in error_message or "origin" in error_message:
            return FallbackReason.CORS_ORIGIN_BLOCKED

        # Network errors
        if any(term in error_message for term in ["network", "connection", "timeout"]):
            if "timeout" in error_message:
                return FallbackReason.TIMEOUT_ERROR
            return FallbackReason.NETWORK_ERROR

        # Connection errors during broadcast suggest network issues
        if context == "broadcast_error":
            return FallbackReason.NETWORK_ERROR

        return FallbackReason.WEBSOCKET_CONNECTION_FAILED

    async def _send_fallback_activation_message(
        self, connection: WebSocketConnection, polling_id: str, reason: FallbackReason
    ):
        """Send fallback activation notification to client"""
        try:
            fallback_message = {
                "type": "fallback_activated",
                "polling_id": polling_id,
                "fallback_reason": reason.value,
                "message": "Connection switched to compatibility mode. All features remain available.",
                "polling_endpoint": f"/api/websocket/poll/{polling_id}",
                "instructions": {
                    "action": "switch_to_polling",
                    "polling_interval": 5,
                    "recovery_check_interval": 300,
                },
                "timestamp": datetime.now().isoformat(),
            }

            await connection.websocket.send_json(fallback_message)

        except Exception as e:
            logger.warning(f"Failed to send fallback activation message: {e}")

    async def _broadcast_client_joined(
        self, session_id: str, client_type: ClientType, connection_id: str
    ):
        """
        Client-Join-Event an andere Session-Teilnehmer senden
        """
        join_message = {
            "type": MessageType.CLIENT_JOINED.value,
            "session_id": session_id,
            "client_type": client_type.value,
            "connection_id": connection_id,
            "timestamp": datetime.now().isoformat(),
        }

        # Include customer_language when customer joins
        if client_type == ClientType.CUSTOMER:
            session = self.session_manager.get_session(session_id)
            if session and session.customer_language:
                join_message["customer_language"] = session.customer_language

        await self.broadcast_to_session(
            session_id, join_message, exclude_connection=connection_id
        )

    async def _broadcast_client_left(
        self, session_id: str, client_type: ClientType, connection_id: str, reason: str
    ):
        """
        Client-Leave-Event an andere Session-Teilnehmer senden
        """
        leave_message = {
            "type": MessageType.CLIENT_LEFT.value,
            "session_id": session_id,
            "client_type": client_type.value,
            "connection_id": connection_id,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }

        await self.broadcast_to_session(session_id, leave_message)

    def _get_termination_message(self, reason: str) -> str:
        """
        Benutzerfreundliche Termination-Messages
        """
        messages = {
            "new_session_created": "Die Session wurde beendet, da eine neue Session gestartet wurde.",
            "timeout": "Die Session wurde aufgrund von Inaktivität beendet.",
            "manual_termination": "Die Session wurde manuell beendet.",
            "system_cleanup": "Die Session wurde für System-Wartung beendet.",
            "error": "Die Session wurde aufgrund eines Fehlers beendet.",
            "session_ended": "Die Session wurde ordnungsgemäß beendet.",
        }
        return messages.get(reason, "Die Session wurde beendet.")

    def _update_active_connections_count(self):
        """
        Aktive Verbindungen zählen
        """
        active_count = sum(1 for c in self.all_connections.values() if c.is_alive())
        self.connection_stats["active_connections"] = active_count

    def _calculate_reconnect_delay(self, attempt: int) -> float:
        """
        Exponential backoff für Reconnect-Delays
        """
        delay = self.base_reconnect_delay * (2**attempt)
        max_delay = 60  # Maximum 60 Sekunden
        return min(delay, max_delay)

    # 📱 === Mobile-Optimization Handlers ===

    async def _handle_tab_visibility_change(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ):
        """
        Tab-Visibility-Change verarbeiten (Background/Foreground)
        """
        is_visible = message.get("is_visible", True)
        old_interval = connection.current_polling_interval

        # Status aktualisieren und neues Intervall berechnen
        new_interval = self.adaptive_polling.update_client_status(
            connection, tab_active=is_visible
        )

        # Client über Intervall-Änderung informieren
        if new_interval != old_interval:
            await self._send_polling_interval_update(
                connection,
                new_interval,
                reason=(
                    "tab_visibility_change" if is_visible else "background_optimization"
                ),
            )

        logger.info(
            f"📱 Tab-Visibility für {connection.session_id}: {'visible' if is_visible else 'hidden'} "
            f"(Polling: {old_interval}s → {new_interval}s)"
        )

    async def _handle_battery_status_update(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ):
        """
        Battery-Status-Update verarbeiten
        """
        battery_level = message.get("battery_level", 1.0)
        is_charging = message.get("is_charging", False)
        old_interval = connection.current_polling_interval

        # Status aktualisieren
        new_interval = self.adaptive_polling.update_client_status(
            connection, battery_level=battery_level
        )

        # Battery-Saver-Mode Detection
        if battery_level < 0.2 and not is_charging:
            await self._send_battery_saver_notification(connection)

        # Client über Intervall-Änderung informieren
        if new_interval != old_interval:
            await self._send_polling_interval_update(
                connection, new_interval, reason="battery_optimization"
            )

        logger.info(
            f"🔋 Battery-Update für {connection.session_id}: {battery_level:.0%} "
            f"{'(charging)' if is_charging else ''} (Polling: {old_interval}s → {new_interval}s)"
        )

    async def _handle_network_status_change(
        self, connection: WebSocketConnection, message: Dict[str, Any]
    ):
        """
        Network-Status-Change verarbeiten
        """
        network_quality = message.get(
            "network_quality", "good"
        )  # "good", "slow", "offline"
        connection_type = message.get(
            "connection_type", "wifi"
        )  # "wifi", "cellular", "offline"
        old_interval = connection.current_polling_interval

        # Status aktualisieren
        new_interval = self.adaptive_polling.update_client_status(
            connection, network_quality=network_quality
        )

        # Client über Intervall-Änderung informieren
        if new_interval != old_interval:
            reason = f"network_{network_quality}"
            await self._send_polling_interval_update(
                connection, new_interval, reason=reason
            )

        logger.info(
            f"📶 Network-Update für {connection.session_id}: {network_quality} ({connection_type}) "
            f"(Polling: {old_interval}s → {new_interval}s)"
        )

    async def _send_polling_interval_update(
        self, connection: WebSocketConnection, new_interval: int, reason: str
    ):
        """
        Polling-Intervall-Update an Client senden
        """
        optimization_tips = self.adaptive_polling.get_battery_optimization_tips(
            connection
        )

        message = {
            "type": MessageType.POLLING_INTERVAL_UPDATE.value,
            "new_interval": new_interval,
            "old_interval": connection.current_polling_interval,
            "reason": reason,
            "optimization_tips": optimization_tips,
            "battery_level": connection.battery_level,
            "is_mobile": connection.is_mobile,
            "tab_active": connection.tab_active,
            "timestamp": datetime.now().isoformat(),
        }

        try:
            await connection.websocket.send_json(message)
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Senden des Polling-Updates: {e}")

    async def _send_battery_saver_notification(self, connection: WebSocketConnection):
        """
        Battery-Saver-Notification an Client senden
        """
        message = {
            "type": "battery_saver_mode",
            "title": "🔋 Battery-Saver aktiviert",
            "message": "Update-Frequenz wurde auf 60 Sekunden reduziert um Akku zu schonen.",
            "battery_level": connection.battery_level,
            "new_polling_interval": 60,
            "tips": [
                "📱 Tab schließen wenn nicht benötigt",
                "🔌 Gerät ans Ladegerät anschließen",
                "⚡ Battery-Saver-Modus deaktivieren für normale Geschwindigkeit",
            ],
            "timestamp": datetime.now().isoformat(),
        }

        try:
            await connection.websocket.send_json(message)
        except Exception as e:
            logger.warning(f"⚠️ Fehler beim Senden der Battery-Saver-Notification: {e}")


# === FastAPI WebSocket Endpoints ===

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)

router = APIRouter()

# Globale WebSocket-Manager-Instanz
websocket_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """
    WebSocket-Manager-Instanz abrufen (Dependency Injection)
    """
    global websocket_manager
    if websocket_manager is None:
        from .session_manager import session_manager

        websocket_manager = WebSocketManager(session_manager)
    return websocket_manager


@router.websocket("/ws/{session_id}/{client_type}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    client_type: str,
    origin: Optional[str] = Header(None),  # Explicit Origin handling
    manager: WebSocketManager = Depends(get_websocket_manager),
):
    """
    Enhanced WebSocket endpoint with explicit CORS validation
    """
    # 1. CORS Origin Validation (before WebSocket accept)
    if not await validate_websocket_origin(origin):
        await websocket.close(code=1008, reason="Origin not allowed")
        logger.warning(f"❌ WebSocket connection rejected - invalid origin: {origin}")
        return

    # 2. Client-Type validieren
    try:
        client_type_enum = ClientType(client_type.lower())
    except ValueError:
        await websocket.close(code=1003, reason="Invalid client type")
        return

    # 3. Session validieren
    session = manager.session_manager.get_session(session_id)
    if not session:
        await websocket.close(code=1003, reason="Session not found")
        return

    if session.status == SessionStatus.TERMINATED:
        await websocket.close(code=1003, reason="Session terminated")
        return

    connection_id = None

    try:
        # 4. WebSocket-Verbindung herstellen mit origin logging
        logger.info(f"🔗 WebSocket connection from origin: {origin}")
        connection_id = await manager.connect_websocket(
            websocket, session_id, client_type_enum, client_info={"origin": origin}
        )

        # Message-Handler-Loop
        while True:
            try:
                # Auf Nachrichten warten
                data = await websocket.receive_json()
                await manager.handle_websocket_message(connection_id, data)

            except WebSocketDisconnect:
                logger.info(f"🔌 WebSocket-Disconnect: {connection_id}")
                break

            except Exception as e:
                logger.error(f"❌ WebSocket-Message-Fehler {connection_id}: {e}")
                # Error-Message an Client senden
                error_message = {
                    "type": MessageType.ERROR.value,
                    "error": "Message processing failed",
                    "timestamp": datetime.now().isoformat(),
                }
                try:
                    await websocket.send_json(error_message)
                except Exception:
                    break

    except Exception as e:
        logger.error(f"❌ WebSocket-Verbindungsfehler: {e}")

    finally:
        # Cleanup bei Disconnect
        if connection_id:
            await manager.disconnect_websocket(connection_id, "client_disconnect")


@router.get("/api/websocket/stats")
async def get_websocket_stats(
    manager: WebSocketManager = Depends(get_websocket_manager),
):
    """
    WebSocket-Statistiken für Monitoring
    """
    return manager.get_connection_stats()


@router.get("/api/websocket/sessions/{session_id}/connections")
async def get_session_connections(
    session_id: str, manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    WebSocket-Verbindungen einer Session anzeigen
    """
    connections = manager.get_session_connections(session_id)
    return {
        "session_id": session_id,
        "connections": connections,
        "count": len(connections),
    }


@router.get("/api/websocket/debug/connection-test")
async def websocket_connection_test(
    origin: Optional[str] = Header(None), user_agent: Optional[str] = Header(None)
):
    """
    Debug endpoint to test WebSocket connection feasibility
    """
    origin_allowed = await validate_websocket_origin(origin) if origin else False
    environment = os.environ.get("ENVIRONMENT", "production")

    suggestions = []
    if not origin:
        suggestions.append(
            "Origin header is missing - ensure frontend sends Origin header"
        )
    elif not origin_allowed:
        if environment == "development":
            suggestions.append(
                "Add your origin to DEVELOPMENT_CORS_ORIGINS environment variable"
            )
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
        "timestamp": datetime.now().isoformat(),
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


@router.post("/api/websocket/sessions/{session_id}/polling/enable")
async def enable_polling_fallback(
    session_id: str,
    client_type: str,
    manager: WebSocketManager = Depends(get_websocket_manager),
):
    """
    Polling-Fallback für Session aktivieren
    """
    try:
        client_type_enum = ClientType(client_type.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid client type")

    polling_id = await manager.enable_polling_fallback(session_id, client_type_enum)

    return {
        "polling_id": polling_id,
        "session_id": session_id,
        "client_type": client_type,
        "polling_interval": manager.polling_interval,
    }


@router.get("/api/websocket/polling/{polling_id}/messages")
async def get_polling_messages(
    polling_id: str, manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Nachrichten für Polling-Client abrufen
    """
    messages = await manager.get_polling_messages(polling_id)
    return {
        "polling_id": polling_id,
        "messages": messages,
        "count": len(messages),
        "next_poll_in": manager.polling_interval,
    }
