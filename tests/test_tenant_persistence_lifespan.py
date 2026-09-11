"""Production lifespan wiring for the tenant-scoped Redis stores."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketState

from services.api_gateway.app import app, lifespan
from services.api_gateway.realtime_ticket import realtime_ticket_store
from services.api_gateway.session_manager import (
    ClientType,
    SessionStatus,
    session_manager,
)
from services.api_gateway.session_store import (
    RedisTenantSessionStore,
    join_key,
    session_key as persisted_session_key,
)
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot
from services.api_gateway.websocket import get_websocket_manager
from services.api_gateway.websocket_polling_routes import TenantPollingStore

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


class PersistentFakeRedis:
    """Small Redis contract shared by two real application lifespans."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.pings = 0
        self.fail_after_next_termination = False

    def ping(self) -> bool:
        self.pings += 1
        return True

    def close(self) -> None:
        return None

    def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def scan_iter(self, *, match):
        return iter(key for key in self.sets if fnmatch(key, match))

    def eval(self, script, number_of_keys, *values):
        if number_of_keys == 1:
            key = values[0]
            return self.values.pop(key, None)

        keys = values[:number_of_keys]
        argv = values[number_of_keys:]
        if number_of_keys == 4:
            session_key, tenant_index, join_key, active_index = keys
            session_payload, session_id, join_payload = argv
            if join_key in self.values:
                return 0
            self.values[session_key] = session_payload
            self.sets.setdefault(tenant_index, set()).add(session_id)
            self.values[join_key] = join_payload
            self.sets.setdefault(active_index, set()).add(session_id)
            return 1

        session_key_value, active_index, join_key_value = keys
        session_payload, session_id, expected_join, terminal_join, tenant_id = argv
        current_join = self.values.get(join_key_value)
        if current_join == terminal_join:
            persisted = json.loads(self.values[session_key_value])
            if (
                persisted["id"] == session_id
                and persisted["tenant_id"] == tenant_id
                and persisted["status"] == "terminated"
                and session_id not in self.sets.setdefault(active_index, set())
            ):
                return 2
            return 0
        if current_join != expected_join:
            return 0
        self.values[session_key_value] = session_payload
        self.sets.setdefault(active_index, set()).discard(session_id)
        self.values[join_key_value] = terminal_join
        if self.fail_after_next_termination:
            self.fail_after_next_termination = False
            raise ConnectionError("reply lost after Redis committed")
        return 1


@pytest.fixture(autouse=True)
def _clean_global_memory_state():
    session_manager.reset(clear_persistence=True)
    original_ticket_backend = realtime_ticket_store.redis
    if hasattr(original_ticket_backend, "values"):
        original_ticket_backend.values.clear()
    sockets = get_websocket_manager()
    session_manager.register_websocket_manager(sockets)
    sockets.session_connections.clear()
    sockets.all_connections.clear()
    yield
    session_manager.reset(clear_persistence=True)
    session_manager.register_websocket_manager(sockets)
    sockets.session_connections.clear()
    sockets.all_connections.clear()
    if hasattr(original_ticket_backend, "values"):
        original_ticket_backend.values.clear()


@pytest.mark.asyncio
async def test_production_startup_uses_shared_redis_and_survives_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.api_gateway.tenant_persistence as persistence

    redis = PersistentFakeRedis()
    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(
        persistence.Redis,
        "from_url",
        lambda *_args, **_kwargs: redis,
    )

    async with lifespan(app):
        assert isinstance(session_manager.store, RedisTenantSessionStore)
        assert session_manager.store.redis is redis
        assert realtime_ticket_store.redis is redis
        assert session_manager.websocket_manager is get_websocket_manager()
        session = await session_manager.create_admin_session("tenant-a", SNAPSHOT)
        issued = realtime_ticket_store.issue(session.key, "websocket")

    async with lifespan(app):
        assert session_manager.websocket_manager is get_websocket_manager()
        restored = session_manager.get_session(session.key)
        assert restored is not None
        assert restored is not session
        assert json.loads(restored.runtime_configuration.canonical_json) == {}
        assert (
            realtime_ticket_store.consume(issued.ticket, session.key, "websocket")
            is True
        )
        assert (
            realtime_ticket_store.consume(issued.ticket, session.key, "websocket")
            is False
        )

    assert redis.pings == 2


@pytest.mark.asyncio
async def test_production_startup_fails_closed_without_redis_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.api_gateway.tenant_persistence import TenantPersistenceUnavailable

    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")

    with pytest.raises(TenantPersistenceUnavailable):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_configured_redis_connection_failure_aborts_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.api_gateway.tenant_persistence as persistence

    class BrokenRedis:
        def ping(self):
            raise ConnectionError("private redis endpoint")

    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(
        persistence.Redis,
        "from_url",
        lambda *_args, **_kwargs: BrokenRedis(),
    )

    with pytest.raises(persistence.TenantPersistenceUnavailable):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_ambiguous_termination_commit_is_reconciled_before_cleanup_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.api_gateway.tenant_persistence as persistence

    redis = PersistentFakeRedis()
    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(persistence.Redis, "from_url", lambda *_args, **_kwargs: redis)
    polling = TenantPollingStore(clock=lambda: 0.0)
    monkeypatch.setattr(
        "services.api_gateway.websocket_polling_routes.polling_store", polling
    )
    sockets = get_websocket_manager()
    monkeypatch.setattr(sockets, "start_heartbeat_system", AsyncMock())

    async with lifespan(app):
        session = await session_manager.create_admin_session("tenant-a", SNAPSHOT)
        usable_after_failure = realtime_ticket_store.issue(session.key, "websocket")
        revoked_after_retry = realtime_ticket_store.issue(session.key, "websocket")
        polling_client = polling.activate(session.key, ClientType.CUSTOMER)
        websocket = AsyncMock()
        websocket.client_state = WebSocketState.CONNECTED
        await sockets.connect_websocket(websocket, session.key, ClientType.ADMIN)
        redis.fail_after_next_termination = True

        with pytest.raises(ConnectionError, match="reply lost"):
            await session_manager.terminate_session(session.key)

        assert session.status is SessionStatus.PENDING
        assert json.loads(redis.get(join_key("ssf", session.id)))["active"] is False
        committed = json.loads(
            redis.get(persisted_session_key("ssf", session.key))
        )
        assert committed["status"] == "terminated"
        assert polling_client.terminated is False
        assert session.key in sockets.session_connections
        assert (
            realtime_ticket_store.consume(
                usable_after_failure.ticket, session.key, "websocket"
            )
            is True
        )

        await session_manager.terminate_session(session.key)

        assert session.status is SessionStatus.TERMINATED
        assert session.terminated_at.isoformat() == committed["terminated_at"]
        assert polling_client.terminated is True
        assert session.key not in sockets.session_connections
        assert (
            realtime_ticket_store.consume(
                revoked_after_retry.ticket, session.key, "websocket"
            )
            is False
        )


@pytest.mark.asyncio
async def test_restart_rehydrates_active_session_for_same_tenant_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.api_gateway.tenant_persistence as persistence

    redis = PersistentFakeRedis()
    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(persistence.Redis, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(session_manager, "allow_parallel_sessions", False)

    async with lifespan(app):
        first = await session_manager.create_admin_session("tenant-a", SNAPSHOT)

    async with lifespan(app):
        assert session_manager.active_admin_sessions == {"tenant-a": {first.id}}
        second = await session_manager.create_admin_session("tenant-a", SNAPSHOT)

        assert session_manager.get_session(first.key).status is SessionStatus.TERMINATED
        assert session_manager.get_session(second.key).status is SessionStatus.PENDING
        assert session_manager.active_admin_sessions == {"tenant-a": {second.id}}


@pytest.mark.asyncio
@pytest.mark.parametrize("expired_by", ["absolute_lifetime", "reconnect_grace"])
async def test_restart_terminates_sessions_whose_persisted_deadline_expired(
    monkeypatch: pytest.MonkeyPatch,
    expired_by: str,
) -> None:
    import services.api_gateway.tenant_persistence as persistence

    redis = PersistentFakeRedis()
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(persistence.Redis, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(session_manager, "clock", lambda: now)

    async with lifespan(app):
        session = await session_manager.create_admin_session("tenant-a", SNAPSHOT)
        if expired_by == "absolute_lifetime":
            session_manager.admin_connected(session.key)

    now += timedelta(
        hours=8 if expired_by == "absolute_lifetime" else 0,
        minutes=0 if expired_by == "absolute_lifetime" else 30,
    )

    async with lifespan(app):
        restored = session_manager.get_session(session.key)
        assert restored is not None
        assert restored.status is SessionStatus.TERMINATED
        assert session_manager.resolve_customer_session(session.id) is None
        assert session_manager.active_admin_sessions == {}


@pytest.mark.asyncio
async def test_restart_clears_stale_transport_presence_and_starts_admin_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.api_gateway.tenant_persistence as persistence

    redis = PersistentFakeRedis()
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(persistence.Redis, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(session_manager, "clock", lambda: now)

    async with lifespan(app):
        session = await session_manager.create_admin_session("tenant-a", SNAPSHOT)
        session_manager.admin_connected(session.key)
        session_manager.customer_connected(session.key)

    now += timedelta(minutes=5)
    async with lifespan(app):
        restored = session_manager.get_session(session.key)
        assert restored is not None
        assert restored.admin_connected is False
        assert restored.customer_connected is False
        assert restored.admin_connection_count == 0
        assert restored.customer_connection_count == 0
        assert restored.admin_disconnected_at == now
        assert restored.next_timeout_at() == now + timedelta(minutes=30)
        persisted = session_manager.store.load(session.key)
        assert persisted is not None
        assert persisted.admin_disconnected_at == now
        assert persisted.admin_connection_count == 0
