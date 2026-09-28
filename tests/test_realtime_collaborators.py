"""The collaborators WebSocketManager composes, each on its own (#228 task 3.2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

from services.api_gateway.realtime_connection import WebSocketConnection
from services.api_gateway.realtime_dispatch import BroadcastDispatcher
from services.api_gateway.realtime_heartbeat import Heartbeat
from services.api_gateway.realtime_protocol import ConnectionState
from services.api_gateway.realtime_registry import ConnectionRegistry
from services.api_gateway.session_manager import ClientType
from services.api_gateway.tenant_session import TenantSessionKey
from services.api_gateway.websocket import WebSocketManager
from services.api_gateway.websocket_monitor import DisconnectReason
from services.api_gateway.websocket_polling_routes import TenantPollingStore
from tests.realtime_sessions import tenant_session_manager, websocket_monitor

KEY_A = TenantSessionKey("tenant-a", "DUPL1234")
KEY_B = TenantSessionKey("tenant-b", "DUPL1234")


def _connection(key: TenantSessionKey, client_type: ClientType = ClientType.ADMIN):
    now = datetime.now(timezone.utc)
    socket = Mock()
    socket.send_json = AsyncMock()
    return WebSocketConnection(
        websocket=socket,
        client_type=client_type,
        session_id=key.session_id,
        connected_at=now,
        last_heartbeat=now,
        key=key,
        state=ConnectionState.CONNECTED,
    )


def _registered(registry: ConnectionRegistry, key: TenantSessionKey, client_type=ClientType.ADMIN):
    connection = _connection(key, client_type)
    connection_id = registry.build_connection_id(key, client_type)
    registry.add(connection_id, connection)
    return connection_id, connection


class TestConnectionRegistry:
    def test_two_tenants_sessions_with_one_id_keep_separate_pools(self):
        registry = ConnectionRegistry()
        id_a, _ = _registered(registry, KEY_A)
        id_b, _ = _registered(registry, KEY_B)

        assert set(registry.session(KEY_A) or {}) == {id_a}
        assert set(registry.session(KEY_B) or {}) == {id_b}

    def test_removing_the_last_socket_drops_the_pool_and_only_that_one(self):
        registry = ConnectionRegistry()
        id_a, connection = _registered(registry, KEY_A)
        _registered(registry, KEY_B)

        assert registry.remove(id_a) is connection
        assert registry.session(KEY_A) is None
        assert registry.session(KEY_B) is not None
        assert registry.get(id_a) is None
        assert registry.remove(id_a) is None

    def test_a_popped_session_stays_tracked_until_released(self):
        registry = ConnectionRegistry()
        connection_id, connection = _registered(registry, KEY_A)

        assert registry.pop_session(KEY_A) == [connection]
        assert registry.session(KEY_A) is None
        assert registry.registered_connection_id(connection) is None
        assert registry.tracked_connection_id(connection) == connection_id
        assert registry.pop_session(KEY_A) == []


class TestBroadcastDispatcher:
    async def test_a_broadcast_reaches_the_sessions_pollers_and_sockets(self):
        registry = ConnectionRegistry()
        _, connection = _registered(registry, KEY_A)
        pollers = TenantPollingStore()
        poller = pollers.activate(KEY_A, ClientType.CUSTOMER)
        foreign = pollers.activate(KEY_B, ClientType.CUSTOMER)
        dispatcher = BroadcastDispatcher(registry, pollers, websocket_monitor())

        await dispatcher.broadcast_to_session(KEY_A, {"type": "message"})

        connection.websocket.send_json.assert_awaited_once_with({"type": "message"})
        assert list(poller.messages) == [{"type": "message"}]
        assert not foreign.messages

    async def test_a_polled_send_is_not_queued_back_to_the_pollers(self):
        registry = ConnectionRegistry()
        pollers = TenantPollingStore()
        poller = pollers.activate(KEY_A, ClientType.CUSTOMER)
        dispatcher = BroadcastDispatcher(registry, pollers, websocket_monitor())

        await dispatcher.broadcast_to_session(KEY_A, {"type": "message"}, include_polling=False)

        assert not poller.messages

    async def test_a_differentiated_broadcast_counts_pollers_as_deliveries(self):
        registry = ConnectionRegistry()
        pollers = TenantPollingStore()
        admin = pollers.activate(KEY_A, ClientType.ADMIN)
        customer = pollers.activate(KEY_A, ClientType.CUSTOMER)
        dispatcher = BroadcastDispatcher(registry, pollers, websocket_monitor())

        result = await dispatcher.broadcast_with_differentiated_content(
            KEY_A, ClientType.ADMIN, {"role": "sender"}, {"role": "receiver"}
        )

        assert (result.success, result.successful_sends, result.total_connections) == (
            True,
            2,
            2,
        )
        assert list(admin.messages) == [{"role": "sender"}]
        assert list(customer.messages) == [{"role": "receiver"}]


class _Closer:
    def __init__(self) -> None:
        self.disconnected: list[tuple[str, str, int]] = []
        self.released: list[tuple[str, DisconnectReason]] = []

    async def disconnect_websocket(
        self, connection_id: str, reason: str = "client_disconnect", code: int = 1000
    ) -> None:
        self.disconnected.append((connection_id, reason, code))

    async def release_connection(self, connection_id: str, reason: DisconnectReason) -> None:
        self.released.append((connection_id, reason))


class TestHeartbeat:
    async def test_a_silent_socket_is_disconnected_as_a_heartbeat_timeout(self):
        registry = ConnectionRegistry()
        silent_id, silent = _registered(registry, KEY_A)
        _registered(registry, KEY_B)
        silent.last_heartbeat -= timedelta(seconds=61)
        closer = _Closer()
        heartbeat = Heartbeat(registry, websocket_monitor(), closer)

        await heartbeat.check_timeouts()

        assert closer.disconnected == [(silent_id, "heartbeat_timeout", 1001)]
        assert registry.connection_stats["heartbeat_timeouts"] == 1

    async def test_a_socket_the_ping_cannot_reach_is_released_as_a_connection_error(self):
        registry = ConnectionRegistry()
        connection_id, connection = _registered(registry, KEY_A)
        connection.websocket.send_json = AsyncMock(side_effect=RuntimeError("gone"))
        closer = _Closer()
        heartbeat = Heartbeat(registry, websocket_monitor(), closer)

        await heartbeat.send_pings()

        assert closer.released == [(connection_id, DisconnectReason.CONNECTION_ERROR)]


def test_the_manager_composes_one_set_of_collaborators():
    pollers = TenantPollingStore()
    monitor = websocket_monitor()
    manager = WebSocketManager(tenant_session_manager(), pollers, monitor=monitor)

    assert manager.dispatcher.registry is manager.registry
    assert manager.dispatcher.polling_store is pollers
    assert manager.dispatcher.monitor is monitor
    assert manager.heartbeat.registry is manager.registry
    assert manager.heartbeat.closer is manager
    assert manager.session_connections is manager.registry.session_connections
    assert manager.all_connections is manager.registry.all_connections
    manager.heartbeat_interval = 0.5
    assert manager.heartbeat.interval == 0.5
