"""Tenant-aware session lifecycle and presence timeout tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.session_manager import ClientType, SessionManager, SessionStatus
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

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
