"""Tenant isolation for realtime WebSocket registries."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from services.api_gateway.app import app
from services.api_gateway.auth import optional_ssf_user
from services.api_gateway.routes.admin import list_tenant_realtime_connections
from services.api_gateway.session_manager import (
    ClientType,
    SessionManager,
    SessionStatus,
)
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_context import StudioTenantContext
from services.api_gateway.tenant_session import (
    RuntimeConfigurationSnapshot,
    TenantSessionKey,
)
from services.api_gateway.websocket import (
    ConnectionState,
    WebSocketConnection,
    WebSocketManager,
    _safe_identifier,
)
from services.api_gateway.websocket_monitor import WebSocketMonitor
from services.api_gateway.websocket_polling_routes import (
    POLLING_QUEUE_SIZE,
    TenantPollingStore,
)

REVISION = f"sha256:{'a' * 64}"
ALLOWED_ORIGIN = "https://translate.smart-village.solutions"


class _PresenceManager:
    def register_websocket_manager(self, manager: WebSocketManager) -> None:
        self.websocket_manager = manager

    async def add_websocket_connection(self, *args) -> None:
        return None

    async def remove_websocket_connection(self, *args) -> None:
        return None

    def get_session(self, key):
        return SimpleNamespace(
            status=SessionStatus.ACTIVE,
            customer_language=None,
        )


SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


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


@pytest.fixture
def customer_websocket_client():
    from services.api_gateway import websocket as websocket_module
    from services.api_gateway.session_manager import session_manager

    original_overrides = app.dependency_overrides.copy()
    original_websocket_manager = websocket_module.websocket_manager
    session_manager.reset(clear_persistence=True)
    websocket_module.websocket_manager = None
    client = TestClient(app)
    try:
        created = client.post("/api/admin/session/create")
        assert created.status_code == 201
        yield client, created.json()["session_id"]
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        websocket_module.websocket_manager = original_websocket_manager
        session_manager.reset(clear_persistence=True)
        if original_websocket_manager is not None:
            session_manager.register_websocket_manager(original_websocket_manager)


def test_customer_websocket_rejects_a_cross_tenant_supplied_bearer_before_accept(
    customer_websocket_client,
) -> None:
    client, session_id = customer_websocket_client
    app.dependency_overrides[optional_ssf_user] = lambda: {
        "studio_tenant_id": "another-tenant",
        "ssf_authorization_revision": REVISION,
    }

    with pytest.raises(WebSocketDenialResponse) as denied:
        with client.websocket_connect(
            f"/ws/customer/{session_id}",
            headers={
                "Authorization": "Bearer valid-for-another-tenant",
                "Origin": ALLOWED_ORIGIN,
            },
        ):
            pass

    assert denied.value.status_code == 404
    assert denied.value.json() == {"detail": "Session not found"}


def test_customer_websocket_rejects_a_malformed_supplied_bearer_before_accept(
    customer_websocket_client,
) -> None:
    client, session_id = customer_websocket_client

    with pytest.raises(WebSocketDenialResponse) as denied:
        with client.websocket_connect(
            f"/ws/customer/{session_id}",
            headers={
                "Authorization": "Bearer malformed",
                "Origin": ALLOWED_ORIGIN,
            },
        ):
            pass

    assert denied.value.status_code == 401
    assert denied.value.json() == {"detail": "A valid bearer token is required"}


def test_customer_websocket_still_accepts_an_anonymous_capability(
    customer_websocket_client,
) -> None:
    client, session_id = customer_websocket_client

    with client.websocket_connect(
        f"/ws/customer/{session_id}", headers={"Origin": ALLOWED_ORIGIN}
    ) as websocket:
        acknowledgement = websocket.receive_json()

    assert acknowledgement["type"] == "connection_ack"
    assert acknowledgement["session_id"] == session_id
    assert acknowledgement["client_type"] == "customer"


def test_legacy_client_selected_websocket_route_is_absent() -> None:
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/ABC12345/admin"):
            pass


def test_production_uvicorn_access_log_is_disabled_for_capability_urls() -> None:
    dockerfile = (
        Path(__file__).resolve().parents[1] / "services/api_gateway/Dockerfile"
    ).read_text(encoding="utf-8")
    command = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))

    assert '"--no-access-log"' in command


@pytest.mark.asyncio
async def test_connection_is_not_registered_if_session_terminates_during_accept() -> None:
    manager = SessionManager(store=MemoryTenantSessionStore())
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    sockets = WebSocketManager(manager)
    sockets.start_heartbeat_system = AsyncMock()
    accept_started = asyncio.Event()
    accept_release = asyncio.Event()
    websocket = AsyncMock()

    async def blocked_accept() -> None:
        accept_started.set()
        await accept_release.wait()

    websocket.accept.side_effect = blocked_accept
    connecting = asyncio.create_task(
        sockets.connect_websocket(websocket, session.key, ClientType.ADMIN)
    )
    await accept_started.wait()
    await manager.terminate_session(session.key)
    accept_release.set()

    with pytest.raises(RuntimeError, match="Session unavailable"):
        await connecting
    assert session.key not in sockets.session_connections
    assert manager.get_session(session.key).admin_connection_count == 0


@pytest.mark.asyncio
async def test_inbound_message_is_not_dispatched_after_termination_starts() -> None:
    manager = SessionManager(store=MemoryTenantSessionStore())
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    sockets = WebSocketManager(manager)
    sockets.start_heartbeat_system = AsyncMock()
    sender = AsyncMock()
    receiver = AsyncMock()
    sender_id = await sockets.connect_websocket(sender, session.key, ClientType.ADMIN)
    await sockets.connect_websocket(receiver, session.key, ClientType.CUSTOMER)
    termination_started = asyncio.Event()
    termination_release = asyncio.Event()

    async def block_termination(payload) -> None:
        if payload.get("type") == "session_terminated":
            termination_started.set()
            await termination_release.wait()

    sender.send_json.side_effect = block_termination
    receiver.send_json.side_effect = block_termination
    terminating = asyncio.create_task(manager.terminate_session(session.key))
    await termination_started.wait()

    await sockets.handle_websocket_message(
        sender_id,
        {"type": "message", "content": {"text": "must-not-arrive"}},
    )
    assert not any(
        call.args[0].get("type") == "message" for call in receiver.send_json.await_args_list
    )

    termination_release.set()
    await terminating


@pytest.mark.asyncio
async def test_polling_overflow_reports_current_delivery_and_historical_eviction(
    monkeypatch,
) -> None:
    key = TenantSessionKey("tenant-a", "SESSION1")
    store = TenantPollingStore()
    receiver = store.activate(key, ClientType.CUSTOMER)
    for index in range(POLLING_QUEUE_SIZE):
        receiver.messages.append({"type": "old", "index": index})
    monkeypatch.setattr(
        "services.api_gateway.websocket_polling_routes.polling_store", store
    )
    sockets = WebSocketManager(_PresenceManager())

    result = await sockets.broadcast_with_differentiated_content(
        key,
        ClientType.ADMIN,
        {"type": "message", "content": {"text": "original"}},
        {"type": "message", "content": {"text": "newest"}},
    )

    assert receiver.messages[-1]["content"] == {"text": "newest"}
    assert result.success is True
    assert result.successful_sends == 1
    assert result.failed_sends == 0
    assert result.messages_dropped == 1
    samples = [
        sample
        for metric in store.messages_dropped.collect()
        for sample in metric.samples
        if sample.name == "tenant_polling_messages_dropped_total"
    ]
    assert samples[0].value == 1


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


@pytest.mark.asyncio
async def test_legacy_fallback_log_never_contains_the_public_session_id(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A fallback success log must retain only the pseudonymous session reference."""
    import services.api_gateway.websocket as websocket_module

    session_id = "SECRET42"
    socket_manager = WebSocketManager(_PresenceManager())
    connection = WebSocketConnection(
        websocket=AsyncMock(),
        client_type=ClientType.ADMIN,
        session_id=session_id,
        connected_at=datetime.now(timezone.utc),
        last_heartbeat=datetime.now(timezone.utc),
        state=ConnectionState.CONNECTED,
    )
    monkeypatch.setattr(
        websocket_module.fallback_manager,
        "evaluate_websocket_failure",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        websocket_module.fallback_manager,
        "activate_polling_fallback",
        AsyncMock(return_value="safe-polling-id"),
    )
    monkeypatch.setattr(
        socket_manager,
        "_send_fallback_activation_message",
        AsyncMock(),
    )

    with caplog.at_level("INFO", logger="services.api_gateway.websocket"):
        await socket_manager._evaluate_connection_error(
            connection,
            RuntimeError("network unavailable"),
            "receive_error",
        )

    assert session_id not in caplog.text
    assert _safe_identifier(session_id) in caplog.text
