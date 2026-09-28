"""
WebSocket Monitoring System
Comprehensive metrics collection for WebSocket connections, performance tracking,
and health monitoring integrated with Prometheus.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Info

from .session_pseudonym import SessionPseudonymizer
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)

# The manager pings every 30 s and closes a socket after 60 s without a pong,
# so a heartbeat is only overdue once it is older than that timeout.
HEARTBEAT_STALE_AFTER_SECONDS = 60


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resource_log_fields(
    resource: TenantSessionKey, pseudonymizer: SessionPseudonymizer
) -> dict[str, str]:
    return {
        "tenant_ref": resource.tenant_ref,
        "session_ref": pseudonymizer.reference(resource.session_id),
    }


class ConnectionState(Enum):
    """WebSocket connection states"""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    TIMEOUT = "timeout"


class DisconnectReason(Enum):
    """WebSocket disconnect reasons.

    The values are the Prometheus label written to `websocket_disconnects_total`
    and matched by the WebSocketConnectionFailures and WebSocketOriginBlocked
    rules in monitoring/alert_rules.yml. Renaming one breaks an alert silently.
    """

    CLIENT_DISCONNECT = "client_disconnect"
    SERVER_DISCONNECT = "server_disconnect"
    CONNECTION_ERROR = "connection_error"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    SESSION_EXPIRED = "session_expired"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    AUTHENTICATION_FAILED = "authentication_failed"
    PROTOCOL_ERROR = "protocol_error"
    ORIGIN_NOT_ALLOWED = "origin_not_allowed"

    @classmethod
    def from_wire(cls, value: str) -> "DisconnectReason":
        """Map the free-text reason the socket layer passes around.

        Unknown values become PROTOCOL_ERROR, never CLIENT_DISCONNECT: an
        unrecognised cause is not evidence of a clean client exit, and folding
        it into the clean bucket is exactly the defect this replaces.
        """
        try:
            return cls(value)
        except ValueError:
            return _WIRE_ALIASES.get(value, cls.PROTOCOL_ERROR)


_WIRE_ALIASES = {
    "no_connections": DisconnectReason.SERVER_DISCONNECT,
    "session_timeout": DisconnectReason.SESSION_EXPIRED,
    "new_session_created": DisconnectReason.SERVER_DISCONNECT,
    "battery_optimization": DisconnectReason.SERVER_DISCONNECT,
    # handle_session_termination's default reason. A deliberate server-side
    # termination is not a fault, so it must not land in PROTOCOL_ERROR.
    "session_ended": DisconnectReason.SERVER_DISCONNECT,
    # An operator (or the operator-facing admin UI) ending a session on
    # purpose is a deliberate server-side termination, not a protocol
    # violation -- it must not land in PROTOCOL_ERROR either.
    "manual_termination": DisconnectReason.SERVER_DISCONNECT,
    "manual_admin_termination": DisconnectReason.SERVER_DISCONNECT,
    # terminate_all_active_sessions' default, and a member of the closed
    # SessionTerminationReason enum. Maintenance is a deliberate server-side
    # action; without this an operator's cleanup pages critical.
    "system_cleanup": DisconnectReason.SERVER_DISCONNECT,
    # _get_termination_message's inactivity reason -- the same event as
    # session_timeout, spelled differently by the caller.
    "timeout": DisconnectReason.SESSION_EXPIRED,
    # _get_termination_message's fault reason. It still pages, but it is a
    # connection error, not evidence the client broke the protocol.
    "error": DisconnectReason.CONNECTION_ERROR,
}


@dataclass
class ConnectionMetrics:
    """Connection-specific metrics data"""

    session_id: str
    resource_key: TenantSessionKey
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


class WebSocketMetrics:
    """The realtime Prometheus series, registered once on one registry.

    A series can be registered only once per registry, while every lifespan
    builds its own monitor, so create_app() builds this once per app on the
    registry that app's /metrics serves (`GatewayMetrics`), and each of the
    app's monitors counts into it. The names and labels are queried by
    monitoring/alert_rules.yml and the Grafana dashboards.
    """

    def __init__(self, registry: CollectorRegistry) -> None:
        self.connections_total = Counter(
            "websocket_connections_total",
            "Total number of WebSocket connections established",
            ["client_type"],
            registry=registry,
        )

        self.connections_active = Gauge(
            "websocket_connections_active",
            "Current number of active WebSocket connections",
            ["client_type"],
            registry=registry,
        )

        self.connections_duration = Histogram(
            "websocket_connection_duration_seconds",
            "WebSocket connection duration in seconds",
            ["client_type", "disconnect_reason"],
            buckets=[1, 5, 10, 30, 60, 300, 600, 1800, 3600, float("inf")],
            registry=registry,
        )

        self.messages_sent_total = Counter(
            "websocket_messages_sent_total",
            "Total number of messages sent via WebSocket",
            ["client_type"],
            registry=registry,
        )

        self.messages_received_total = Counter(
            "websocket_messages_received_total",
            "Total number of messages received via WebSocket",
            ["client_type"],
            registry=registry,
        )

        self.message_size_bytes = Histogram(
            "websocket_message_size_bytes",
            "WebSocket message size in bytes",
            ["direction", "client_type"],
            buckets=[64, 256, 1024, 4096, 16384, 65536, 262144, float("inf")],
            registry=registry,
        )

        self.errors_total = Counter(
            "websocket_errors_total",
            "Total number of WebSocket errors",
            ["client_type"],
            registry=registry,
        )

        self.disconnects_total = Counter(
            "websocket_disconnects_total",
            "Total number of WebSocket disconnections",
            ["client_type", "disconnect_reason"],
            registry=registry,
        )

        self.heartbeat_latency = Histogram(
            "websocket_heartbeat_latency_seconds",
            "WebSocket heartbeat response latency",
            ["client_type"],
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, float("inf")],
            registry=registry,
        )

        self.sessions_with_connections = Gauge(
            "websocket_sessions_with_connections",
            "Number of sessions with active WebSocket connections",
            registry=registry,
        )

        self.connections_per_session = Histogram(
            "websocket_connections_per_session",
            "Number of WebSocket connections per session",
            buckets=[1, 2, 3, 4, 5, 10, 20, float("inf")],
            registry=registry,
        )

        self.system_info = Info(
            "websocket_system_info",
            "WebSocket system information",
            registry=registry,
        )

        self.broadcast_total = Counter(
            "websocket_broadcast_total",
            "Total number of broadcast operations",
            ["sender_type"],
            registry=registry,
        )

        self.broadcast_success_total = Counter(
            "websocket_broadcast_success_total",
            "Total number of successful broadcast operations",
            ["sender_type"],
            registry=registry,
        )

        self.broadcast_failure_total = Counter(
            "websocket_broadcast_failure_total",
            "Total number of failed broadcast operations",
            ["sender_type", "reason"],
            registry=registry,
        )

        self.broadcast_messages_delivered = Counter(
            "websocket_broadcast_messages_delivered_total",
            "Total number of messages successfully delivered in broadcasts",
            ["sender_type"],
            registry=registry,
        )

        self.broadcast_messages_failed = Counter(
            "websocket_broadcast_messages_failed_total",
            "Total number of messages that failed to deliver in broadcasts",
            ["sender_type"],
            registry=registry,
        )

        self.system_info.info(
            {
                "version": "1.0.0",
                "monitoring_enabled": "true",
                "max_connections_per_session": "10",
            }
        )

        # Counted only by the legacy polling fallback (websocket_fallback.py), which
        # nothing registered reaches any more; kept exposed until PR7 deletes it.
        self.polling_messages_dropped = Counter(
            "websocket_polling_messages_dropped_total",
            "Messages discarded because a polling client's queue was full",
            ["client_type"],
            registry=registry,
        )

        # The ssf-overview dashboard's "monitor initialised" panel reads this.
        self.monitor_initialized = Gauge(
            "websocket_monitor_initialized",
            "WebSocket monitor initialization indicator",
            registry=registry,
        )
        self.monitor_initialized.set(1)


class WebSocketMonitor:
    """One app's view of its WebSocket connections: live records, history and sessions.

    `build_gateway_dependencies` builds one per app, with the app's realtime
    series and the pseudonymizer the app's session manager also uses, so a
    session's log lines correlate across both.
    """

    def __init__(self, metrics: WebSocketMetrics, pseudonymizer: SessionPseudonymizer) -> None:
        self.metrics = metrics
        self._pseudonymizer = pseudonymizer
        self._active_connections: Dict[str, ConnectionMetrics] = {}
        self._connection_history: List[ConnectionMetrics] = []
        self._session_connections: Dict[TenantSessionKey, Set[str]] = defaultdict(set)

        # Performance tracking
        self._performance_samples: List[Dict[str, Any]] = []
        self._max_history_size = 10000

    @property
    def pseudonymizer(self) -> SessionPseudonymizer:
        return self._pseudonymizer

    def connection_established(
        self,
        connection_id: str,
        session_id: str,
        client_type: str,
        origin: Optional[str] = None,
        *,
        resource_key: TenantSessionKey,
    ) -> ConnectionMetrics:
        """Record new WebSocket connection establishment"""

        metrics = ConnectionMetrics(
            session_id=session_id,
            client_type=client_type,
            origin=origin,
            connect_time=utc_now(),
            resource_key=resource_key,
        )

        self._active_connections[connection_id] = metrics
        self._session_connections[metrics.resource_key].add(connection_id)

        # Update Prometheus metrics
        self.metrics.connections_total.labels(client_type=client_type).inc()

        self.metrics.connections_active.labels(client_type=client_type).inc()
        self.metrics.sessions_with_connections.set(len(self._session_connections))

        fields = _resource_log_fields(metrics.resource_key, self._pseudonymizer)
        logger.info("websocket_connection_established", extra=fields)
        return metrics

    def connection_closed(
        self,
        connection_id: str,
        reason: DisconnectReason = DisconnectReason.CLIENT_DISCONNECT,
    ) -> Optional[ConnectionMetrics]:
        """Record WebSocket connection closure"""

        metrics = self._forget(connection_id)
        if not metrics:
            logger.warning("websocket_connection_close_not_found")
            return None

        # Update connection metrics
        metrics.disconnect_time = utc_now()
        metrics.disconnect_reason = reason
        metrics.connection_duration = (
            metrics.disconnect_time - metrics.connect_time
        ).total_seconds()

        self.metrics.connections_duration.labels(
            client_type=metrics.client_type, disconnect_reason=reason.value
        ).observe(metrics.connection_duration)
        self.metrics.disconnects_total.labels(
            client_type=metrics.client_type, disconnect_reason=reason.value
        ).inc()

        # Add to history
        self._connection_history.append(metrics)
        self._trim_history()

        logger.info(
            "websocket_connection_closed",
            extra={
                **_resource_log_fields(metrics.resource_key, self._pseudonymizer),
                "client_type": metrics.client_type,
                "disconnect_reason": reason.value,
            },
        )
        return metrics

    def _forget(self, connection_id: str) -> Optional[ConnectionMetrics]:
        """Drop a record from the live gauges without counting a disconnect."""
        metrics = self._active_connections.pop(connection_id, None)
        if not metrics:
            return None

        self._session_connections[metrics.resource_key].discard(connection_id)
        if not self._session_connections[metrics.resource_key]:
            del self._session_connections[metrics.resource_key]

        self.metrics.connections_active.labels(client_type=metrics.client_type).dec()
        self.metrics.sessions_with_connections.set(len(self._session_connections))
        return metrics

    def record_rejected_connection(self, reason: DisconnectReason) -> None:
        """Count a socket refused before it was ever registered.

        `connection_closed` cannot serve these: there is no ConnectionMetrics to
        pop, so it logs "non-existent connection" and returns None. The
        WebSocketOriginBlocked alert needs the counter incremented anyway.
        """
        self.metrics.disconnects_total.labels(
            client_type="unknown", disconnect_reason=reason.value
        ).inc()

    def message_sent(
        self, connection_id: str, message_data: str, _message_type: str = "unknown"
    ) -> None:
        """Record outbound message"""
        metrics = self._active_connections.get(connection_id)
        if not metrics:
            return

        message_size = len(message_data.encode("utf-8"))
        metrics.messages_sent += 1
        metrics.bytes_sent += message_size

        # Update Prometheus metrics
        self.metrics.messages_sent_total.labels(
            client_type=metrics.client_type,
        ).inc()

        self.metrics.message_size_bytes.labels(
            direction="outbound", client_type=metrics.client_type
        ).observe(message_size)

    def message_received(
        self, connection_id: str, message_data: str, _message_type: str = "unknown"
    ) -> None:
        """Record inbound message"""
        metrics = self._active_connections.get(connection_id)
        if not metrics:
            return

        message_size = len(message_data.encode("utf-8"))
        metrics.messages_received += 1
        metrics.bytes_received += message_size

        # Update Prometheus metrics
        self.metrics.messages_received_total.labels(
            client_type=metrics.client_type,
        ).inc()

        self.metrics.message_size_bytes.labels(
            direction="inbound", client_type=metrics.client_type
        ).observe(message_size)

    def record_error(
        self, connection_id: str, _error_type: str, _error_details: Optional[str] = None
    ) -> None:
        """Record WebSocket error"""
        metrics = self._active_connections.get(connection_id)
        if not metrics:
            return

        metrics.errors += 1

        # Update Prometheus metrics
        self.metrics.errors_total.labels(
            client_type=metrics.client_type,
        ).inc()

        logger.error(
            "websocket_connection_error",
            extra={
                **_resource_log_fields(metrics.resource_key, self._pseudonymizer),
                "client_type": metrics.client_type,
            },
        )

    def record_heartbeat(self, connection_id: str, latency_seconds: Optional[float] = None) -> None:
        """Record a pong; latency is None when it answered no outstanding ping."""
        metrics = self._active_connections.get(connection_id)
        if not metrics:
            return

        metrics.last_heartbeat = utc_now()

        if latency_seconds is not None:
            self.metrics.heartbeat_latency.labels(client_type=metrics.client_type).observe(
                latency_seconds
            )

    def session_closed(self, session_id: TenantSessionKey, reason: str = "session_expired") -> None:
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
            "websocket_session_closed",
            extra={
                **_resource_log_fields(session_id, self._pseudonymizer),
                "disconnected_count": len(connection_ids),
            },
        )

    def get_active_connections(self) -> Dict[str, ConnectionMetrics]:
        """Get all active WebSocket connections"""
        return self._active_connections.copy()

    def get_session_connections(self, session_id: TenantSessionKey) -> List[ConnectionMetrics]:
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
        by_client_type: Dict[str, int] = {}
        by_session: Dict[TenantSessionKey, int] = {}

        stats: Dict[str, Any] = {
            "active_connections": len(active_connections),
            "sessions_with_connections": len(self._session_connections),
            "total_historical_connections": len(self._connection_history),
            "connections_by_client_type": by_client_type,
            "connections_by_session": by_session,
            "average_connection_duration": 0,
            "message_throughput": {"sent_per_second": 0, "received_per_second": 0},
        }

        # Group by client type
        for metrics in active_connections:
            client_type = metrics.client_type
            by_client_type[client_type] = by_client_type.get(client_type, 0) + 1

        # Group by session
        for session_id, connection_ids in self._session_connections.items():
            by_session[session_id] = len(connection_ids)

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
                if time_since_heartbeat <= HEARTBEAT_STALE_AFTER_SECONDS:
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

    def _trim_history(self) -> None:
        """Trim connection history to prevent memory growth"""
        if len(self._connection_history) > self._max_history_size:
            # Keep most recent entries
            excess = len(self._connection_history) - self._max_history_size
            self._connection_history = self._connection_history[excess:]

    def _purge_orphaned_records(self, live_connection_ids: Iterable[str]) -> List[str]:
        live = set(live_connection_ids)
        orphaned = [cid for cid in self._active_connections if cid not in live]
        for connection_id in orphaned:
            self._forget(connection_id)
        return orphaned

    async def periodic_cleanup(self, live_connection_ids: Callable[[], Iterable[str]]) -> None:
        """Purge records for sockets the WebSocketManager no longer holds.

        It never closes or times out a connection. The manager owns the
        heartbeat and records every real close through `connection_closed`;
        this cleanup used to record heartbeat_timeout for any socket older
        than 300 s while it was still open, and the real close was then lost.
        A purged record counts no disconnect, because its cause is unknown.
        """
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                orphaned = self._purge_orphaned_records(live_connection_ids())
                if orphaned:
                    logger.warning(
                        "websocket_orphaned_records_purged",
                        extra={"connection_count": len(orphaned)},
                    )

            except Exception:
                logger.exception("WebSocket cleanup task failed")
