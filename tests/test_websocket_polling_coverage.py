"""Behavioral coverage for the WebSocket monitoring APIs."""

from datetime import timedelta
from unittest.mock import Mock

from prometheus_client import CollectorRegistry, generate_latest

from services.api_gateway import websocket_monitoring_routes as monitoring_routes
from services.api_gateway.tenant_session import TenantSessionKey
from services.api_gateway.websocket_monitor import DisconnectReason
from services.api_gateway.websocket_monitor import utc_now as monitor_utc_now
from tests.realtime_sessions import websocket_monitor


def test_monitor_tracks_connection_lifecycle_and_health():
    """The real monitor tracks traffic, errors, and stale connection health."""
    monitor = websocket_monitor()
    metrics = monitor.connection_established(
        "connection-1",
        "session-3",
        "customer",
        "https://client.example:8443",
        resource_key=TenantSessionKey("tenant-a", "session-3"),
    )
    monitor.message_sent("connection-1", "hello", "chat")
    monitor.message_received("connection-1", "world", "chat")
    monitor.record_error("connection-1", "decode_error")
    metrics.last_heartbeat = monitor_utc_now() - timedelta(seconds=61)

    health = monitor.get_health_status()
    closed = monitor.connection_closed("connection-1", DisconnectReason.SERVER_DISCONNECT)

    assert health["status"] == "degraded"
    assert health["stale_connections"] == 1
    assert closed.messages_sent == 1
    assert closed.messages_received == 1
    assert closed.errors == 1
    assert monitor.get_connection_stats()["total_historical_connections"] == 1


def test_websocket_prometheus_metrics_have_no_session_label():
    registry = CollectorRegistry()
    monitor = websocket_monitor(registry)
    monitor.connection_established(
        "connection-1",
        "session-ref",
        "admin",
        resource_key=TenantSessionKey("tenant-a", "session-secret"),
    )
    monitor.message_sent("connection-1", "hello", "chat")
    monitor.record_error("connection-1", "decode_error")

    output = generate_latest(registry).decode("utf-8")

    assert "session_id=" not in output
    assert "session-secret" not in output


def test_monitoring_health_reflects_monitor_state():
    """The health endpoint retains monitor data and answers 503 when degraded."""
    monitor = Mock()
    monitor.get_health_status.return_value = {"status": "degraded", "active_connections": 2}

    health = monitoring_routes.websocket_health_check(monitor)

    assert health.status_code == 503
    assert b'"active_connections":2' in health.body
