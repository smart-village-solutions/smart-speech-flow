"""Each client frame type reaches its own handler, and nothing else does (#230).

Pinned before the if/elif ladder became a dispatch table, so the change shows
no difference here.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.api_gateway.realtime_protocol import MessageType
from services.api_gateway.session_models import SessionStatus
from services.api_gateway.websocket import ConnectionState, WebSocketManager
from tests.realtime_sessions import tenant_session_manager, websocket_monitor

CONNECTION_ID = "connection-1"


@pytest.fixture
def manager(monkeypatch) -> WebSocketManager:
    manager = WebSocketManager(tenant_session_manager(), monitor=websocket_monitor())
    connection = SimpleNamespace(state=ConnectionState.CONNECTED, key="session-key")
    monkeypatch.setattr(manager.registry, "get", lambda _id: connection)
    monkeypatch.setattr(
        manager.session_manager,
        "get_session",
        lambda _key: SimpleNamespace(status=SessionStatus.ACTIVE),
    )
    monkeypatch.setattr(manager.heartbeat, "handle_pong", AsyncMock())
    monkeypatch.setattr(manager, "_handle_client_message", AsyncMock())
    monkeypatch.setattr(manager, "_handle_typing_indicator", AsyncMock())
    for name in (
        "handle_tab_visibility_change",
        "handle_battery_status_update",
        "handle_network_status_change",
    ):
        monkeypatch.setattr(manager.client_status, name, AsyncMock())
    manager.connection = connection
    return manager


def _handlers(manager: WebSocketManager) -> dict[str, AsyncMock]:
    return {
        "pong": manager.heartbeat.handle_pong,
        "message": manager._handle_client_message,
        "typing": manager._handle_typing_indicator,
        "tab": manager.client_status.handle_tab_visibility_change,
        "battery": manager.client_status.handle_battery_status_update,
        "network": manager.client_status.handle_network_status_change,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("frame_type", "handler", "with_connection_id"),
    [
        (MessageType.HEARTBEAT_PONG, "pong", True),
        (MessageType.MESSAGE, "message", False),
        (MessageType.TYPING_INDICATOR, "typing", False),
        (MessageType.TAB_VISIBILITY_CHANGE, "tab", False),
        (MessageType.BATTERY_STATUS_UPDATE, "battery", False),
        (MessageType.NETWORK_STATUS_CHANGE, "network", False),
    ],
)
async def test_each_frame_type_reaches_only_its_handler(
    manager, frame_type, handler, with_connection_id
):
    frame = {"type": frame_type.value}

    await manager.handle_websocket_message(CONNECTION_ID, frame)

    handlers = _handlers(manager)
    expected = (
        (CONNECTION_ID, manager.connection, frame)
        if with_connection_id
        else (manager.connection, frame)
    )
    handlers[handler].assert_awaited_once_with(*expected)
    assert [name for name, mock in handlers.items() if mock.await_count] == [handler]


@pytest.mark.asyncio
@pytest.mark.parametrize("frame_type", ["no_such_type", None, ["a", "list"], {"a": 1}])
async def test_an_unknown_or_malformed_type_is_logged_and_reaches_no_handler(
    manager, caplog, frame_type
):
    with caplog.at_level(logging.WARNING):
        await manager.handle_websocket_message(CONNECTION_ID, {"type": frame_type})

    assert any("Unbekannter Message-Type" in record.getMessage() for record in caplog.records)
    assert not any(mock.await_count for mock in _handlers(manager).values())
