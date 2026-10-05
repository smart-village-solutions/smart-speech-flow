"""The async tenant session store against a real Redis (#428).

The unit suites drive the store over recording doubles, which cannot run the
Lua scripts, expire a key or race two pool connections. These tests drive
`RedisTenantSessionStore` over `redis.asyncio`, as production does, and read
the server back through a separate synchronous client.

Marked integration, and skipped unless SSF_TEST_REDIS_URL is set. CI has no
Redis service, so CI skips them. Run with
    docker run -d --rm --name ssf-session-redis -p 6391:6379 redis:7.4.7-alpine
    SSF_TEST_REDIS_URL=redis://127.0.0.1:6391/0 \
    pytest tests/integration/test_tenant_session_store_redis.py --run-integration

Each test works in its own random namespace and deletes only that namespace's
keys, so a shared Redis is safe to point this at.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from services.api_gateway.session_models import Session, SessionStatus
from services.api_gateway.session_store import (
    RedisTenantSessionStore,
    SessionStoreConsistencyError,
    join_key,
    session_key,
    tenant_active_sessions_key,
    tenant_sessions_key,
)
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SSF_TEST_REDIS_URL"),
        reason="set SSF_TEST_REDIS_URL to run the session store against a real Redis",
    ),
]

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")
TERMINATED_AT = datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)


def make_session(tenant_id: str, session_id: str) -> Session:
    return Session(id=session_id, tenant_id=tenant_id, runtime_configuration=SNAPSHOT)


def terminal(session: Session) -> Session:
    return replace(session, status=SessionStatus.TERMINATED, terminated_at=TERMINATED_AT)


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = Redis.from_url(os.environ["SSF_TEST_REDIS_URL"], decode_responses=True)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def namespace(redis_client: Redis) -> Iterator[str]:
    name = f"ssf-session-test-{uuid4().hex}"
    try:
        yield name
    finally:
        keys = list(redis_client.scan_iter(match=f"{name}:*"))
        if keys:
            redis_client.delete(*keys)


@pytest.fixture
async def store(namespace: str) -> AsyncIterator[RedisTenantSessionStore]:
    # Configured as tenant_persistence.py configures production's client.
    client = AsyncRedis.from_url(
        os.environ["SSF_TEST_REDIS_URL"],
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        yield RedisTenantSessionStore(client, namespace=namespace)
    finally:
        await client.aclose()


async def test_a_created_session_loads_back_and_resolves_its_join(
    store: RedisTenantSessionStore,
) -> None:
    session = make_session("tenant-a", "ABC12345")

    assert await store.create(session) is True

    assert await store.load(session.key) == session
    assert await store.resolve_join(session.id) == session.key
    assert await store.resolve_ended_join(session.id) is None


async def test_the_create_writes_the_v2_keys(
    store: RedisTenantSessionStore, redis_client: Redis, namespace: str
) -> None:
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)

    assert json.loads(redis_client.get(session_key(namespace, session.key)))["id"] == "ABC12345"
    assert redis_client.smembers(tenant_sessions_key(namespace, "tenant-a")) == {"ABC12345"}
    assert redis_client.smembers(tenant_active_sessions_key(namespace, "tenant-a")) == {"ABC12345"}
    assert json.loads(redis_client.get(join_key(namespace, "ABC12345"))) == {
        "active": True,
        "session_id": "ABC12345",
        "tenant_id": "tenant-a",
    }


async def test_a_session_id_is_globally_unique_across_tenants(
    store: RedisTenantSessionStore,
) -> None:
    assert await store.create(make_session("tenant-a", "ABC12345")) is True

    assert await store.create(make_session("tenant-b", "ABC12345")) is False
    assert await store.list_for_tenant("tenant-b") == []


async def test_concurrent_creates_of_one_id_have_one_winner(
    store: RedisTenantSessionStore,
) -> None:
    results = await asyncio.gather(
        *(store.create(make_session(f"tenant-{index}", "ABC12345")) for index in range(10))
    )

    assert results.count(True) == 1


async def test_a_save_persists_the_change(store: RedisTenantSessionStore) -> None:
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)
    session.customer_language = "ar"

    await store.save(session)

    loaded = await store.load(session.key)
    assert loaded is not None
    assert loaded.customer_language == "ar"


async def test_twenty_concurrent_saves_leave_the_final_state(
    store: RedisTenantSessionStore,
) -> None:
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)

    async def save_count(count: int) -> None:
        session.admin_connection_count = count
        await store.save(session)

    await asyncio.gather(*(save_count(count) for count in range(1, 21)))

    loaded = await store.load(session.key)
    assert loaded is not None
    assert loaded.admin_connection_count == 20
    assert len(store._write_locks) == 0


async def test_termination_revokes_the_join_and_refuses_later_saves(
    store: RedisTenantSessionStore, redis_client: Redis, namespace: str
) -> None:
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)

    committed = await store.terminate(terminal(session))

    assert committed.status is SessionStatus.TERMINATED
    assert await store.resolve_join(session.id) is None
    assert await store.resolve_ended_join(session.id) == (session.key, TERMINATED_AT)
    assert redis_client.smembers(tenant_active_sessions_key(namespace, "tenant-a")) == set()
    # An identical re-save is an idempotent no-op; any change is refused.
    await store.save(committed)
    with pytest.raises(SessionStoreConsistencyError):
        await store.save(replace(committed, customer_language="ar"))


async def test_termination_expires_the_record_but_not_the_tombstone(
    store: RedisTenantSessionStore,
    redis_client: Redis,
    namespace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "24")
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)

    await store.terminate(terminal(session))

    assert 24 * 3600 - 5 < redis_client.ttl(session_key(namespace, session.key)) <= 24 * 3600
    assert redis_client.ttl(join_key(namespace, session.id)) == -1
    assert await store.create(make_session("tenant-a", "ABC12345")) is False


async def test_a_repeated_termination_returns_the_persisted_record(
    store: RedisTenantSessionStore,
) -> None:
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)
    first = await store.terminate(terminal(session))

    second = await store.terminate(replace(terminal(session), termination_reason="retry"))

    assert second == first


async def test_list_active_spans_tenants_and_skips_terminated_sessions(
    store: RedisTenantSessionStore,
) -> None:
    live_a = make_session("tenant-a", "LIVEAAAA")
    live_b = make_session("tenant-b", "LIVEBBBB")
    ended = make_session("tenant-a", "ENDEDAAA")
    for session in (live_a, live_b, ended):
        await store.create(session)
    await store.terminate(terminal(ended))

    active = await store.list_active()

    assert sorted(session.id for session in active) == ["LIVEAAAA", "LIVEBBBB"]


async def test_list_for_tenant_returns_only_that_tenants_sessions(
    store: RedisTenantSessionStore,
) -> None:
    await store.create(make_session("tenant-a", "AAAA1111"))
    await store.create(make_session("tenant-b", "BBBB2222"))

    assert [session.id for session in await store.list_for_tenant("tenant-a")] == ["AAAA1111"]


async def test_a_record_rewritten_under_another_tenant_is_quarantined(
    store: RedisTenantSessionStore, redis_client: Redis, namespace: str
) -> None:
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)
    redis_client.set(
        session_key(namespace, session.key),
        RedisTenantSessionStore._session_payload(replace(session, tenant_id="tenant-b")),
    )

    assert await store.load(session.key) is None
    assert await store.resolve_join(session.id) is None
