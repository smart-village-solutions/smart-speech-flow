"""Tenant-aware session lifecycle and presence timeout tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketState

from services.api_gateway.session_manager import (
    ClientType,
    SessionManager,
    SessionStatus,
)
from services.api_gateway.session_store import (
    MemoryTenantSessionStore,
    SessionStoreConsistencyError,
)
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot
from services.api_gateway.websocket import WebSocketManager
from services.api_gateway.websocket_polling_routes import TenantPollingStore

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


class Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **delta: int) -> None:
        self.current += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def manager(clock: Clock) -> SessionManager:
    identifiers = iter(["AAAA1111", "BBBB2222", "CCCC3333"])
    return SessionManager(
        store=MemoryTenantSessionStore(),
        clock=clock,
        session_id_factory=lambda: next(identifiers),
    )


@pytest.mark.asyncio
async def test_single_active_session_limit_is_per_tenant(
    manager: SessionManager,
) -> None:
    first_a = await manager.create_admin_session("tenant-a", SNAPSHOT)
    first_b = await manager.create_admin_session("tenant-b", SNAPSHOT)
    second_a = await manager.create_admin_session("tenant-a", SNAPSHOT)

    assert manager.get_session(first_a.key).status is SessionStatus.TERMINATED
    assert manager.get_session(first_b.key).status is SessionStatus.PENDING
    assert manager.get_session(second_a.key).status is SessionStatus.PENDING
    assert manager.active_admin_sessions == {
        "tenant-a": {second_a.id},
        "tenant-b": {first_b.id},
    }


@pytest.mark.asyncio
async def test_customer_resolution_uses_server_owned_join_index(
    manager: SessionManager,
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)

    assert manager.resolve_customer_session(session.id) == session.key

    await manager.terminate_session(session.key, "manual_admin_termination")

    assert manager.resolve_customer_session(session.id) is None


@pytest.mark.asyncio
async def test_connected_admin_survives_silence_until_absolute_limit(
    manager: SessionManager, clock: Clock
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    manager.admin_connected(session.key)

    clock.advance(hours=7, minutes=55)
    assert session.warning_due(clock()) is True
    assert session.timeout_due(clock()) is False

    clock.advance(minutes=5)
    assert session.timeout_due(clock()) is True


@pytest.mark.asyncio
async def test_customer_alone_does_not_cancel_admin_reconnect_grace(
    manager: SessionManager, clock: Clock
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    manager.admin_connected(session.key)
    manager.customer_connected(session.key)
    manager.admin_disconnected(session.key)

    clock.advance(minutes=25)
    assert session.warning_due(clock()) is True
    assert session.timeout_due(clock()) is False

    clock.advance(minutes=5)
    assert session.timeout_due(clock()) is True


@pytest.mark.asyncio
async def test_admin_reconnect_cancels_grace_warning(manager: SessionManager, clock: Clock) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    manager.admin_connected(session.key)
    manager.admin_disconnected(session.key)
    clock.advance(minutes=25)
    session.timeout_warning_sent = True

    manager.admin_connected(session.key)

    assert session.admin_disconnected_at is None
    assert session.timeout_warning_sent is False
    assert session.warning_due(clock()) is False


@pytest.mark.asyncio
async def test_heartbeat_does_not_change_business_or_timeout_state(
    manager: SessionManager, clock: Clock
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    before = session.last_activity
    clock.advance(minutes=10)

    await manager.heartbeat_received(session.key, ClientType.ADMIN)

    assert session.last_activity == before
    assert session.admin_disconnected_at == session.created_at


@pytest.mark.asyncio
async def test_pending_session_without_admin_connection_expires_from_creation(
    manager: SessionManager, clock: Clock
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)

    assert session.admin_disconnected_at == session.created_at
    clock.advance(minutes=30)
    assert session.timeout_due(clock()) is True


@pytest.mark.asyncio
async def test_session_status_exposes_warning_and_timeout_deadlines(
    manager: SessionManager,
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)

    payload = session.to_dict()

    assert payload["warning_at"] == (session.created_at + timedelta(minutes=25)).isoformat()
    assert payload["timeout_at"] == (session.created_at + timedelta(minutes=30)).isoformat()
    assert "tenant_id" in payload


@pytest.mark.asyncio
async def test_multiple_admin_sockets_decrement_presence_independently(
    manager: SessionManager,
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)

    await manager.add_websocket_connection(session.key, ClientType.ADMIN, object())
    await manager.add_websocket_connection(session.key, ClientType.ADMIN, object())
    await manager.remove_websocket_connection(session.key, ClientType.ADMIN)

    assert session.admin_connection_count == 1
    assert session.admin_connected is True

    await manager.remove_websocket_connection(session.key, ClientType.ADMIN)

    assert session.admin_connection_count == 0
    assert session.admin_connected is False


@pytest.mark.asyncio
async def test_termination_persists_tombstone_before_socket_presence_cleanup(
    manager: SessionManager,
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    sockets = WebSocketManager(manager)
    sockets.start_heartbeat_system = AsyncMock()
    websocket = AsyncMock()
    websocket.client_state = WebSocketState.CONNECTED
    await sockets.connect_websocket(websocket, session.key, ClientType.ADMIN)

    await manager.terminate_session(session.key)

    stored = manager.get_session(session.key)
    assert stored is not None
    assert stored.status is SessionStatus.TERMINATED
    assert stored.admin_connection_count == 0
    assert session.key not in sockets.session_connections


@pytest.mark.asyncio
async def test_failed_atomic_termination_is_consistent_and_retry_cleans_realtime(
    monkeypatch: pytest.MonkeyPatch,
    clock: Clock,
) -> None:
    from services.api_gateway.realtime_ticket import (
        MemoryRealtimeTicketBackend,
        RealtimeTicketStore,
    )

    class FailOnceStore(MemoryTenantSessionStore):
        def __init__(self) -> None:
            super().__init__()
            self.termination_attempts = 0

        def terminate(self, session) -> None:
            self.termination_attempts += 1
            if self.termination_attempts == 1:
                raise SessionStoreConsistencyError("atomic Redis mutation failed")
            super().terminate(session)

    store = FailOnceStore()
    manager = SessionManager(
        store=store,
        clock=clock,
        session_id_factory=lambda: "RETRY123",
    )
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    tickets = RealtimeTicketStore(MemoryRealtimeTicketBackend(clock=clock), clock=clock)
    usable_after_failure = tickets.issue(session.key, "websocket")
    revoked_after_success = tickets.issue(session.key, "websocket")
    polling = TenantPollingStore(clock=lambda: 0.0)
    polling_client = polling.activate(session.key, ClientType.CUSTOMER)
    monkeypatch.setattr(
        "services.api_gateway.realtime_ticket.realtime_ticket_store", tickets
    )
    monkeypatch.setattr(
        "services.api_gateway.websocket_polling_routes.polling_store", polling
    )

    sockets = WebSocketManager(manager)
    sockets.start_heartbeat_system = AsyncMock()
    websocket = AsyncMock()
    websocket.client_state = WebSocketState.CONNECTED
    await sockets.connect_websocket(websocket, session.key, ClientType.ADMIN)

    with pytest.raises(SessionStoreConsistencyError):
        await manager.terminate_session(session.key, "manual_admin_termination")

    assert session.status is SessionStatus.PENDING
    assert store.load(session.key) is session
    assert store.load(session.key).status is SessionStatus.PENDING
    assert manager.active_admin_sessions == {"tenant-a": {session.id}}
    assert polling_client.terminated is False
    assert session.key in sockets.session_connections
    assert tickets.consume(
        usable_after_failure.ticket, session.key, "websocket"
    ) is True

    await manager.terminate_session(session.key, "manual_admin_termination")

    assert store.termination_attempts == 2
    assert session.status is SessionStatus.TERMINATED
    assert manager.active_admin_sessions == {}
    assert polling_client.terminated is True
    assert session.key not in sockets.session_connections
    assert tickets.consume(
        revoked_after_success.ticket, session.key, "websocket"
    ) is False


@pytest.mark.asyncio
async def test_timeout_monitor_uses_tenant_deadlines_and_full_key(
    manager: SessionManager, clock: Clock
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    realtime = AsyncMock()
    manager.websocket_manager = realtime

    clock.advance(minutes=25)
    await manager.check_session_timeouts()

    realtime.broadcast_to_session.assert_awaited_once()
    assert realtime.broadcast_to_session.await_args.args[0] == session.key
    assert manager.get_session(session.key).status is SessionStatus.PENDING

    clock.advance(minutes=5)
    await manager.check_session_timeouts()

    assert manager.get_session(session.key).status is SessionStatus.TERMINATED


@pytest.mark.asyncio
async def test_connected_admin_is_not_terminated_at_legacy_30_minute_deadline(
    manager: SessionManager, clock: Clock
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    manager.admin_connected(session.key)
    clock.advance(minutes=30)

    await manager.check_session_timeouts()

    assert manager.get_session(session.key).status is SessionStatus.PENDING


@pytest.mark.asyncio
async def test_timeout_monitor_releases_idle_polling_presence(
    manager: SessionManager,
    monkeypatch,
) -> None:
    polling_store = TenantPollingStore(clock=lambda: 121.0)
    monkeypatch.setattr(
        "services.api_gateway.websocket_polling_routes.polling_store", polling_store
    )
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    client = polling_store.activate(session.key, ClientType.ADMIN)
    manager.admin_connected(session.key)
    client.last_seen = 0

    await manager.check_session_timeouts()

    assert client.polling_id not in polling_store.clients
    assert manager.get_session(session.key).admin_connection_count == 0
