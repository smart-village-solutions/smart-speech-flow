"""
WebSocket Monitoring System
Comprehensive metrics collection for WebSocket connections, performance tracking,
and health monitoring integrated with Prometheus.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from prometheus_client import Counter, Gauge, Histogram, Info

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ConnectionState(Enum):
    """WebSocket connection states"""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    TIMEOUT = "timeout"


class DisconnectReason(Enum):
    """WebSocket disconnect reasons"""

    CLIENT_DISCONNECT = "client_disconnect"
    SERVER_DISCONNECT = "server_disconnect"
    CONNECTION_ERROR = "connection_error"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    SESSION_EXPIRED = "session_expired"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    AUTHENTICATION_FAILED = "authentication_failed"
    PROTOCOL_ERROR = "protocol_error"


@dataclass
class ConnectionMetrics:
    """Connection-specific metrics data"""

    session_id: str
    client_type: str
    origin: Optional[str]
    connect_time: datetime
    disconnect_time: Optional[datetime] = None
    disconnect_reason: Optional[DisconnectReason] = None
    last_heartbeat: Optional[datetime] = None
    messages_sent: int = 0
    messages_received: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    errors: int = 0
    connection_duration: Optional[float] = None


class WebSocketMonitor:
    """
    Comprehensive WebSocket monitoring system with Prometheus integration
    """

    def __init__(self, registry=None):
        self._active_connections: Dict[str, ConnectionMetrics] = {}
        self._connection_history: List[ConnectionMetrics] = []
        self._session_connections: Dict[str, Set[str]] = defaultdict(set)

        # Store registry for Prometheus metrics
        # Falls keine Registry übergeben wird, verwende die Standard-Registry
        if registry is None:
            from prometheus_client import REGISTRY

            self._registry = REGISTRY
        else:
            self._registry = registry

        # Prometheus Metrics
        self._setup_prometheus_metrics()

        # Performance tracking
        self._performance_samples: List[Dict[str, Any]] = []
        self._max_history_size = 10000

    def _setup_prometheus_metrics(self):
        """Initialize Prometheus metrics for WebSocket monitoring"""

        # Connection Metrics
        self.connections_total = Counter(
            "websocket_connections_total",
            "Total number of WebSocket connections established",
            ["session_id", "client_type", "origin_domain"],
            registry=self._registry,
        )

        self.connections_active = Gauge(
            "websocket_connections_active",
            "Current number of active WebSocket connections",
            ["client_type"],
            registry=self._registry,
        )

        self.connections_duration = Histogram(
            "websocket_connection_duration_seconds",
            "WebSocket connection duration in seconds",
            ["client_type", "disconnect_reason"],
            buckets=[1, 5, 10, 30, 60, 300, 600, 1800, 3600, float("inf")],
            registry=self._registry,
        )

        # Message Metrics
        self.messages_sent_total = Counter(
            "websocket_messages_sent_total",
            "Total number of messages sent via WebSocket",
            ["session_id", "client_type", "message_type"],
            registry=self._registry,
        )

        self.messages_received_total = Counter(
            "websocket_messages_received_total",
            "Total number of messages received via WebSocket",
            ["session_id", "client_type", "message_type"],
            registry=self._registry,
        )

        self.message_size_bytes = Histogram(
            "websocket_message_size_bytes",
            "WebSocket message size in bytes",
            ["direction", "client_type"],
            buckets=[64, 256, 1024, 4096, 16384, 65536, 262144, float("inf")],
            registry=self._registry,
        )

        # Error Metrics
        self.errors_total = Counter(
            "websocket_errors_total",
            "Total number of WebSocket errors",
            ["session_id", "client_type", "error_type"],
            registry=self._registry,
        )

        self.disconnects_total = Counter(
            "websocket_disconnects_total",
            "Total number of WebSocket disconnections",
            ["client_type", "disconnect_reason"],
            registry=self._registry,
        )

        # Performance Metrics
        self.heartbeat_latency = Histogram(
            "websocket_heartbeat_latency_seconds",
            "WebSocket heartbeat response latency",
            ["session_id", "client_type"],
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, float("inf")],
            registry=self._registry,
        )

        # Session Metrics
        self.sessions_with_connections = Gauge(
            "websocket_sessions_with_connections",
            "Number of sessions with active WebSocket connections",
            registry=self._registry,
        )

        self.connections_per_session = Histogram(
            "websocket_connections_per_session",
            "Number of WebSocket connections per session",
            buckets=[1, 2, 3, 4, 5, 10, 20, float("inf")],
            registry=self._registry,
        )

        # System Health
        self.system_info = Info(
            "websocket_system_info",
            "WebSocket system information",
            registry=self._registry,
        )

        # Broadcast Metrics (Task 4.8)
        self.broadcast_total = Counter(
            "websocket_broadcast_total",
            "Total number of broadcast operations",
            ["session_id", "sender_type"],
            registry=self._registry,
        )

        self.broadcast_success_total = Counter(
            "websocket_broadcast_success_total",
            "Total number of successful broadcast operations",
            ["session_id", "sender_type"],
            registry=self._registry,
        )

        self.broadcast_failure_total = Counter(
            "websocket_broadcast_failure_total",
            "Total number of failed broadcast operations",
            ["session_id", "sender_type", "reason"],
            registry=self._registry,
        )

        self.broadcast_messages_delivered = Counter(
            "websocket_broadcast_messages_delivered_total",
            "Total number of messages successfully delivered in broadcasts",
            ["session_id", "sender_type"],
            registry=self._registry,
        )

        self.broadcast_messages_failed = Counter(
            "websocket_broadcast_messages_failed_total",
            "Total number of messages that failed to deliver in broadcasts",
            ["session_id", "sender_type"],
            registry=self._registry,
        )

        # Initialize system info
        self.system_info.info(
            {
                "version": "1.0.0",
                "monitoring_enabled": "true",
                "max_connections_per_session": "10",
            }
        )

    def connection_established(
        self,
        connection_id: str,
        session_id: str,
        client_type: str,
        origin: Optional[str] = None,
    ) -> ConnectionMetrics:
        """Record new WebSocket connection establishment"""

        metrics = ConnectionMetrics(
            session_id=session_id,
            client_type=client_type,
            origin=origin,
            connect_time=utc_now(),
        )

        self._active_connections[connection_id] = metrics
        self._session_connections[session_id].add(connection_id)

        # Update Prometheus metrics
        origin_domain = self._extract_domain(origin) if origin else "unknown"
        self.connections_total.labels(
            session_id=session_id, client_type=client_type, origin_domain=origin_domain
        ).inc()

        self.connections_active.labels(client_type=client_type).inc()
        self.sessions_with_connections.set(len(self._session_connections))

        logger.info(
            f"WebSocket connection established: {connection_id} for session {session_id}"
        )
        return metrics

    def connection_closed(
        self,
        connection_id: str,
        reason: DisconnectReason = DisconnectReason.CLIENT_DISCONNECT,
    ) -> Optional[ConnectionMetrics]:
        """Record WebSocket connection closure"""

        metrics = self._active_connections.pop(connection_id, None)
        if not metrics:
            logger.warning(
                f"Attempted to close non-existent connection: {connection_id}"
            )
            return None

        # Update connection metrics
        metrics.disconnect_time = utc_now()
        metrics.disconnect_reason = reason
        metrics.connection_duration = (
            metrics.disconnect_time - metrics.connect_time
        ).total_seconds()

        # Remove from session tracking
        self._session_connections[metrics.session_id].discard(connection_id)
        if not self._session_connections[metrics.session_id]:
            del self._session_connections[metrics.session_id]

        # Update Prometheus metrics
        self.connections_active.labels(client_type=metrics.client_type).dec()
        self.connections_duration.labels(
            client_type=metrics.client_type, disconnect_reason=reason.value
        ).observe(metrics.connection_duration)
        self.disconnects_total.labels(
            client_type=metrics.client_type, disconnect_reason=reason.value
        ).inc()

        self.sessions_with_connections.set(len(self._session_connections))

        # Add to history
        self._connection_history.append(metrics)
        self._trim_history()

        logger.info(
            f"WebSocket connection closed: {connection_id} "
            f"(duration: {metrics.connection_duration:.2f}s, reason: {reason.value})"
        )
        return metrics

    def message_sent(
        self, connection_id: str, message_data: str, message_type: str = "unknown"
    ):
        """Record outbound message"""
        metrics = self._active_connections.get(connection_id)
        if not metrics:
            return

        message_size = len(message_data.encode("utf-8"))
        metrics.messages_sent += 1
        metrics.bytes_sent += message_size

        # Update Prometheus metrics
        self.messages_sent_total.labels(
            session_id=metrics.session_id,
            client_type=metrics.client_type,
            message_type=message_type,
        ).inc()

        self.message_size_bytes.labels(
            direction="outbound", client_type=metrics.client_type
        ).observe(message_size)

    def message_received(
        self, connection_id: str, message_data: str, message_type: str = "unknown"
    ):
        """Record inbound message"""
        metrics = self._active_connections.get(connection_id)
        if not metrics:
            return

        message_size = len(message_data.encode("utf-8"))
        metrics.messages_received += 1
        metrics.bytes_received += message_size

        # Update Prometheus metrics
        self.messages_received_total.labels(
            session_id=metrics.session_id,
            client_type=metrics.client_type,
            message_type=message_type,
        ).inc()

        self.message_size_bytes.labels(
            direction="inbound", client_type=metrics.client_type
        ).observe(message_size)

    def record_error(
        self, connection_id: str, error_type: str, error_details: Optional[str] = None
    ):
        """Record WebSocket error"""
        metrics = self._active_connections.get(connection_id)
        if not metrics:
            return

        metrics.errors += 1

        # Update Prometheus metrics
        self.errors_total.labels(
            session_id=metrics.session_id,
            client_type=metrics.client_type,
            error_type=error_type,
        ).inc()

        logger.error(
            f"WebSocket error on connection {connection_id}: {error_type} - {error_details}"
        )

    def record_heartbeat(self, connection_id: str, latency_seconds: float):
        """Record heartbeat response time"""
        metrics = self._active_connections.get(connection_id)
        if not metrics:
            return

        metrics.last_heartbeat = utc_now()

        # Update Prometheus metrics
        self.heartbeat_latency.labels(
            session_id=metrics.session_id, client_type=metrics.client_type
        ).observe(latency_seconds)

    def session_closed(self, session_id: str, reason: str = "session_expired"):
        """Handle session closure - disconnect all associated WebSocket connections"""
        connection_ids = list(self._session_connections.get(session_id, []))

        for connection_id in connection_ids:
            self.connection_closed(
                connection_id,
                (
                    DisconnectReason.SESSION_EXPIRED
                    if reason == "session_expired"
                    else DisconnectReason.SERVER_DISCONNECT
                ),
            )

        logger.info(
            f"Session {session_id} closed, disconnected {len(connection_ids)} WebSocket connections"
        )

    def get_active_connections(self) -> Dict[str, ConnectionMetrics]:
        """Get all active WebSocket connections"""
        return self._active_connections.copy()

    def get_session_connections(self, session_id: str) -> List[ConnectionMetrics]:
        """Get all active connections for a specific session"""
        connection_ids = self._session_connections.get(session_id, set())
        return [
            self._active_connections[conn_id]
            for conn_id in connection_ids
            if conn_id in self._active_connections
        ]

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get comprehensive connection statistics"""
        active_connections = list(self._active_connections.values())

        stats = {
            "active_connections": len(active_connections),
            "sessions_with_connections": len(self._session_connections),
            "total_historical_connections": len(self._connection_history),
            "connections_by_client_type": {},
            "connections_by_session": {},
            "average_connection_duration": 0,
            "message_throughput": {"sent_per_second": 0, "received_per_second": 0},
        }

        # Group by client type
        for metrics in active_connections:
            client_type = metrics.client_type
            if client_type not in stats["connections_by_client_type"]:
                stats["connections_by_client_type"][client_type] = 0
            stats["connections_by_client_type"][client_type] += 1

        # Group by session
        for session_id, connection_ids in self._session_connections.items():
            stats["connections_by_session"][session_id] = len(connection_ids)

        # Calculate average duration from history
        if self._connection_history:
            durations = [
                conn.connection_duration
                for conn in self._connection_history
                if conn.connection_duration is not None
            ]
            if durations:
                stats["average_connection_duration"] = sum(durations) / len(durations)

        return stats

    def get_health_status(self) -> Dict[str, Any]:
        """Get WebSocket system health status"""
        now = utc_now()
        healthy_connections = 0
        stale_connections = 0

        for metrics in self._active_connections.values():
            if metrics.last_heartbeat:
                time_since_heartbeat = (now - metrics.last_heartbeat).total_seconds()
                if time_since_heartbeat < 30:  # Healthy if heartbeat within 30s
                    healthy_connections += 1
                else:
                    stale_connections += 1

        return {
            "status": "healthy" if stale_connections == 0 else "degraded",
            "active_connections": len(self._active_connections),
            "healthy_connections": healthy_connections,
            "stale_connections": stale_connections,
            "sessions_with_connections": len(self._session_connections),
            "monitoring_active": True,
            "last_check": now.isoformat(),
        }

    def _extract_domain(self, origin: str) -> str:
        """Extract domain from origin URL"""
        try:
            if "://" in origin:
                domain = origin.split("://")[1]
            else:
                domain = origin

            # Remove port if present
            if ":" in domain:
                domain = domain.split(":")[0]

            return domain
        except Exception:
            return "unknown"

    def _trim_history(self):
        """Trim connection history to prevent memory growth"""
        if len(self._connection_history) > self._max_history_size:
            # Keep most recent entries
            excess = len(self._connection_history) - self._max_history_size
            self._connection_history = self._connection_history[excess:]

    def _find_stale_connections(self, now: datetime) -> List[str]:
        stale_connections: List[str] = []
        for connection_id, metrics in self._active_connections.items():
            if metrics.last_heartbeat:
                time_since_heartbeat = (now - metrics.last_heartbeat).total_seconds()
                if time_since_heartbeat > 300:
                    stale_connections.append(connection_id)
                continue

            connection_age = (now - metrics.connect_time).total_seconds()
            if connection_age > 300:
                stale_connections.append(connection_id)
        return stale_connections

    async def periodic_cleanup(self):
        """Periodic cleanup task for stale connections"""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                now = utc_now()
                stale_connections = self._find_stale_connections(now)

                # Clean up stale connections
                for connection_id in stale_connections:
                    self.connection_closed(
                        connection_id, DisconnectReason.HEARTBEAT_TIMEOUT
                    )
                    logger.warning(
                        f"Cleaned up stale WebSocket connection: {connection_id}"
                    )

                if stale_connections:
                    logger.info(
                        f"Cleaned up {len(stale_connections)} stale WebSocket connections"
                    )

            except Exception as e:
                logger.error(f"Error in WebSocket cleanup task: {e}")


# Global WebSocket Monitor Instance
websocket_monitor = None


def initialize_websocket_monitor(registry=None):
    """Initialize the global WebSocket monitor with the given registry"""
    global websocket_monitor
    if websocket_monitor is None:
        websocket_monitor = WebSocketMonitor(registry=registry)

        # Test-Metrik hinzufügen um Registry-Verbindung zu bestätigen
        if registry is not None:
            from prometheus_client import Gauge

            test_metric = Gauge(
                "websocket_monitor_initialized",
                "WebSocket monitor initialization indicator",
                registry=registry,
            )
            test_metric.set(1)

    return websocket_monitor


def get_websocket_monitor():
    """Get the websocket monitor instance, should already be initialized by app startup"""
    global websocket_monitor
    if websocket_monitor is None:
        # Lazily initialize a default monitor for tests and simple setups
        # to avoid hard dependency on app startup ordering.
        initialize_websocket_monitor()
    return websocket_monitor
