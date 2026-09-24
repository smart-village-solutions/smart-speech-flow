"""Which sockets an app holds, keyed by tenant session and by connection id."""

from __future__ import annotations

from typing import Dict, Optional
from uuid import uuid4

from .realtime_connection import WebSocketConnection, safe_identifier
from .session_manager import ClientType
from .tenant_session import TenantSessionKey


class ConnectionRegistry:
    """The socket pools of one app.

    Sessions are keyed by `TenantSessionKey`, never by the bare session id, so
    two tenants' sessions that share an id keep separate pools.
    """

    def __init__(self) -> None:
        # Session-basierte Connection-Pools
        self.session_connections: Dict[TenantSessionKey, Dict[str, WebSocketConnection]] = {}
        # Global Connection Tracking für Monitoring
        self.all_connections: Dict[str, WebSocketConnection] = {}
        self.connection_stats = {
            "total_connections": 0,
            "active_connections": 0,
            "failed_connections": 0,
            "heartbeat_timeouts": 0,
            "reconnects": 0,
        }

    @staticmethod
    def build_connection_id(session_id: TenantSessionKey, client_type: ClientType) -> str:
        """A connection id must be unique, not merely descriptive.

        The previous form ended in `int(time.time())`, so two sockets opened for
        one session inside the same second collided — and the monitor keys its
        active-connection map by this value, so the loser's metrics silently
        became the winner's. Reconnect storms are when that happens and when the
        connection KPIs matter most.
        """
        scope = f"{session_id.tenant_ref}_{safe_identifier(session_id.session_id)}"
        return f"{scope}_{client_type.value}_{uuid4().hex[:12]}"

    def registered_connection_id(self, connection: WebSocketConnection) -> Optional[str]:
        """The id this connection is registered under, or None if it is not.

        Callers that hold a connection object and need its id must ask the map
        that broadcast_to_session iterates. Rebuilding the id from the
        connection's own fields worked only while it ended in a timestamp the
        caller could recompute, and silently stopped matching anything once ids
        became unique -- which included the sender in its own broadcast.
        """
        for connection_id, candidate in self.session_connections.get(connection.key, {}).items():
            if candidate is connection:
                return connection_id
        return None

    def tracked_connection_id(self, connection: WebSocketConnection) -> Optional[str]:
        """The id under which `connection` is still tracked app-wide, if any.

        A terminating session's pool is gone before its sockets close, so only
        the app-wide map still knows them.
        """
        for connection_id, candidate in self.all_connections.items():
            if candidate == connection:
                return connection_id
        return None

    def get(self, connection_id: str) -> Optional[WebSocketConnection]:
        return self.all_connections.get(connection_id)

    def session(self, session_id: TenantSessionKey) -> Optional[Dict[str, WebSocketConnection]]:
        return self.session_connections.get(session_id)

    def add(self, connection_id: str, connection: WebSocketConnection) -> None:
        if connection.key not in self.session_connections:
            self.session_connections[connection.key] = {}

        self.session_connections[connection.key][connection_id] = connection
        self.all_connections[connection_id] = connection

    def pop_session(self, session_id: TenantSessionKey) -> list[WebSocketConnection]:
        """Detach a session's pool; its sockets stay tracked until each one is released."""
        pool = self.session_connections.pop(session_id, None)
        return list(pool.values()) if pool is not None else []

    def remove(self, connection_id: str) -> Optional[WebSocketConnection]:
        connection = self.all_connections.get(connection_id)
        if not connection:
            return None

        # Aus Session-Pool entfernen
        resource_key = connection.key
        if resource_key in self.session_connections:
            self.session_connections[resource_key].pop(connection_id, None)

            # Wenn Session keine Verbindungen mehr hat, Pool löschen
            if not self.session_connections[resource_key]:
                del self.session_connections[resource_key]

        # Aus globalem Pool entfernen
        self.all_connections.pop(connection_id, None)
        return connection

    def update_active_connections_count(self) -> None:
        """
        Aktive Verbindungen zählen
        """
        active_count = sum(1 for c in self.all_connections.values() if c.is_alive())
        self.connection_stats["active_connections"] = active_count
