"""The heartbeat: pings every socket, times the pongs, and closes the silent ones."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, Optional, Protocol

from .realtime_connection import WebSocketConnection, ensure_utc, utc_now
from .realtime_protocol import ConnectionState, heartbeat_ping_frame
from .realtime_registry import ConnectionRegistry
from .websocket_monitor import DisconnectReason, WebSocketMonitor

# The manager's own logger, so the heartbeat log lines keep their logger name.
logger = logging.getLogger("services.api_gateway.websocket")


class ConnectionCloser(Protocol):
    """What the heartbeat asks of the socket lifecycle when a socket fails it."""

    async def disconnect_websocket(
        self, connection_id: str, reason: str = "client_disconnect", code: int = 1000
    ) -> None: ...

    async def release_connection(self, connection_id: str, reason: DisconnectReason) -> None: ...


class Heartbeat:
    """One background task per app, started with the first socket.

    The lifespan stops it at shutdown (tests/test_realtime_heartbeat_shutdown.py).
    """

    def __init__(
        self,
        registry: ConnectionRegistry,
        monitor: WebSocketMonitor,
        closer: ConnectionCloser,
    ) -> None:
        self.registry = registry
        self.monitor = monitor
        self.closer = closer
        # Use the canonical 60s timeout for tests and reasonable production defaults.
        self.interval: float = 30  # Sekunden
        self.timeout: float = 60  # Sekunden (heartbeat timeout threshold)
        self.task: Optional[asyncio.Task[None]] = None

    @property
    def active(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self) -> None:
        """Startet das Heartbeat-Überwachungssystem"""
        if self.active:
            return

        self.task = asyncio.create_task(self.monitor_loop())
        await asyncio.sleep(0)
        logger.info("💓 Heartbeat-System gestartet")

    async def stop(self) -> None:
        """Stoppt das Heartbeat-System"""
        if self.task:
            self.task.cancel()
            results = await asyncio.gather(
                self.task,
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    logger.error("Heartbeat task shutdown error: %s", result)
            self.task = None
        logger.info("💓 Heartbeat-System gestoppt")

    async def monitor_loop(self) -> None:
        """
        Heartbeat-Überwachung im Hintergrund
        """
        logger.info("💓 Heartbeat-Monitor gestartet")

        try:
            while True:
                await asyncio.sleep(self.interval)
                await self.send_pings()
                await self.check_timeouts()

        except asyncio.CancelledError:
            logger.info("💓 Heartbeat-Monitor gestoppt")
            raise
        except Exception:
            logger.exception("Heartbeat monitor failed")

    async def send_pings(self) -> None:
        """
        Heartbeat-Pings an alle aktive Verbindungen senden
        """
        ping_message = heartbeat_ping_frame()

        dead_connections = []

        for connection_id, connection in self.registry.all_connections.items():
            if connection.state != ConnectionState.CONNECTED:
                continue

            # Set before the send: the receive loop can handle the reply while
            # send_json is still awaiting.
            connection.pending_ping_id = ping_message["ping_id"]
            connection.ping_sent_at = utc_now()
            try:
                await connection.websocket.send_json(ping_message)
            except Exception as e:
                logger.warning(f"💓 Heartbeat-Ping-Fehler {connection_id}: {e}")
                dead_connections.append(connection_id)

        # Tote Verbindungen cleanup
        for connection_id in dead_connections:
            await self.closer.release_connection(connection_id, DisconnectReason.CONNECTION_ERROR)

    async def check_timeouts(self) -> None:
        """
        Heartbeat-Timeouts prüfen und tote Verbindungen entfernen
        """
        timeout_threshold = utc_now() - timedelta(seconds=self.timeout)
        timeout_connections = []

        for connection_id, connection in self.registry.all_connections.items():
            if ensure_utc(connection.last_heartbeat) < timeout_threshold:
                timeout_connections.append(connection_id)
                self.registry.connection_stats["heartbeat_timeouts"] += 1

        for connection_id in timeout_connections:
            logger.warning(f"💓 Heartbeat-Timeout: {connection_id}")
            await self.closer.disconnect_websocket(connection_id, "heartbeat_timeout", 1001)

    async def handle_pong(
        self,
        connection_id: str,
        connection: WebSocketConnection,
        message: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Heartbeat-Pong verarbeiten
        """
        await asyncio.sleep(0)
        now = utc_now()
        latency = None
        echoed = (message or {}).get("ping_id")
        if (
            echoed is not None
            and echoed == connection.pending_ping_id
            and connection.ping_sent_at is not None
        ):
            latency = (now - ensure_utc(connection.ping_sent_at)).total_seconds()
            connection.pending_ping_id = None
            connection.ping_sent_at = None

        connection.last_heartbeat = now
        connection.state = ConnectionState.CONNECTED
        self.monitor.record_heartbeat(connection_id, latency)
