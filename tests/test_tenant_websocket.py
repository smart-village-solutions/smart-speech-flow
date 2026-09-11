"""Tenant isolation for realtime WebSocket registries."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from starlette.websockets import WebSocketDisconnect

from services.api_gateway.app import app
from services.api_gateway.routes.admin import list_tenant_realtime_connections
from services.api_gateway.session_manager import ClientType
from services.api_gateway.tenant_context import StudioTenantContext
from services.api_gateway.tenant_session import TenantSessionKey
from services.api_gateway.websocket import WebSocketManager
from services.api_gateway.websocket_monitor import WebSocketMonitor

REVISION = f"sha256:{'a' * 64}"


class _PresenceManager:
    def register_websocket_manager(self, manager: WebSocketManager) -> None:
        self.websocket_manager = manager

    async def add_websocket_connection(self, *args) -> None:
        return None

    async def remove_websocket_connection(self, *args) -> None:
        return None

    def get_session(self, key):
        return None


@pytest.mark.asyncio
async def test_same_public_id_in_two_tenants_never_cross_broadcast() -> None:
    session_manager = _PresenceManager()
    socket_manager = WebSocketManager(session_manager)
    socket_manager.start_heartbeat_system = AsyncMock()
    socket_a = AsyncMock()
    socket_b = AsyncMock()
    key_a = TenantSessionKey("tenant-a", "DUPL1234")
    key_b = TenantSessionKey("tenant-b", "DUPL1234")

    await socket_manager.connect_websocket(socket_a, key_a, ClientType.ADMIN)
    await socket_manager.connect_websocket(socket_b, key_b, ClientType.ADMIN)
    socket_a.send_json.reset_mock()
    socket_b.send_json.reset_mock()

    await socket_manager.broadcast_to_session(key_a, {"type": "message"})

    socket_a.send_json.assert_awaited_once()
    socket_b.send_json.assert_not_awaited()
    assert set(socket_manager.session_connections) == {key_a, key_b}


def test_admin_websocket_rejects_invalid_ticket_before_accept() -> None:
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/admin/ABC12345?ticket=expired"):
            pass

    assert closed.value.code == 4404


def test_legacy_client_selected_websocket_route_is_absent() -> None:
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/ABC12345/admin"):
            pass


@pytest.mark.asyncio
async def test_termination_cleans_only_the_addressed_tenant() -> None:
    session_manager = _PresenceManager()
    socket_manager = WebSocketManager(session_manager)
    socket_manager.start_heartbeat_system = AsyncMock()
    socket_a = AsyncMock()
    socket_b = AsyncMock()
    key_a = TenantSessionKey("tenant-a", "DUPL1234")
    key_b = TenantSessionKey("tenant-b", "DUPL1234")
    await socket_manager.connect_websocket(socket_a, key_a, ClientType.ADMIN)
    await socket_manager.connect_websocket(socket_b, key_b, ClientType.ADMIN)

    await socket_manager.handle_session_termination(key_a)

    assert key_a not in socket_manager.session_connections
    assert key_b in socket_manager.session_connections


@pytest.mark.asyncio
async def test_admin_connection_listing_is_filtered_by_token_tenant() -> None:
    session_manager = _PresenceManager()
    socket_manager = WebSocketManager(session_manager)
    socket_manager.start_heartbeat_system = AsyncMock()
    await socket_manager.connect_websocket(
        AsyncMock(), TenantSessionKey("tenant-a", "DUPL1234"), ClientType.ADMIN
    )
    await socket_manager.connect_websocket(
        AsyncMock(), TenantSessionKey("tenant-b", "DUPL1234"), ClientType.ADMIN
    )

    response = await list_tenant_realtime_connections(
        StudioTenantContext("tenant-a", REVISION), socket_manager
    )

    assert response["count"] == 1
    assert response["connections"][0]["session_id"] == "DUPL1234"


def test_monitor_keeps_duplicate_public_ids_in_separate_tenant_buckets() -> None:
    monitor = WebSocketMonitor(registry=CollectorRegistry())
    key_a = TenantSessionKey("tenant-a", "DUPL1234")
    key_b = TenantSessionKey("tenant-b", "DUPL1234")

    monitor.connection_established("connection-a", "safe-ref", "admin", resource_key=key_a)
    monitor.connection_established("connection-b", "safe-ref", "admin", resource_key=key_b)

    assert monitor.get_connection_stats()["sessions_with_connections"] == 2
    assert len(monitor.get_session_connections(key_a)) == 1
    assert len(monitor.get_session_connections(key_b)) == 1
