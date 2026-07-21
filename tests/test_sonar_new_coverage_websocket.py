"""Behavioral coverage for Sonar remediation paths in WebSocket services."""

import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.api_gateway.session_manager import ClientType, SessionManager, SessionStatus
from services.api_gateway.websocket import (
    ConnectionState,
    WebSocketConnection,
    WebSocketManager,
    websocket_endpoint,
)
from services.api_gateway.websocket_fallback import (
    FallbackReason,
    PollingClient,
    WebSocketFallbackManager,
)


class _Counter:
    def inc(self):
        pass


class _Metric:
    def labels(self, **_labels):
        return _Counter()


class _Monitor:
    broadcast_failure_total = _Metric()


@pytest.mark.asyncio
async def test_no_connection_broadcast_uses_redacted_warning(caplog):
    manager = WebSocketManager(SessionManager())

    with caplog.at_level(logging.WARNING):
        result = await manager.broadcast_with_differentiated_content(
            "SENSITIVE123",
            ClientType.ADMIN,
            {"type": "original"},
            {"type": "translated"},
        )

    assert result.session_has_connections is False
    assert "Broadcast attempted without active connections" in caplog.messages
    assert "SENSITIVE123" not in caplog.text


@pytest.mark.asyncio
async def test_heartbeat_monitor_logs_unexpected_failure(monkeypatch, caplog):
    manager = WebSocketManager(SessionManager())

    async def fail_sleep(_delay):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr("services.api_gateway.websocket.asyncio.sleep", fail_sleep)

    with caplog.at_level(logging.ERROR):
        await manager._heartbeat_monitor()

    assert "Heartbeat monitor failed" in caplog.messages


@pytest.mark.asyncio
async def test_fallback_evaluation_failure_is_logged(monkeypatch, caplog):
    manager = WebSocketManager(SessionManager())
    connection = WebSocketConnection(
        websocket=Mock(),
        client_type=ClientType.ADMIN,
        session_id="TEST1234",
        connected_at=datetime.now(timezone.utc),
        last_heartbeat=datetime.now(timezone.utc),
        state=ConnectionState.CONNECTED,
    )

    monkeypatch.setattr(
        "services.api_gateway.websocket.fallback_manager.evaluate_websocket_failure",
        Mock(side_effect=RuntimeError("fallback storage unavailable")),
    )

    with caplog.at_level(logging.ERROR):
        await manager._evaluate_connection_error(
            connection, RuntimeError("network interrupted"), "broadcast_error"
        )

    assert "Fallback evaluation failed" in caplog.messages


@pytest.mark.asyncio
async def test_endpoint_returns_error_message_after_message_handler_failure(
    monkeypatch, caplog
):
    websocket = SimpleNamespace(
        receive_json=AsyncMock(side_effect=RuntimeError("bad message")),
        send_json=AsyncMock(side_effect=RuntimeError("client disconnected")),
        close=AsyncMock(),
    )
    manager = SimpleNamespace(
        session_manager=SimpleNamespace(
            get_session=Mock(return_value=SimpleNamespace(status=SessionStatus.ACTIVE))
        ),
        connect_websocket=AsyncMock(return_value="connection-1"),
        handle_websocket_message=AsyncMock(),
        disconnect_websocket=AsyncMock(),
    )

    async def allow_origin(_origin):
        return True

    monkeypatch.setattr(
        "services.api_gateway.websocket.validate_websocket_origin", allow_origin
    )

    with caplog.at_level(logging.ERROR):
        await websocket_endpoint(websocket, "TEST1234", "admin", manager, None)

    assert "WebSocket message processing failed" in caplog.messages
    websocket.send_json.assert_awaited_once()
    manager.disconnect_websocket.assert_awaited_once_with(
        "connection-1", "client_disconnect"
    )


@pytest.mark.asyncio
async def test_fallback_notification_is_queued_when_callback_fails(caplog):
    manager = WebSocketFallbackManager()
    client = PollingClient(
        polling_id="poll-1",
        session_id="TEST1234",
        client_type="admin",
        origin=None,
        created_at=datetime.now(timezone.utc),
        fallback_reason=FallbackReason.NETWORK_ERROR,
    )

    async def failing_callback(_notification):
        raise RuntimeError("callback unavailable")

    manager.notification_callbacks.append(failing_callback)

    with caplog.at_level(logging.ERROR):
        await manager._send_fallback_notification(client)

    assert len(client.message_queue) == 1
    assert client.message_queue[0]["type"] == "fallback_notification"
    assert "Notification callback failed" in caplog.messages


@pytest.mark.asyncio
async def test_periodic_cleanup_logs_internal_failure_before_cancellation(
    monkeypatch, caplog
):
    manager = WebSocketFallbackManager()
    outcomes = iter((RuntimeError("clock unavailable"), asyncio.CancelledError()))

    async def controlled_sleep(_delay):
        outcome = next(outcomes)
        raise outcome

    monkeypatch.setattr(
        "services.api_gateway.websocket_fallback.asyncio.sleep", controlled_sleep
    )

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await manager.periodic_cleanup()

    assert "Polling cleanup task failed" in caplog.messages
