"""Single-use, scoped realtime capability tickets.

The backend contract cases here are the same ones
tests/integration/test_realtime_ticket_redis.py runs against a real Redis, so
the memory adapter and the Redis adapter are held to one contract.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import redis

from services.api_gateway.realtime_ticket import (
    CONSUME_TICKET_LUA,
    MemoryRealtimeTicketBackend,
    RealtimeTicketStore,
    RealtimeTicketUnavailable,
    RedisRealtimeTicketBackend,
)
from services.api_gateway.tenant_session import TenantSessionKey


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 11, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def backend(clock: Clock) -> MemoryRealtimeTicketBackend:
    return MemoryRealtimeTicketBackend(clock=clock)


async def test_ticket_is_hashed_scoped_and_single_use(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    store = RealtimeTicketStore(backend, clock=clock)
    key_a = TenantSessionKey("tenant-a", "ABC12345")
    key_b = TenantSessionKey("tenant-b", "ABC12345")

    issued = await store.issue(key_a, "websocket", ttl_seconds=60)

    stored = "".join(backend.values) + "".join(value for value, _ in backend.values.values())
    assert issued.ticket not in stored
    assert issued.expires_at == clock() + timedelta(seconds=60)
    assert await store.consume(issued.ticket, key_b, "websocket") is False
    assert await store.consume(issued.ticket, key_a, "websocket") is False


async def test_ticket_rejects_transport_mismatch_and_replay(
    backend: MemoryRealtimeTicketBackend,
) -> None:
    store = RealtimeTicketStore(backend)
    key = TenantSessionKey("tenant-a", "ABC12345")
    wrong_transport = await store.issue(key, "websocket")
    valid = await store.issue(key, "websocket")

    assert await store.consume(wrong_transport.ticket, key, "polling") is False
    assert await store.consume(valid.ticket, key, "websocket") is True
    assert await store.consume(valid.ticket, key, "websocket") is False


async def test_session_revocation_invalidates_every_outstanding_ticket(
    backend: MemoryRealtimeTicketBackend,
) -> None:
    store = RealtimeTicketStore(backend)
    key = TenantSessionKey("tenant-a", "ABC12345")
    first = await store.issue(key, "websocket")
    second = await store.issue(key, "polling")

    await store.revoke(key)

    assert await store.consume(first.ticket, key, "websocket") is False
    assert await store.consume(second.ticket, key, "polling") is False


async def test_a_repeat_revoke_restarts_the_eight_hour_lifetime(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    store = RealtimeTicketStore(backend, clock=clock)
    key = TenantSessionKey("tenant-a", "ABC12345")
    await store.revoke(key)
    clock.advance(hours=7)

    await store.revoke(key)
    clock.advance(hours=2)

    issued = await store.issue(key, "websocket")
    assert await store.consume(issued.ticket, key, "websocket") is False


async def test_a_backend_failure_is_reported_as_unavailable() -> None:
    class Down:
        async def put_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
            raise ConnectionError("down")

        async def put(self, key: str, value: str, ttl_seconds: int) -> None:
            raise ConnectionError("down")

        async def consume(self, key: str) -> str | None:
            raise ConnectionError("down")

        async def get(self, key: str) -> str | None:
            raise ConnectionError("down")

    store = RealtimeTicketStore(Down())
    key = TenantSessionKey("tenant-a", "ABC12345")

    with pytest.raises(RealtimeTicketUnavailable):
        await store.issue(key, "websocket")
    with pytest.raises(RealtimeTicketUnavailable):
        await store.consume("any-ticket", key, "websocket")
    with pytest.raises(RealtimeTicketUnavailable):
        await store.revoke(key)


@pytest.mark.parametrize(
    "failure",
    [redis.exceptions.ConnectionError("down"), ValueError("corrupt payload")],
    ids=["redis", "corrupt"],
)
async def test_a_redis_failure_or_corrupt_payload_is_unavailable(failure) -> None:
    class Failing:
        async def put_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
            raise failure

        async def put(self, key: str, value: str, ttl_seconds: int) -> None:
            raise failure

        async def consume(self, key: str) -> str | None:
            raise failure

        async def get(self, key: str) -> str | None:
            raise failure

    store = RealtimeTicketStore(Failing())
    key = TenantSessionKey("tenant-a", "ABC12345")

    with pytest.raises(RealtimeTicketUnavailable):
        await store.issue(key, "websocket")
    with pytest.raises(RealtimeTicketUnavailable):
        await store.consume("any-ticket", key, "websocket")


async def test_a_bug_in_a_backend_is_not_disguised_as_an_outage() -> None:
    class Buggy:
        async def put_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
            raise KeyError("bug")

    store = RealtimeTicketStore(Buggy())
    key = TenantSessionKey("tenant-a", "ABC12345")

    with pytest.raises(KeyError):
        await store.issue(key, "websocket")


async def test_memory_consume_is_single_use(backend: MemoryRealtimeTicketBackend) -> None:
    assert await backend.put_if_absent("k", "value", 60) is True

    assert await backend.consume("k") == "value"
    assert await backend.consume("k") is None
    assert await backend.get("k") is None


async def test_memory_get_does_not_consume(backend: MemoryRealtimeTicketBackend) -> None:
    await backend.put("k", "value", 60)

    assert await backend.get("k") == "value"
    assert await backend.consume("k") == "value"


async def test_memory_consume_has_one_winner_among_twenty_tasks(
    backend: MemoryRealtimeTicketBackend,
) -> None:
    await backend.put_if_absent("k", "value", 60)

    results = await asyncio.gather(*(backend.consume("k") for _ in range(20)))

    assert results.count("value") == 1


async def test_memory_values_expire_after_their_lifetime(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    await backend.put_if_absent("ticket", "value", 1)
    await backend.put("revoked", "1", 1)
    clock.advance(milliseconds=999)
    assert await backend.get("ticket") == "value"

    clock.advance(milliseconds=1)

    assert await backend.consume("ticket") is None
    assert await backend.get("revoked") is None


async def test_memory_put_if_absent_keeps_a_live_value(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    assert await backend.put_if_absent("k", "first", 1) is True
    assert await backend.put_if_absent("k", "second", 60) is False
    assert await backend.get("k") == "first"

    clock.advance(seconds=1)

    assert await backend.put_if_absent("k", "third", 60) is True
    assert await backend.get("k") == "third"


async def test_memory_put_overwrites_and_restarts_the_lifetime(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    await backend.put("k", "first", 10)
    clock.advance(seconds=9)

    await backend.put("k", "second", 10)
    clock.advance(seconds=9)

    assert await backend.get("k") == "second"


async def test_the_memory_adapter_never_sees_a_script() -> None:
    assert not hasattr(MemoryRealtimeTicketBackend(), "eval")


class RecordingRedis:
    """Records the calls the Redis adapter makes, returning what redis.asyncio would."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.set_result: bool | None = True
        self.reply: bytes | None = b"value"

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool | None:
        self.calls.append(("set", key, value, ex, nx))
        return self.set_result

    async def eval(self, script: str, number_of_keys: int, key: str) -> bytes | None:
        self.calls.append(("eval", script, number_of_keys, key))
        return self.reply

    async def get(self, key: str) -> bytes | None:
        self.calls.append(("get", key))
        return self.reply


async def test_the_redis_adapter_maps_each_operation_onto_its_command() -> None:
    redis = RecordingRedis()
    backend = RedisRealtimeTicketBackend(redis)

    assert await backend.put_if_absent("ticket", "payload", 60) is True
    await backend.put("revoked", "1", 28800)
    assert await backend.consume("ticket") == "value"
    assert await backend.get("revoked") == "value"

    assert redis.calls == [
        ("set", "ticket", "payload", 60, True),
        ("set", "revoked", "1", 28800, False),
        ("eval", CONSUME_TICKET_LUA, 1, "ticket"),
        ("get", "revoked"),
    ]


async def test_the_redis_adapter_returns_str_and_bool() -> None:
    redis = RecordingRedis()
    redis.set_result = None
    backend = RedisRealtimeTicketBackend(redis)

    assert await backend.put_if_absent("ticket", "payload", 60) is False
    assert isinstance(await backend.consume("ticket"), str)
    assert isinstance(await backend.get("ticket"), str)
    redis.reply = None
    assert await backend.consume("ticket") is None
    assert await backend.get("ticket") is None
