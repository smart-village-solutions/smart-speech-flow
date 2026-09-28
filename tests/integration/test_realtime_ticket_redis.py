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

import json
import os
import threading
import time
from hashlib import sha256
from typing import Iterator
from uuid import uuid4

import pytest
from redis import Redis

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


# Production's client decodes replies (tenant_persistence.py); a default
# client returns bytes, which the adapter must decode itself.
@pytest.fixture(params=[True, False], ids=["decoded-client", "bytes-client"])
def backend(request: pytest.FixtureRequest) -> Iterator[RedisRealtimeTicketBackend]:
    client = Redis.from_url(os.environ["SSF_TEST_REDIS_URL"], decode_responses=request.param)
    try:
        yield RedisRealtimeTicketBackend(client)
    finally:
        client.close()


@pytest.fixture
def store(backend: RedisRealtimeTicketBackend, namespace: str) -> RealtimeTicketStore:
    return RealtimeTicketStore(backend, namespace=namespace)


def _keys(redis_client: Redis, namespace: str) -> list[str]:
    return sorted(key.decode() for key in redis_client.scan_iter(match=f"{namespace}:*"))


def test_a_ticket_is_consumed_exactly_once(store: RealtimeTicketStore) -> None:
    issued = store.issue(KEY, "websocket")

    assert store.consume(issued.ticket, KEY, "websocket") is True
    assert store.consume(issued.ticket, KEY, "websocket") is False


def test_consume_key_returns_the_issued_scope_once(store: RealtimeTicketStore) -> None:
    issued = store.issue(KEY, "polling")

    assert store.consume_key(issued.ticket, KEY.session_id, "polling") == KEY
    assert store.consume_key(issued.ticket, KEY.session_id, "polling") is None


def test_consuming_leaves_no_key_behind(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    issued = store.issue(KEY, "websocket")
    assert len(_keys(redis_client, namespace)) == 1

    assert store.consume(issued.ticket, KEY, "websocket") is True

    assert _keys(redis_client, namespace) == []


def test_an_unknown_ticket_is_refused(store: RealtimeTicketStore) -> None:
    assert store.consume("never-issued", KEY, "websocket") is False


def test_twenty_concurrent_consumers_have_exactly_one_winner(
    store: RealtimeTicketStore,
) -> None:
    issued = store.issue(KEY, "websocket")
    contenders = 20
    start = threading.Barrier(contenders)
    results: list[bool] = []
    results_lock = threading.Lock()

    def contend() -> None:
        start.wait()
        outcome = store.consume(issued.ticket, KEY, "websocket")
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=contend) for _ in range(contenders)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == contenders
    assert results.count(True) == 1


def test_a_ticket_expires_after_its_lifetime(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    issued = store.issue(KEY, "websocket", ttl_seconds=1)
    (ticket_key,) = _keys(redis_client, namespace)
    assert 0 < redis_client.pttl(ticket_key) <= 1000

    time.sleep(1.5)

    assert _keys(redis_client, namespace) == []
    assert store.consume(issued.ticket, KEY, "websocket") is False


def test_the_default_lifetime_is_sixty_seconds(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    store.issue(KEY, "websocket")
    (ticket_key,) = _keys(redis_client, namespace)

    assert 55 < redis_client.ttl(ticket_key) <= 60


def test_a_transport_mismatch_is_refused_and_spends_the_ticket(
    store: RealtimeTicketStore,
) -> None:
    issued = store.issue(KEY, "websocket")

    assert store.consume(issued.ticket, KEY, "polling") is False
    assert store.consume(issued.ticket, KEY, "websocket") is False


def test_a_session_mismatch_is_refused_and_spends_the_ticket(
    store: RealtimeTicketStore,
) -> None:
    issued = store.issue(KEY, "websocket")

    assert store.consume_key(issued.ticket, "OTHER123", "websocket") is None
    assert store.consume_key(issued.ticket, KEY.session_id, "websocket") is None


def test_a_tenant_mismatch_is_refused_and_spends_the_ticket(
    store: RealtimeTicketStore,
) -> None:
    same_id_other_tenant = TenantSessionKey("tenant-b", KEY.session_id)
    issued = store.issue(KEY, "websocket")

    assert store.consume(issued.ticket, same_id_other_tenant, "websocket") is False
    assert store.consume(issued.ticket, KEY, "websocket") is False


def test_revoke_invalidates_every_outstanding_ticket(
    store: RealtimeTicketStore,
) -> None:
    websocket = store.issue(KEY, "websocket")
    polling = store.issue(KEY, "polling")

    store.revoke(KEY)

    assert store.consume(websocket.ticket, KEY, "websocket") is False
    assert store.consume(polling.ticket, KEY, "polling") is False


def test_revoke_also_refuses_tickets_issued_after_it(
    store: RealtimeTicketStore,
) -> None:
    store.revoke(KEY)
    issued = store.issue(KEY, "websocket")

    assert store.consume(issued.ticket, KEY, "websocket") is False


def test_revoke_touches_only_its_own_session(store: RealtimeTicketStore) -> None:
    other_tenant = TenantSessionKey("tenant-b", KEY.session_id)
    other_session = TenantSessionKey(KEY.tenant_id, "OTHER123")
    tenant_ticket = store.issue(other_tenant, "websocket")
    session_ticket = store.issue(other_session, "websocket")

    store.revoke(KEY)

    assert store.consume(tenant_ticket.ticket, other_tenant, "websocket") is True
    assert store.consume(session_ticket.ticket, other_session, "websocket") is True


def test_a_repeat_revoke_refreshes_the_eight_hour_lifetime(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    store.revoke(KEY)
    (revoked_key,) = _keys(redis_client, namespace)
    assert REVOCATION_TTL_SECONDS - 5 < redis_client.ttl(revoked_key)
    assert redis_client.ttl(revoked_key) <= REVOCATION_TTL_SECONDS
    redis_client.expire(revoked_key, 100)

    store.revoke(KEY)

    assert REVOCATION_TTL_SECONDS - 5 < redis_client.ttl(revoked_key)


def test_the_ticket_key_holds_a_hash_and_the_payload_as_today(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    issued = store.issue(KEY, "websocket")

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


def test_the_revocation_key_layout_and_value(
    store: RealtimeTicketStore, redis_client: Redis, namespace: str
) -> None:
    store.revoke(KEY)

    # base64url("tenant-a") without padding.
    assert _keys(redis_client, namespace) == [
        f"{namespace}:v2:tenant:dGVuYW50LWE:session:ABC12345:realtime-revoked"
    ]
    assert redis_client.get(_keys(redis_client, namespace)[0]) == b"1"


def test_an_unreachable_redis_is_reported_as_unavailable(namespace: str) -> None:
    unreachable = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.5)
    store = RealtimeTicketStore(RedisRealtimeTicketBackend(unreachable), namespace=namespace)

    with pytest.raises(RealtimeTicketUnavailable):
        store.issue(KEY, "websocket")
    with pytest.raises(RealtimeTicketUnavailable):
        store.consume("any-ticket", KEY, "websocket")
    with pytest.raises(RealtimeTicketUnavailable):
        store.revoke(KEY)


def test_redis_consume_is_single_use(backend: RedisRealtimeTicketBackend, namespace: str) -> None:
    key = f"{namespace}:k"
    assert backend.put_if_absent(key, "value", 60) is True

    assert backend.consume(key) == "value"
    assert backend.consume(key) is None
    assert backend.get(key) is None


def test_redis_get_does_not_consume(backend: RedisRealtimeTicketBackend, namespace: str) -> None:
    key = f"{namespace}:k"
    backend.put(key, "value", 60)

    assert backend.get(key) == "value"
    assert backend.consume(key) == "value"


def test_redis_consume_has_one_winner_among_twenty_threads(
    backend: RedisRealtimeTicketBackend, namespace: str
) -> None:
    key = f"{namespace}:k"
    backend.put_if_absent(key, "value", 60)
    contenders = 20
    start = threading.Barrier(contenders)
    results: list[str | None] = []
    results_lock = threading.Lock()

    def contend() -> None:
        start.wait()
        outcome = backend.consume(key)
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=contend) for _ in range(contenders)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == contenders
    assert results.count("value") == 1


def test_redis_values_expire_after_their_lifetime(
    backend: RedisRealtimeTicketBackend, namespace: str
) -> None:
    ticket, revoked = f"{namespace}:ticket", f"{namespace}:revoked"
    backend.put_if_absent(ticket, "value", 1)
    backend.put(revoked, "1", 1)
    assert backend.get(ticket) == "value"

    time.sleep(1.5)

    assert backend.consume(ticket) is None
    assert backend.get(revoked) is None


def test_redis_put_if_absent_keeps_a_live_value(
    backend: RedisRealtimeTicketBackend, namespace: str
) -> None:
    key = f"{namespace}:k"
    assert backend.put_if_absent(key, "first", 1) is True
    assert backend.put_if_absent(key, "second", 60) is False
    assert backend.get(key) == "first"

    time.sleep(1.5)

    assert backend.put_if_absent(key, "third", 60) is True
    assert backend.get(key) == "third"


def test_redis_put_overwrites_and_restarts_the_lifetime(
    backend: RedisRealtimeTicketBackend, redis_client: Redis, namespace: str
) -> None:
    key = f"{namespace}:k"
    backend.put(key, "first", 10)
    redis_client.expire(key, 2)

    backend.put(key, "second", 10)

    assert backend.get(key) == "second"
    assert redis_client.ttl(key) > 5


def test_the_redis_adapter_returns_str_from_a_bytes_client(
    backend: RedisRealtimeTicketBackend, namespace: str
) -> None:
    key = f"{namespace}:k"
    backend.put(key, "välue", 60)

    assert backend.get(key) == "välue"
    assert backend.consume(key) == "välue"
