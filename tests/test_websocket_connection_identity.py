"""Two sockets on one session must never share a connection id.

The monitor keys its active-connection map by this id, so a collision makes one
socket's metrics describe the other's — and the connection KPIs (R1-R4) divide
by those counts. The polling fallback has the same defect with worse
consequences: its id keys a dict of message queues, so a collision discards a
whole queue.
"""

import time
from unittest.mock import AsyncMock, Mock

from services.api_gateway.realtime_connection import safe_identifier
from services.api_gateway.realtime_registry import ConnectionRegistry
from services.api_gateway.session_manager import ClientType
from services.api_gateway.tenant_session import TenantSessionKey
from services.api_gateway.websocket import WebSocketManager
from services.api_gateway.websocket_fallback import (
    FallbackConfig,
    FallbackReason,
    WebSocketFallbackManager,
)
from tests.realtime_sessions import TENANT, open_session, tenant_session_manager, websocket_monitor

SESSION_A = TenantSessionKey(TENANT, "session-a")


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
        ConnectionRegistry.build_connection_id(SESSION_A, ClientType.CUSTOMER)
        for _ in range(100)
    }

    assert len(ids) == 100, f"only {len(ids)} distinct ids from 100 connections"


def test_the_id_still_names_its_session_and_client_type():
    """Kept readable on purpose: these ids appear in operator log lines.

    The session id itself is a join credential, so only its hash is in the id.
    """
    connection_id = ConnectionRegistry.build_connection_id(SESSION_A, ClientType.CUSTOMER)

    scope = f"{SESSION_A.tenant_ref}_{safe_identifier(SESSION_A.session_id)}"
    assert connection_id.startswith(f"{scope}_{ClientType.CUSTOMER.value}_")
    assert SESSION_A.session_id not in connection_id


class TestTheEndpointItselfBuildsUniqueIds:
    """build_connection_id in isolation is not the seam that broke.

    connect_websocket used to inline the id construction; a revert that puts
    the timestamp back there passes every test that only calls the helper.
    """

    async def test_two_connections_for_one_session_get_different_ids(self):
        sessions = tenant_session_manager()
        key = open_session(sessions, "session-a")
        manager = WebSocketManager(sessions, monitor=websocket_monitor())

        first = await manager.connect_websocket(_websocket(), key, ClientType.CUSTOMER)
        second = await manager.connect_websocket(_websocket(), key, ClientType.CUSTOMER)

        try:
            assert first != second
            assert len(manager.all_connections) == 2
            assert len(manager.session_connections[key]) == 2
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
