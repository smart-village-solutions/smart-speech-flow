"""Behavioral coverage for polling fallback and WebSocket monitoring APIs."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway import websocket_monitoring_routes as monitoring_routes
from services.api_gateway import websocket_polling_routes as polling_routes
from services.api_gateway.websocket_fallback import (
    FallbackConfig,
    FallbackReason,
    WebSocketFallbackManager,
    utc_now as fallback_utc_now,
)
from services.api_gateway.websocket_monitor import (
    DisconnectReason,
    WebSocketMonitor,
    utc_now as monitor_utc_now,
)


@pytest.mark.asyncio
async def test_fallback_activation_queues_messages_and_suggests_recovery(monkeypatch):
    """Polling clients receive queued messages and due recovery instructions."""
    manager = WebSocketFallbackManager(
        FallbackConfig(enable_jitter=False, enable_user_notifications=False)
    )
    monkeypatch.setattr("services.api_gateway.websocket_fallback.time.time", lambda: 42)

    polling_id = await manager.activate_polling_fallback(
        "session-1",
        "admin",
        "https://console.example",
        FallbackReason.NETWORK_ERROR,
    )
    assert polling_id == "poll_session-1_admin_42"
    assert manager.send_message_to_polling_client(polling_id, {"type": "transcript"})

    client = manager.polling_clients[polling_id]
    client.websocket_retry_after = fallback_utc_now() - timedelta(seconds=1)
    messages = manager.poll_messages(polling_id)

    assert messages[0]["type"] == "transcript"
    assert messages[0]["_polling_meta"]["polling_id"] == polling_id
    assert messages[1]["type"] == "websocket_retry_suggestion"
    assert manager.get_polling_client_status(polling_id)["last_poll"] is not None


def test_fallback_records_repeated_failures_and_recovery_cleanup():
    """Failure history triggers fallback and successful recovery removes the client."""
    manager = WebSocketFallbackManager(
        FallbackConfig(enable_jitter=False, enable_user_notifications=False)
    )

    assert not manager.evaluate_websocket_failure(
        "session-2", "customer", None, {"message": "network unavailable"}
    )
    assert manager.evaluate_websocket_failure(
        "session-2", "customer", None, {"message": "network unavailable"}
    )

    polling_id = "poll-session-2"
    manager.polling_clients[polling_id] = SimpleNamespace(
        session_id="session-2", message_queue=[]
    )
    manager.session_polling_clients["session-2"].add(polling_id)
    manager.websocket_recovery_successful(polling_id)

    assert polling_id not in manager.polling_clients
    assert manager.fallback_stats["successful_recoveries"] == 1


def test_polling_routes_return_recovery_and_failure_responses(monkeypatch):
    """Public polling handlers map manager recovery results to API responses."""
    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "attempt_websocket_recovery",
        lambda _polling_id: {
            "success": True,
            "recovery_info": {"session_id": "SESSION1", "client_type": "admin"},
        },
    )
    success = polling_routes.attempt_websocket_recovery("poll-1")

    assert success.status_code == 200
    assert b"/ws/SESSION1/admin" in success.body

    failed_reasons = []
    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "websocket_recovery_failed",
        lambda polling_id, reason: failed_reasons.append((polling_id, reason)),
    )
    failure = polling_routes.websocket_recovery_failed("poll-1", "not-a-reason")

    assert failure.status_code == 200
    assert failed_reasons == [("poll-1", FallbackReason.WEBSOCKET_CONNECTION_FAILED)]


def test_monitor_tracks_connection_lifecycle_and_health():
    """The real monitor tracks traffic, errors, and stale connection health."""
    monitor = WebSocketMonitor(registry=CollectorRegistry())
    metrics = monitor.connection_established(
        "connection-1", "session-3", "customer", "https://client.example:8443"
    )
    monitor.message_sent("connection-1", "hello", "chat")
    monitor.message_received("connection-1", "world", "chat")
    monitor.record_error("connection-1", "decode_error")
    metrics.last_heartbeat = monitor_utc_now() - timedelta(seconds=31)

    health = monitor.get_health_status()
    closed = monitor.connection_closed("connection-1", DisconnectReason.SERVER_DISCONNECT)

    assert health["status"] == "degraded"
    assert health["stale_connections"] == 1
    assert closed.messages_sent == 1
    assert closed.messages_received == 1
    assert closed.errors == 1
    assert monitor.get_connection_stats()["total_historical_connections"] == 1


def test_monitoring_routes_filter_connections_and_force_close(monkeypatch):
    """Monitoring endpoints serialize filters and close an existing connection."""
    now = monitor_utc_now()
    alpha = SimpleNamespace(
        session_id="session-a",
        client_type="admin",
        origin="https://admin.example",
        connect_time=now,
        last_heartbeat=now,
        messages_sent=2,
        messages_received=1,
        bytes_sent=10,
        bytes_received=5,
        errors=0,
    )
    beta = SimpleNamespace(**{**alpha.__dict__, "session_id": "session-b", "client_type": "customer"})
    monitor = Mock()
    monitor.get_active_connections.return_value = {"alpha": alpha, "beta": beta}
    monkeypatch.setattr(monitoring_routes, "get_websocket_monitor", lambda: monitor)

    response = monitoring_routes.list_active_connections(session_id="session-a")
    close_response = monitoring_routes.force_close_connection("alpha", "operator_request")

    assert response.status_code == 200
    assert b'"filtered_count":1' in response.body
    assert b'"connection_id":"alpha"' in response.body
    assert close_response.status_code == 200
    monitor.connection_closed.assert_called_once_with(
        connection_id="alpha", reason=DisconnectReason.SERVER_DISCONNECT
    )


def test_monitoring_health_and_summary_reflect_monitor_state(monkeypatch):
    """Health and summary endpoints retain monitor data and appropriate status codes."""
    monitor = Mock()
    monitor.get_health_status.return_value = {"status": "degraded", "active_connections": 2}
    monitor.get_connection_stats.return_value = {"active_connections": 2}
    monkeypatch.setattr(monitoring_routes, "get_websocket_monitor", lambda: monitor)

    health = monitoring_routes.websocket_health_check()
    summary = monitoring_routes.websocket_metrics_summary(hours=4)

    assert health.status_code == 503
    assert b'"active_connections":2' in health.body
    assert summary.status_code == 200
    assert b'"hours":4' in summary.body
