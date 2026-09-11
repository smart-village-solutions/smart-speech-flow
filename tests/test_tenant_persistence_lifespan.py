"""Production lifespan wiring for the tenant-scoped Redis stores."""

from __future__ import annotations

import json

import pytest

from services.api_gateway.app import app, lifespan
from services.api_gateway.realtime_ticket import realtime_ticket_store
from services.api_gateway.session_manager import session_manager
from services.api_gateway.session_store import RedisTenantSessionStore
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot
from services.api_gateway.websocket import get_websocket_manager

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


class PersistentFakeRedis:
    """Small Redis contract shared by two real application lifespans."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.pings = 0

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

        session_key, active_index, join_key = keys
        session_payload, session_id, expected_join, terminal_join = argv
        if self.values.get(join_key) != expected_join:
            return 0
        self.values[session_key] = session_payload
        self.sets.setdefault(active_index, set()).discard(session_id)
        self.values[join_key] = terminal_join
        return 1


@pytest.fixture(autouse=True)
def _clean_global_memory_state():
    session_manager.reset(clear_persistence=True)
    original_ticket_backend = realtime_ticket_store.redis
    if hasattr(original_ticket_backend, "values"):
        original_ticket_backend.values.clear()
    yield
    session_manager.reset(clear_persistence=True)
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
