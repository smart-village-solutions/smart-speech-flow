"""Realtime ticket semantics against a real Redis.

The unit suites run the ticket store over an in-memory double, which cannot
show that CONSUME_TICKET_LUA really is an atomic get-and-delete, that Redis
expires a ticket, or what the keys and values look like on the server. These
tests drive the store over the Redis adapter and a real client and pin all
of that. The adapter's own contract cases match the memory adapter's in
tests/test_realtime_ticket.py, so both are held to one contract.

Marked integration, and skipped unless SSF_TEST_REDIS_URL is set. CI has no
Redis service, so CI skips them. Run with
    docker run -d --rm --name ssf-ticket-redis -p 6390:6379 redis:7.4.7-alpine
    SSF_TEST_REDIS_URL=redis://127.0.0.1:6390/0 \
    pytest tests/integration/test_realtime_ticket_redis.py --run-integration

Each test works in its own random namespace and deletes only that namespace's
keys, so a shared Redis is safe to point this at.
"""

from __future__ import annotations

import asyncio
import json
import os
from hashlib import sha256
from typing import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from services.api_gateway.realtime_ticket import (
    RealtimeTicketStore,
    RealtimeTicketUnavailable,
    RedisRealtimeTicketBackend,
)
from services.api_gateway.tenant_session import TenantSessionKey

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SSF_TEST_REDIS_URL"),
        reason="set SSF_TEST_REDIS_URL to run the ticket store against a real Redis",
    ),
]

KEY = TenantSessionKey("tenant-a", "ABC12345")
REVOCATION_TTL_SECONDS = 8 * 60 * 60


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = Redis.from_url(os.environ["SSF_TEST_REDIS_URL"])
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def namespace(redis_client: Redis) -> Iterator[str]:
    name = f"ssf-ticket-test-{uuid4().hex}"
    try:
        yield name
    finally:
        keys = list(redis_client.scan_iter(match=f"{name}:*"))
        if keys:
            redis_client.delete(*keys)


# The adapter runs on production's async client, which decodes replies
# (tenant_persistence.py); a default client returns bytes, which the adapter
# must decode itself. Assertions inspect Redis through a separate sync client.
@pytest.fixture(params=[True, False], ids=["decoded-client", "bytes-client"])
async def backend(request: pytest.FixtureRequest) -> AsyncIterator[RedisRealtimeTicketBackend]:
    client = AsyncRedis.from_url(os.environ["SSF_TEST_REDIS_URL"], decode_responses=request.param)
    try:
        yield RedisRealtimeTicketBackend(client)
    finally:
        await client.aclose()


@pytest.fixture
def store(backend: RedisRealtimeTicketBackend, namespace: str) -> RealtimeTicketStore:
    return RealtimeTicketStore(backend, namespace=namespace)


def _keys(redis_client: Redis, namespace: str) -> list[str]:
    return sorted(key.decode() for key in redis_client.scan_iter(match=f"{namespace}:*"))


async def test_a_ticket_is_consumed_exactly_once(store: RealtimeTicketStore) -> None:
    issued = await store.issue(KEY, "websocket")

    assert await store.consume(issued.ticket, KEY, "websocket") is True
    assert await store.consume(issued.ticket, KEY, "websocket") is False


async def test_consume_key_returns_the_issued_scope_once(store: RealtimeTicketStore) -> None:
    issued = await store.issue(KEY, "polling")

    assert await store.consume_key(issued.ticket, KEY.session_id, "polling") == KEY
    assert await store.consume_key(issued.ticket, KEY.session_id, "polling") is None


async def test_consuming_leaves_no_key_behind(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    issued = await store.issue(KEY, "websocket")
    assert len(_keys(redis_client, namespace)) == 1

    assert await store.consume(issued.ticket, KEY, "websocket") is True

    assert _keys(redis_client, namespace) == []


async def test_an_unknown_ticket_is_refused(store: RealtimeTicketStore) -> None:
    assert await store.consume("never-issued", KEY, "websocket") is False


async def test_twenty_concurrent_consumers_have_exactly_one_winner(
    store: RealtimeTicketStore,
) -> None:
    issued = await store.issue(KEY, "websocket")

    results = await asyncio.gather(*(store.consume(issued.ticket, KEY, "websocket") for _ in range(20)))

    assert results.count(True) == 1


async def test_a_ticket_expires_after_its_lifetime(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    issued = await store.issue(KEY, "websocket", ttl_seconds=1)
    (ticket_key,) = _keys(redis_client, namespace)
    assert 0 < redis_client.pttl(ticket_key) <= 1000

    await asyncio.sleep(1.5)

    assert _keys(redis_client, namespace) == []
    assert await store.consume(issued.ticket, KEY, "websocket") is False


async def test_the_default_lifetime_is_sixty_seconds(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    await store.issue(KEY, "websocket")
    (ticket_key,) = _keys(redis_client, namespace)

    assert 55 < redis_client.ttl(ticket_key) <= 60


async def test_a_transport_mismatch_is_refused_and_spends_the_ticket(
    store: RealtimeTicketStore,
) -> None:
    issued = await store.issue(KEY, "websocket")

    assert await store.consume(issued.ticket, KEY, "polling") is False
    assert await store.consume(issued.ticket, KEY, "websocket") is False


async def test_a_session_mismatch_is_refused_and_spends_the_ticket(
    store: RealtimeTicketStore,
) -> None:
    issued = await store.issue(KEY, "websocket")

    assert await store.consume_key(issued.ticket, "OTHER123", "websocket") is None
    assert await store.consume_key(issued.ticket, KEY.session_id, "websocket") is None


async def test_a_tenant_mismatch_is_refused_and_spends_the_ticket(
    store: RealtimeTicketStore,
) -> None:
    same_id_other_tenant = TenantSessionKey("tenant-b", KEY.session_id)
    issued = await store.issue(KEY, "websocket")

    assert await store.consume(issued.ticket, same_id_other_tenant, "websocket") is False
    assert await store.consume(issued.ticket, KEY, "websocket") is False


async def test_revoke_invalidates_every_outstanding_ticket(
    store: RealtimeTicketStore,
) -> None:
    websocket = await store.issue(KEY, "websocket")
    polling = await store.issue(KEY, "polling")

    await store.revoke(KEY)

    assert await store.consume(websocket.ticket, KEY, "websocket") is False
    assert await store.consume(polling.ticket, KEY, "polling") is False


async def test_revoke_also_refuses_tickets_issued_after_it(
    store: RealtimeTicketStore,
) -> None:
    await store.revoke(KEY)
    issued = await store.issue(KEY, "websocket")

    assert await store.consume(issued.ticket, KEY, "websocket") is False


async def test_revoke_touches_only_its_own_session(store: RealtimeTicketStore) -> None:
    other_tenant = TenantSessionKey("tenant-b", KEY.session_id)
    other_session = TenantSessionKey(KEY.tenant_id, "OTHER123")
    tenant_ticket = await store.issue(other_tenant, "websocket")
    session_ticket = await store.issue(other_session, "websocket")

    await store.revoke(KEY)

    assert await store.consume(tenant_ticket.ticket, other_tenant, "websocket") is True
    assert await store.consume(session_ticket.ticket, other_session, "websocket") is True


async def test_a_repeat_revoke_refreshes_the_eight_hour_lifetime(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    await store.revoke(KEY)
    (revoked_key,) = _keys(redis_client, namespace)
    assert REVOCATION_TTL_SECONDS - 5 < redis_client.ttl(revoked_key)
    assert redis_client.ttl(revoked_key) <= REVOCATION_TTL_SECONDS
    redis_client.expire(revoked_key, 100)

    await store.revoke(KEY)

    assert REVOCATION_TTL_SECONDS - 5 < redis_client.ttl(revoked_key)


async def test_the_ticket_key_holds_a_hash_and_the_payload_as_today(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    issued = await store.issue(KEY, "websocket")

    (ticket_key,) = _keys(redis_client, namespace)
    digest = sha256(issued.ticket.encode("ascii")).hexdigest()
    assert ticket_key == f"{namespace}:v2:realtime-ticket:{digest}"
    assert redis_client.type(ticket_key) == b"string"
    stored = redis_client.get(ticket_key)
    assert stored is not None
    assert issued.ticket.encode() not in stored
    assert stored == (
        b'{"role":"admin","session_id":"ABC12345",'
        b'"tenant_id":"tenant-a","transport":"websocket"}'
    )
    assert json.loads(stored)["transport"] == "websocket"


async def test_the_revocation_key_layout_and_value(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    await store.revoke(KEY)

    # base64url("tenant-a") without padding.
    assert _keys(redis_client, namespace) == [
        f"{namespace}:v2:tenant:dGVuYW50LWE:session:ABC12345:realtime-revoked"
    ]
    assert redis_client.get(_keys(redis_client, namespace)[0]) == b"1"


async def test_an_unreachable_redis_is_reported_as_unavailable(namespace: str) -> None:
    unreachable = AsyncRedis(host="127.0.0.1", port=1, socket_connect_timeout=0.5)
    store = RealtimeTicketStore(RedisRealtimeTicketBackend(unreachable), namespace=namespace)

    try:
        with pytest.raises(RealtimeTicketUnavailable):
            await store.issue(KEY, "websocket")
        with pytest.raises(RealtimeTicketUnavailable):
            await store.consume("any-ticket", KEY, "websocket")
        with pytest.raises(RealtimeTicketUnavailable):
            await store.revoke(KEY)
    finally:
        await unreachable.aclose()


async def test_redis_consume_is_single_use(backend: RedisRealtimeTicketBackend, namespace: str) -> None:
    key = f"{namespace}:k"
    assert await backend.put_if_absent(key, "value", 60) is True

    assert await backend.consume(key) == "value"
    assert await backend.consume(key) is None
    assert await backend.get(key) is None


async def test_redis_get_does_not_consume(backend: RedisRealtimeTicketBackend, namespace: str) -> None:
    key = f"{namespace}:k"
    await backend.put(key, "value", 60)

    assert await backend.get(key) == "value"
    assert await backend.consume(key) == "value"


async def test_redis_consume_has_one_winner_among_twenty_tasks(
    backend: RedisRealtimeTicketBackend, namespace: str
) -> None:
    key = f"{namespace}:k"
    await backend.put_if_absent(key, "value", 60)

    results = await asyncio.gather(*(backend.consume(key) for _ in range(20)))

    assert results.count("value") == 1


async def test_redis_values_expire_after_their_lifetime(
    backend: RedisRealtimeTicketBackend, namespace: str
) -> None:
    ticket, revoked = f"{namespace}:ticket", f"{namespace}:revoked"
    await backend.put_if_absent(ticket, "value", 1)
    await backend.put(revoked, "1", 1)
    assert await backend.get(ticket) == "value"

    await asyncio.sleep(1.5)

    assert await backend.consume(ticket) is None
    assert await backend.get(revoked) is None


async def test_redis_put_if_absent_keeps_a_live_value(
    backend: RedisRealtimeTicketBackend, namespace: str
) -> None:
    key = f"{namespace}:k"
    assert await backend.put_if_absent(key, "first", 1) is True
    assert await backend.put_if_absent(key, "second", 60) is False
    assert await backend.get(key) == "first"

    await asyncio.sleep(1.5)

    assert await backend.put_if_absent(key, "third", 60) is True
    assert await backend.get(key) == "third"


async def test_redis_put_overwrites_and_restarts_the_lifetime(
    backend: RedisRealtimeTicketBackend, redis_client: Redis, namespace: str
) -> None:
    key = f"{namespace}:k"
    await backend.put(key, "first", 10)
    redis_client.expire(key, 2)

    await backend.put(key, "second", 10)

    assert await backend.get(key) == "second"
    assert redis_client.ttl(key) > 5


async def test_the_redis_adapter_returns_str_from_a_bytes_client(
    backend: RedisRealtimeTicketBackend, namespace: str
) -> None:
    key = f"{namespace}:k"
    await backend.put(key, "välue", 60)

    assert await backend.get(key) == "välue"
    assert await backend.consume(key) == "välue"
