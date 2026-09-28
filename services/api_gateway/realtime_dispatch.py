"""Delivery of one frame to every socket and poller of a tenant session."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

from .realtime_connection import WebSocketConnection, safe_identifier
from .realtime_protocol import ConnectionState, Frame
from .realtime_registry import ConnectionRegistry
from .session_manager import ClientType
from .tenant_session import TenantSessionKey
from .websocket_monitor import WebSocketMetrics, WebSocketMonitor

if TYPE_CHECKING:
    from .websocket_polling_routes import TenantPollingStore

# The manager's own logger, so the broadcast log lines keep their logger name.
logger = logging.getLogger("services.api_gateway.websocket")


@dataclass
class BroadcastResult:
    """Result of a broadcast operation"""

    success: bool
    total_connections: int
    successful_sends: int
    failed_sends: int
    session_has_connections: bool
    errors: List[str]
    messages_dropped: int = 0


class BroadcastDispatcher:
    """Sends to a session's sockets and, unless told otherwise, its pollers."""

    def __init__(
        self,
        registry: ConnectionRegistry,
        polling_store: Optional[TenantPollingStore],
        monitor: WebSocketMonitor,
    ) -> None:
        self.registry = registry
        # Tenant broadcasts also reach this app's HTTP pollers.
        self.polling_store = polling_store
        self.monitor = monitor

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
        if include_polling and self.polling_store is not None:
            self.polling_store.broadcast(session_id, message)

        connections = self.registry.session(session_id)
        if connections is None:
            return

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
                self.monitor.message_sent(
                    connection_id=connection_id,
                    message_data=str(message),
                    _message_type=message_type,
                )

            except Exception as e:
                logger.warning(f"⚠️ Broadcast-Fehler zu {connection_id}: {e}")
                failed_sends += 1

                # 📊 Monitoring: Error occurred
                self.monitor.record_error(
                    connection_id=connection_id,
                    _error_type="broadcast_error",
                    _error_details=str(e),
                )

                # Connection als tot markieren
                connection.state = ConnectionState.ERROR

        logger.debug(
            "websocket_broadcast session_ref=%s successful=%d failed=%d",
            safe_identifier(session_id.session_id),
            successful_sends,
            failed_sends,
        )

    async def broadcast_with_differentiated_content(
        self,
        session_id: TenantSessionKey,
        sender_type: ClientType,
        original_message: Frame,
        translated_message: Frame,
    ) -> BroadcastResult:
        """
        Differentiated Broadcasting with validation and error handling:
        - Sender erhält original_text (ASR-Bestätigung)
        - Empfänger erhält translated_text + audio

        Returns:
            BroadcastResult with success status and detailed metrics
        """
        metrics = self.monitor.metrics
        metric_session_id = safe_identifier(session_id.session_id)
        self.record_broadcast_attempt(metrics, metric_session_id, sender_type)

        errors: list[str] = []
        successful_sends = 0
        failed_sends = 0
        polling_delivered = 0
        polling_dropped = 0

        if self.polling_store is not None:
            polling_delivered, polling_dropped = self.polling_store.broadcast_differentiated(
                session_id,
                sender_type,
                original_message,
                translated_message,
            )
            successful_sends += polling_delivered
            if polling_dropped:
                errors.append("Polling recipient queue overflow")

        connections = self.registry.session(session_id)
        if connections is None:
            if polling_delivered:
                success = failed_sends == 0
                self.record_broadcast_summary(
                    metrics=metrics,
                    session_id=metric_session_id,
                    sender_type=sender_type,
                    total_connections=polling_delivered,
                    successful_sends=successful_sends,
                    failed_sends=failed_sends,
                    success=success,
                )
                return BroadcastResult(
                    success=success,
                    total_connections=polling_delivered,
                    successful_sends=successful_sends,
                    failed_sends=failed_sends,
                    session_has_connections=True,
                    errors=errors,
                    messages_dropped=polling_dropped,
                )
            return self.build_no_connection_broadcast_result(
                metrics, metric_session_id, sender_type
            )

        total_connections = len(connections) + polling_delivered

        # Task 4.3: Log connection count before broadcast
        logger.info(
            "websocket_differentiated_broadcast session_ref=%s connections=%d",
            metric_session_id,
            total_connections,
        )

        # Task 4.4: Check if manager has any connections at all
        if len(self.registry.all_connections) == 0:
            error_msg = "WebSocketManager has no connections at all"
            logger.error(f"❌ {error_msg}")
            errors.append(error_msg)

        for connection_id, connection in connections.items():
            if not connection.is_alive():
                failed_sends += 1
                errors.append(f"Connection {connection_id} is not alive")
                continue

            try:
                await self.send_differentiated_message(
                    connection=connection,
                    connection_id=connection_id,
                    sender_type=sender_type,
                    original_message=original_message,
                    translated_message=translated_message,
                )
                successful_sends += 1
            except Exception as e:
                failed_sends += 1
                error_msg = f"Failed to send to {connection_id}: {str(e)}"
                logger.warning(f"⚠️ {error_msg}")
                errors.append(error_msg)

        success = successful_sends > 0 and failed_sends == 0

        self.record_broadcast_summary(
            metrics=metrics,
            session_id=metric_session_id,
            sender_type=sender_type,
            total_connections=total_connections,
            successful_sends=successful_sends,
            failed_sends=failed_sends,
            success=success,
        )

        return BroadcastResult(
            success=success,
            total_connections=total_connections,
            successful_sends=successful_sends,
            failed_sends=failed_sends,
            session_has_connections=True,
            errors=errors,
            messages_dropped=polling_dropped,
        )

    def record_broadcast_attempt(
        self, metrics: WebSocketMetrics, session_id: str, sender_type: ClientType
    ) -> None:
        logger.debug(
            "WebSocket broadcast attempted",
            extra={"session_ref": safe_identifier(session_id)},
        )
        metrics.broadcast_total.labels(sender_type=sender_type.value).inc()

    def build_no_connection_broadcast_result(
        self, metrics: WebSocketMetrics, session_id: str, sender_type: ClientType
    ) -> BroadcastResult:
        logger.warning(
            "Broadcast attempted without active connections",
            extra={"session_ref": safe_identifier(session_id)},
        )
        metrics.broadcast_failure_total.labels(
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

    async def send_differentiated_message(
        self,
        *,
        connection: WebSocketConnection,
        connection_id: str,
        sender_type: ClientType,
        original_message: Frame,
        translated_message: Frame,
    ) -> None:
        if connection.client_type == sender_type:
            await connection.websocket.send_json(original_message)
            logger.debug(f"✓ Sent original message to sender {connection_id}")
            return

        await connection.websocket.send_json(translated_message)
        logger.debug(f"✓ Sent translated message to receiver {connection_id}")

    def record_broadcast_summary(
        self,
        *,
        metrics: WebSocketMetrics,
        session_id: str,
        sender_type: ClientType,
        total_connections: int,
        successful_sends: int,
        failed_sends: int,
        success: bool,
    ) -> None:
        if success:
            logger.info(
                f"✅ Broadcast successful: {successful_sends}/{total_connections} delivered",
                extra={"session_ref": safe_identifier(session_id)},
            )
            metrics.broadcast_success_total.labels(sender_type=sender_type.value).inc()
        else:
            logger.warning(
                f"⚠️ Broadcast partial/failed: {successful_sends} succeeded, "
                f"{failed_sends} failed out of {total_connections}",
                extra={"session_ref": safe_identifier(session_id)},
            )
            metrics.broadcast_failure_total.labels(
                sender_type=sender_type.value,
                reason=("partial_failure" if successful_sends > 0 else "complete_failure"),
            ).inc()

        if successful_sends > 0:
            metrics.broadcast_messages_delivered.labels(sender_type=sender_type.value).inc(
                successful_sends
            )
        if failed_sends > 0:
            metrics.broadcast_messages_failed.labels(sender_type=sender_type.value).inc(
                failed_sends
            )
