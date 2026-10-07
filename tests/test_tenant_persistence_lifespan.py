"""Production lifespan wiring for the tenant-scoped Redis stores."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketState

from services.api_gateway.app import app, lifespan
from services.api_gateway.realtime_ticket import RedisRealtimeTicketBackend
from services.api_gateway.session_models import ClientType, SessionMessage, SessionStatus
from services.api_gateway.session_store import (
    RedisTenantSessionStore,
    SessionStoreConsistencyError,
    join_key,
)
from services.api_gateway.session_store import session_key as persisted_session_key
from services.api_gateway.tenant_context import admin_ref

REVISION = f"sha256:{'a' * 64}"


class PersistentFakeRedis:
    """Small redis.asyncio contract shared by two real application lifespans."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.pings = 0
        self.expiries: dict[str, int] = {}
        self.fail_after_next_termination = False

    async def ping(self) -> bool:
        self.pings += 1
        return True

    async def aclose(self) -> None:
        return None

    async def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def mget(self, *keys):
        return [self.values.get(key) for key in keys]

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def scan_iter(self, *, match):
        for key in [key for key in self.sets if fnmatch(key, match)]:
            yield key

    async def eval(self, script, number_of_keys, *values):
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

        if ":v2:join:" in keys[1]:
            session_key_value, join_key_value, active_index = keys
            (
                session_payload,
                session_id,
                tenant_id,
                expected_join,
                terminal_join,
            ) = argv
            current_payload = self.values.get(session_key_value)
            current_join = self.values.get(join_key_value)
            if current_payload is None:
                return 0
            current = json.loads(current_payload)
            proposed = json.loads(session_payload)
            if (
                current["id"] != session_id
                or current["tenant_id"] != tenant_id
                or proposed["id"] != session_id
                or proposed["tenant_id"] != tenant_id
            ):
                return 0
            if current["status"] == "terminated":
                if (
                    current_join != terminal_join
                    or session_id in self.sets.setdefault(active_index, set())
                    or session_payload != current_payload
                ):
                    return 0
                return 1
            if (
                current_join != expected_join
                or session_id not in self.sets.setdefault(active_index, set())
                or proposed["status"] == "terminated"
            ):
                return 0
            self.values[session_key_value] = session_payload
            return 1

        session_key_value, active_index, join_key_value = keys
        (
            session_payload,
            session_id,
            expected_join,
            terminal_join,
            tenant_id,
            retention_seconds,
        ) = argv
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
        # Mirrors the script's EXPIRE on the record alone; the tombstone stays.
        if retention_seconds and int(retention_seconds) > 0:
            self.expiries[session_key_value] = int(retention_seconds)
        self.sets.setdefault(active_index, set()).discard(session_id)
        self.values[join_key_value] = terminal_join
        if self.fail_after_next_termination:
            self.fail_after_next_termination = False
            raise ConnectionError("reply lost after Redis committed")
        return 1


def _clock_every_manager(monkeypatch: pytest.MonkeyPatch, clock) -> None:
    """Each lifespan builds its own session manager; give every one this clock."""
    import services.api_gateway.session_manager as sessions_module

    real = sessions_module.TenantSessionManager
    monkeypatch.setattr(
        sessions_module,
        "TenantSessionManager",
        lambda **kwargs: real(clock=clock, **kwargs),
    )


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
        "from_pool",
        lambda *_args, **_kwargs: redis,
    )

    async with lifespan(app):
        dependencies = app.state.dependencies
        session_manager = dependencies.session_manager
        assert isinstance(session_manager.store, RedisTenantSessionStore)
        assert session_manager.store.redis is redis
        assert isinstance(dependencies.realtime_tickets.backend, RedisRealtimeTicketBackend)
        assert dependencies.realtime_tickets.backend.redis is redis
        assert session_manager.websocket_manager is dependencies.websocket_manager
        session = await session_manager.create_admin_session("tenant-a", REVISION)
        issued = await dependencies.realtime_tickets.issue(session.key, "websocket")

    async with lifespan(app):
        dependencies = app.state.dependencies
        session_manager = dependencies.session_manager
        assert session_manager.websocket_manager is dependencies.websocket_manager
        realtime_ticket_store = dependencies.realtime_tickets
        restored = await session_manager.get_session(session.key)
        assert restored is not None
        assert restored is not session
        assert restored.configuration_revision == REVISION
        assert await realtime_ticket_store.consume(issued.ticket, session.key, "websocket") is True
        assert await realtime_ticket_store.consume(issued.ticket, session.key, "websocket") is False

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
        async def ping(self):
            raise ConnectionError("private redis endpoint")

        async def aclose(self) -> None:
            return None

    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(
        persistence.Redis,
        "from_pool",
        lambda *_args, **_kwargs: BrokenRedis(),
    )

    with pytest.raises(persistence.TenantPersistenceUnavailable):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_ambiguous_termination_rejects_stale_saves_before_cleanup_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.api_gateway.tenant_persistence as persistence

    redis = PersistentFakeRedis()
    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(persistence.Redis, "from_pool", lambda *_args, **_kwargs: redis)

    async with lifespan(app):
        dependencies = app.state.dependencies
        session_manager = dependencies.session_manager
        realtime_ticket_store = dependencies.realtime_tickets
        polling = dependencies.polling_store
        monkeypatch.setattr(polling, "clock", lambda: 0.0)
        sockets = dependencies.websocket_manager
        monkeypatch.setattr(sockets, "start_heartbeat_system", AsyncMock())
        session = await session_manager.create_admin_session("tenant-a", REVISION)
        usable_after_failure = await realtime_ticket_store.issue(session.key, "websocket")
        revoked_after_retry = await realtime_ticket_store.issue(session.key, "websocket")
        polling_client = polling.activate(session.key, ClientType.CUSTOMER)
        websocket = AsyncMock()
        websocket.client_state = WebSocketState.CONNECTED
        await sockets.connect_websocket(websocket, session.key, ClientType.ADMIN)
        redis.fail_after_next_termination = True

        with pytest.raises(ConnectionError, match="reply lost"):
            await session_manager.terminate_session(session.key)

        assert session.status is SessionStatus.PENDING
        assert json.loads(redis.values.get(join_key("ssf", session.id)))["active"] is False
        committed = json.loads(redis.values.get(persisted_session_key("ssf", session.key)))
        committed_payload = redis.values.get(persisted_session_key("ssf", session.key))
        assert committed["status"] == "terminated"
        assert polling_client.terminated is False
        assert session.key in sockets.session_connections
        assert (
            await realtime_ticket_store.consume(usable_after_failure.ticket, session.key, "websocket")
            is True
        )

        with pytest.raises(
            SessionStoreConsistencyError, match="session lifecycle does not permit save"
        ):
            await session_manager.admin_disconnected(session.key)

        stale_message = SessionMessage(
            id="stale-after-terminal-commit",
            sender=ClientType.ADMIN,
            original_text="must not persist",
            translated_text="must not persist",
            audio_base64=None,
            source_lang="de",
            target_lang="en",
            timestamp=datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc),
        )
        with pytest.raises(
            SessionStoreConsistencyError, match="session lifecycle does not permit save"
        ):
            await session_manager.add_message(session.key, stale_message)

        assert redis.values.get(persisted_session_key("ssf", session.key)) == committed_payload
        assert json.loads(redis.values.get(join_key("ssf", session.id))) == {
            "active": False,
            "session_id": session.id,
            "tenant_id": "tenant-a",
        }

        await session_manager.terminate_session(session.key)

        assert session.status is SessionStatus.TERMINATED
        assert session.terminated_at.isoformat() == committed["terminated_at"]
        assert session.messages == []
        assert redis.values.get(persisted_session_key("ssf", session.key)) == committed_payload
        assert polling_client.terminated is True
        assert session.key not in sockets.session_connections
        assert (
            await realtime_ticket_store.consume(revoked_after_retry.ticket, session.key, "websocket")
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
    monkeypatch.setattr(persistence.Redis, "from_pool", lambda *_args, **_kwargs: redis)
    monkeypatch.setenv("SSF_ALLOW_PARALLEL_SESSIONS", "false")
    owner = admin_ref("tenant-a", "admin-subject")

    async with lifespan(app):
        session_manager = app.state.dependencies.session_manager
        first = await session_manager.create_admin_session("tenant-a", REVISION, owner_ref=owner)

    async with lifespan(app):
        session_manager = app.state.dependencies.session_manager
        assert session_manager.active_admin_sessions == {"tenant-a": {first.id}}
        second = await session_manager.create_admin_session("tenant-a", REVISION, owner_ref=owner)

        assert (await session_manager.get_session(first.key)).status is SessionStatus.TERMINATED
        assert (await session_manager.get_session(second.key)).status is SessionStatus.PENDING
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
    monkeypatch.setattr(persistence.Redis, "from_pool", lambda *_args, **_kwargs: redis)
    _clock_every_manager(monkeypatch, lambda: now)

    async with lifespan(app):
        session_manager = app.state.dependencies.session_manager
        session = await session_manager.create_admin_session("tenant-a", REVISION)
        if expired_by == "absolute_lifetime":
            await session_manager.admin_connected(session.key)

    now += timedelta(
        hours=8 if expired_by == "absolute_lifetime" else 0,
        minutes=0 if expired_by == "absolute_lifetime" else 30,
    )

    async with lifespan(app):
        session_manager = app.state.dependencies.session_manager
        restored = await session_manager.get_session(session.key)
        assert restored is not None
        assert restored.status is SessionStatus.TERMINATED
        assert await session_manager.resolve_customer_session(session.id) is None
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
    monkeypatch.setattr(persistence.Redis, "from_pool", lambda *_args, **_kwargs: redis)
    _clock_every_manager(monkeypatch, lambda: now)

    async with lifespan(app):
        session_manager = app.state.dependencies.session_manager
        session = await session_manager.create_admin_session("tenant-a", REVISION)
        await session_manager.admin_connected(session.key)
        await session_manager.customer_connected(session.key)

    now += timedelta(minutes=5)
    async with lifespan(app):
        session_manager = app.state.dependencies.session_manager
        restored = await session_manager.get_session(session.key)
        assert restored is not None
        assert restored.admin_connected is False
        assert restored.customer_connected is False
        assert restored.admin_connection_count == 0
        assert restored.customer_connection_count == 0
        assert restored.admin_disconnected_at == now
        assert restored.next_timeout_at() == now + timedelta(minutes=30)
        persisted = await session_manager.store.load(session.key)
        assert persisted is not None
        assert persisted.admin_disconnected_at == now
        assert persisted.admin_connection_count == 0


@pytest.mark.asyncio
async def test_a_client_that_fails_its_ping_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.api_gateway.tenant_persistence as persistence

    closed: list[bool] = []

    class UnreachableRedis:
        async def ping(self):
            raise ConnectionError("private redis endpoint")

        async def aclose(self) -> None:
            closed.append(True)

    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setattr(persistence.Redis, "from_pool", lambda *_args, **_kwargs: UnreachableRedis())

    with pytest.raises(persistence.TenantPersistenceUnavailable):
        await persistence.configure_tenant_persistence()

    assert closed == [True]


@pytest.mark.asyncio
async def test_a_failed_rehydrate_closes_the_connection_before_startup_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.api_gateway.session_manager as sessions_module
    import services.api_gateway.tenant_persistence as persistence
    from services.api_gateway.session_store import SessionStoreConsistencyError

    redis = PersistentFakeRedis()
    closed: list[bool] = []

    async def record_close() -> None:
        closed.append(True)

    async def inconsistent_index(self) -> None:
        raise SessionStoreConsistencyError("active session index does not match session")

    redis.aclose = record_close
    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(persistence.Redis, "from_pool", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(
        sessions_module.TenantSessionManager, "rehydrate_tenant_sessions", inconsistent_index
    )

    with pytest.raises(SessionStoreConsistencyError):
        async with lifespan(app):
            pass

    assert closed == [True]


@pytest.mark.asyncio
async def test_shutdown_lets_pending_presence_releases_finish_before_closing_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import services.api_gateway.tenant_persistence as persistence

    redis = PersistentFakeRedis()
    released: list[bool] = []
    released_when_closed: list[bool] = []

    async def record_close() -> None:
        released_when_closed.append(bool(released))

    async def slow_release() -> None:
        await asyncio.sleep(0.05)
        released.append(True)

    redis.aclose = record_close
    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(persistence.Redis, "from_pool", lambda *_args, **_kwargs: redis)

    async with lifespan(app):
        polling_store = app.state.dependencies.polling_store
        task = asyncio.create_task(slow_release())
        polling_store.release_tasks.add(task)
        task.add_done_callback(polling_store.release_tasks.discard)

    assert released_when_closed == [True]


@pytest.mark.asyncio
async def test_a_busy_pool_makes_commands_wait_rather_than_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async default pool raises at once when every connection is busy.

    The tenant pool blocks instead: a command waits up to the socket timeout
    for a free connection, so a burst does not turn into 503s and failed saves.
    """
    from redis.asyncio import BlockingConnectionPool

    import services.api_gateway.tenant_persistence as persistence

    pools: list[object] = []
    redis = PersistentFakeRedis()

    def adopt(pool):
        pools.append(pool)
        return redis

    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setattr(persistence.Redis, "from_pool", adopt)

    binding = await persistence.configure_tenant_persistence()

    assert binding is not None
    (pool,) = pools
    assert isinstance(pool, BlockingConnectionPool)
    assert pool.max_connections == 100
    assert pool.timeout == 5
    assert pool.connection_kwargs["socket_timeout"] == 5
    assert pool.connection_kwargs["socket_connect_timeout"] == 5
    assert pool.connection_kwargs["decode_responses"] is True


@pytest.mark.asyncio
async def test_any_failed_startup_step_closes_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.api_gateway.app as gateway
    import services.api_gateway.tenant_persistence as persistence

    redis = PersistentFakeRedis()
    closed: list[bool] = []

    async def record_close() -> None:
        closed.append(True)

    def background_tasks_fail(*_args):
        raise RuntimeError("background tasks could not start")

    redis.aclose = record_close
    monkeypatch.setenv("SSF_DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "redis://tenant-state.example:6379/0")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setattr(persistence.Redis, "from_pool", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(gateway, "_start_background_tasks", background_tasks_fail)

    with pytest.raises(RuntimeError):
        async with lifespan(app):
            pass

    assert closed == [True]
