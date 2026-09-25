"""Behavioral coverage for Sonar remediation paths in WebSocket services."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.api_gateway.session_manager import ClientType, SessionStatus
from services.api_gateway.tenant_session import TenantSessionKey
from services.api_gateway.websocket import (
    WebSocketManager,
    websocket_endpoint,
)
from tests.realtime_sessions import TENANT, tenant_session_manager, websocket_monitor


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
    manager = WebSocketManager(tenant_session_manager(), monitor=websocket_monitor())

    with caplog.at_level(logging.WARNING):
        result = await manager.broadcast_with_differentiated_content(
            TenantSessionKey(TENANT, "SENSITIVE123"),
            ClientType.ADMIN,
            {"type": "original"},
            {"type": "translated"},
        )

    assert result.session_has_connections is False
    assert "Broadcast attempted without active connections" in caplog.messages
    assert "SENSITIVE123" not in caplog.text


@pytest.mark.asyncio
async def test_heartbeat_monitor_logs_unexpected_failure(monkeypatch, caplog):
    manager = WebSocketManager(tenant_session_manager(), monitor=websocket_monitor())

    async def fail_sleep(_delay):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr("services.api_gateway.realtime_heartbeat.asyncio.sleep", fail_sleep)

    with caplog.at_level(logging.ERROR):
        await manager.heartbeat.monitor_loop()

    assert "Heartbeat monitor failed" in caplog.messages


@pytest.mark.asyncio
async def test_endpoint_returns_error_message_after_message_handler_failure(
    monkeypatch, caplog
):
    websocket = SimpleNamespace(
        receive_json=AsyncMock(side_effect=RuntimeError("bad message")),
        send_json=AsyncMock(side_effect=RuntimeError("client disconnected")),
        close=AsyncMock(),
    )
    sessions = SimpleNamespace(
        get_session=Mock(return_value=SimpleNamespace(status=SessionStatus.ACTIVE))
    )
    manager = SimpleNamespace(
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
        await websocket_endpoint(
            websocket, TenantSessionKey(TENANT, "TEST1234"), ClientType.ADMIN, manager, sessions
        )

    assert "WebSocket message processing failed" in caplog.messages
    websocket.send_json.assert_awaited_once()
    # Not "client_disconnect": the loop was left because the socket could no
    # longer be written to, which is an abnormal termination.
    manager.disconnect_websocket.assert_awaited_once_with(
        "connection-1", "connection_error"
    )
