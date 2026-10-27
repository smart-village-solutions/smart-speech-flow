"""The recording state survives in Redis, and only recording conversations are indexed."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.api_gateway.recording import session_state as rs
from services.api_gateway.recording.session_state import Phase, RecordingState
from services.api_gateway.recording.session_store import (
    STATE_TTL_SECONDS,
    MemoryRecordingStateStore,
    RedisRecordingStateStore,
)
from services.api_gateway.tenant_session import TenantSessionKey

KEY = TenantSessionKey("tenant-kassel", "ABCD1234")
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


class FakePipeline:
    """Queues commands and applies them together, or none if `fail` is set."""

    def __init__(self, redis: "FakeRedis", transaction: bool) -> None:
        self.redis, self.transaction, self.queued = redis, transaction, []

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    def set(self, key: str, value: str, ex: int) -> None:
        self.queued.append(("set", key, value, ex))

    def sadd(self, key: str, member: str) -> None:
        self.queued.append(("sadd", key, member))

    def srem(self, key: str, member: str) -> None:
        self.queued.append(("srem", key, member))

    async def execute(self) -> None:
        if self.redis.fail:
            raise ConnectionError("redis went away")
        self.redis.transactions.append((self.transaction, [command[0] for command in self.queued]))
        for name, *args in self.queued:
            await getattr(self.redis, name)(*args)


class FakeRedis:
    """The commands the store uses, answering in bytes as redis-py does by default."""

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.sets: dict[str, set[bytes]] = {}
        self.transactions: list[tuple[bool, list[str]]] = []
        self.fail = False

    def pipeline(self, transaction: bool) -> FakePipeline:
        return FakePipeline(self, transaction)

    async def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    async def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = value.encode()
        self.ttls[key] = ex

    async def sadd(self, key: str, member: str) -> None:
        self.sets.setdefault(key, set()).add(member.encode())

    async def srem(self, key: str, member: str) -> None:
        self.sets.get(key, set()).discard(member.encode())

    async def smembers(self, key: str) -> set[bytes]:
        return set(self.sets.get(key, set()))


def asking() -> RecordingState:
    return rs.request(RecordingState(), request_id="r1", requested_by="emp", now=T0)


@pytest.fixture(params=["memory", "redis"])
def store(request):
    if request.param == "memory":
        return MemoryRecordingStateStore()
    return RedisRecordingStateStore(FakeRedis(), namespace="ssf")


async def test_an_unknown_conversation_is_off(store) -> None:
    assert await store.load(KEY) == RecordingState()


async def test_a_state_round_trips_with_every_field(store) -> None:
    state = rs.answer(asking(), request_id="r1", consent=True, window_id="w1", now=T0)
    await store.save(KEY, state)
    assert await store.load(KEY) == state


async def test_only_conversations_that_are_not_off_are_listed(store) -> None:
    await store.save(KEY, asking())
    assert await store.recording_sessions() == [KEY]
    await store.save(KEY, rs.cancel(asking(), request_id="r1", now=T0))
    assert await store.recording_sessions() == []


async def test_redis_keeps_the_state_beside_the_session_for_a_day() -> None:
    redis = FakeRedis()
    await RedisRecordingStateStore(redis, namespace="ssf").save(KEY, asking())
    (key,) = redis.values
    assert key.startswith("ssf:v2:tenant:") and key.endswith(":session:ABCD1234:recording")
    assert redis.ttls[key] == STATE_TTL_SECONDS
    assert (await RedisRecordingStateStore(redis).load(KEY)).phase is Phase.ASKING


async def test_redis_writes_the_state_and_its_index_entry_in_one_transaction() -> None:
    redis = FakeRedis()
    store = RedisRecordingStateStore(redis, namespace="ssf")
    await store.save(KEY, asking())
    assert redis.transactions == [(True, ["set", "sadd"])]
    redis.fail = True
    with pytest.raises(ConnectionError):
        await store.save(KEY, rs.cancel(asking(), request_id="r1", now=T0))
    assert (await store.load(KEY)).phase is Phase.ASKING
    assert await store.recording_sessions() == [KEY]


async def test_touch_restarts_the_expiry() -> None:
    redis = FakeRedis()
    store = RedisRecordingStateStore(redis, namespace="ssf")
    await store.save(KEY, asking())
    (key,) = redis.values
    redis.ttls[key] = 5
    await store.touch(KEY)
    assert redis.ttls[key] == STATE_TTL_SECONDS
