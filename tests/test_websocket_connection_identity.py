"""Two sockets on one session must never share a connection id.

The monitor keys its active-connection map by this id, so a collision makes one
socket's metrics describe the other's — and the connection KPIs (R1-R4) divide
by those counts. The polling fallback has the same defect with worse
consequences: its id keys a dict of message queues, so a collision discards a
whole queue.
"""

import time
from unittest.mock import AsyncMock, Mock

from services.api_gateway.session_manager import SessionManager
from services.api_gateway.websocket import ClientType, WebSocketManager
from services.api_gateway.websocket_fallback import (
    FallbackConfig,
    FallbackReason,
    WebSocketFallbackManager,
)


def _websocket() -> Mock:
    socket = Mock()
    socket.accept = AsyncMock()
    socket.send_json = AsyncMock()
    socket.close = AsyncMock()
    return socket


def test_ids_are_unique_within_the_same_second(monkeypatch):
    """The old format was f"{session}_{type}_{int(time.time())}"."""
    monkeypatch.setattr(time, "time", lambda: 1_757_000_000.0)

    ids = {
        WebSocketManager._build_connection_id("session-a", ClientType.CUSTOMER)
        for _ in range(100)
    }

    assert len(ids) == 100, f"only {len(ids)} distinct ids from 100 connections"


def test_the_id_still_names_its_session_and_client_type():
    """Kept readable on purpose: these ids appear in operator log lines."""
    connection_id = WebSocketManager._build_connection_id(
        "session-a", ClientType.CUSTOMER
    )

    assert connection_id.startswith(f"session-a_{ClientType.CUSTOMER.value}_")


class TestTheEndpointItselfBuildsUniqueIds:
    """_build_connection_id in isolation is not the seam that broke.

    connect_websocket used to inline the id construction; a revert that puts
    the timestamp back there passes every test that only calls the helper.
    """

    async def test_two_connections_for_one_session_get_different_ids(self):
        manager = WebSocketManager(SessionManager())

        first = await manager.connect_websocket(
            _websocket(), "session-a", ClientType.CUSTOMER
        )
        second = await manager.connect_websocket(
            _websocket(), "session-a", ClientType.CUSTOMER
        )

        try:
            assert first != second
            assert len(manager.all_connections) == 2
            assert len(manager.session_connections["session-a"]) == 2
        finally:
            await manager.stop_heartbeat_system()


class TestThePollingFallbackKeepsBothQueues:
    """A polling id keys a message queue; a collision loses one of them whole.

    _evaluate_connection_error runs per connection inside the broadcast loop,
    so one failed broadcast to a session with two same-type connections
    activated the fallback twice in the same instant.
    """

    async def test_two_activations_in_one_instant_do_not_overwrite_each_other(self):
        manager = WebSocketFallbackManager(
            FallbackConfig(enable_jitter=False, enable_user_notifications=False)
        )

        first = await manager.activate_polling_fallback(
            "session-a", "customer", None, FallbackReason.NETWORK_ERROR
        )
        second = await manager.activate_polling_fallback(
            "session-a", "customer", None, FallbackReason.NETWORK_ERROR
        )

        assert first != second
        assert len(manager.polling_clients) == 2

        manager.send_message_to_polling_client(first, {"type": "translation"})

        assert len(manager.polling_clients[first].message_queue) == 1
        assert len(manager.polling_clients[second].message_queue) == 0

    async def test_the_manager_level_fallback_id_is_unique_too(self):
        manager = WebSocketManager(SessionManager())

        first = await manager.enable_polling_fallback("session-a", ClientType.CUSTOMER)
        second = await manager.enable_polling_fallback("session-a", ClientType.CUSTOMER)

        assert first != second
        assert len(manager.polling_clients) == 2
