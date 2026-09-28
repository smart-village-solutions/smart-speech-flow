"""Single-use, scoped realtime capability tickets.

The backend contract cases here are the same ones
tests/integration/test_realtime_ticket_redis.py runs against a real Redis, so
the memory adapter and the Redis adapter are held to one contract.
"""

import threading
from datetime import datetime, timedelta, timezone

import pytest

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


def test_ticket_is_hashed_scoped_and_single_use(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    store = RealtimeTicketStore(backend, clock=clock)
    key_a = TenantSessionKey("tenant-a", "ABC12345")
    key_b = TenantSessionKey("tenant-b", "ABC12345")

    issued = store.issue(key_a, "websocket", ttl_seconds=60)

    stored = "".join(backend.values) + "".join(value for value, _ in backend.values.values())
    assert issued.ticket not in stored
    assert issued.expires_at == clock() + timedelta(seconds=60)
    assert store.consume(issued.ticket, key_b, "websocket") is False
    assert store.consume(issued.ticket, key_a, "websocket") is False


def test_ticket_rejects_transport_mismatch_and_replay(
    backend: MemoryRealtimeTicketBackend,
) -> None:
    store = RealtimeTicketStore(backend)
    key = TenantSessionKey("tenant-a", "ABC12345")
    wrong_transport = store.issue(key, "websocket")
    valid = store.issue(key, "websocket")

    assert store.consume(wrong_transport.ticket, key, "polling") is False
    assert store.consume(valid.ticket, key, "websocket") is True
    assert store.consume(valid.ticket, key, "websocket") is False


def test_session_revocation_invalidates_every_outstanding_ticket(
    backend: MemoryRealtimeTicketBackend,
) -> None:
    store = RealtimeTicketStore(backend)
    key = TenantSessionKey("tenant-a", "ABC12345")
    first = store.issue(key, "websocket")
    second = store.issue(key, "polling")

    store.revoke(key)

    assert store.consume(first.ticket, key, "websocket") is False
    assert store.consume(second.ticket, key, "polling") is False


def test_a_repeat_revoke_restarts_the_eight_hour_lifetime(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    store = RealtimeTicketStore(backend, clock=clock)
    key = TenantSessionKey("tenant-a", "ABC12345")
    store.revoke(key)
    clock.advance(hours=7)

    store.revoke(key)
    clock.advance(hours=2)

    issued = store.issue(key, "websocket")
    assert store.consume(issued.ticket, key, "websocket") is False


def test_a_backend_failure_is_reported_as_unavailable() -> None:
    class Down:
        def put_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
            raise ConnectionError("down")

        def put(self, key: str, value: str, ttl_seconds: int) -> None:
            raise ConnectionError("down")

        def consume(self, key: str) -> str | None:
            raise ConnectionError("down")

        def get(self, key: str) -> str | None:
            raise ConnectionError("down")

    store = RealtimeTicketStore(Down())
    key = TenantSessionKey("tenant-a", "ABC12345")

    with pytest.raises(RealtimeTicketUnavailable):
        store.issue(key, "websocket")
    with pytest.raises(RealtimeTicketUnavailable):
        store.consume("any-ticket", key, "websocket")
    with pytest.raises(RealtimeTicketUnavailable):
        store.revoke(key)


def test_memory_consume_is_single_use(backend: MemoryRealtimeTicketBackend) -> None:
    assert backend.put_if_absent("k", "value", 60) is True

    assert backend.consume("k") == "value"
    assert backend.consume("k") is None
    assert backend.get("k") is None


def test_memory_get_does_not_consume(backend: MemoryRealtimeTicketBackend) -> None:
    backend.put("k", "value", 60)

    assert backend.get("k") == "value"
    assert backend.consume("k") == "value"


def test_memory_consume_has_one_winner_among_twenty_threads(
    backend: MemoryRealtimeTicketBackend,
) -> None:
    backend.put_if_absent("k", "value", 60)
    contenders = 20
    start = threading.Barrier(contenders)
    results: list[str | None] = []
    results_lock = threading.Lock()

    def contend() -> None:
        start.wait()
        outcome = backend.consume("k")
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=contend) for _ in range(contenders)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == contenders
    assert results.count("value") == 1


def test_memory_values_expire_after_their_lifetime(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    backend.put_if_absent("ticket", "value", 1)
    backend.put("revoked", "1", 1)
    clock.advance(milliseconds=999)
    assert backend.get("ticket") == "value"

    clock.advance(milliseconds=1)

    assert backend.consume("ticket") is None
    assert backend.get("revoked") is None


def test_memory_put_if_absent_keeps_a_live_value(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    assert backend.put_if_absent("k", "first", 1) is True
    assert backend.put_if_absent("k", "second", 60) is False
    assert backend.get("k") == "first"

    clock.advance(seconds=1)

    assert backend.put_if_absent("k", "third", 60) is True
    assert backend.get("k") == "third"


def test_memory_put_overwrites_and_restarts_the_lifetime(
    backend: MemoryRealtimeTicketBackend, clock: Clock
) -> None:
    backend.put("k", "first", 10)
    clock.advance(seconds=9)

    backend.put("k", "second", 10)
    clock.advance(seconds=9)

    assert backend.get("k") == "second"


def test_the_memory_adapter_never_sees_a_script() -> None:
    assert not hasattr(MemoryRealtimeTicketBackend(), "eval")


class RecordingRedis:
    """Records the calls the Redis adapter makes, returning what redis-py would."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.set_result: bool | None = True
        self.reply: bytes | None = b"value"

    def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool | None:
        self.calls.append(("set", key, value, ex, nx))
        return self.set_result

    def eval(self, script: str, number_of_keys: int, key: str) -> bytes | None:
        self.calls.append(("eval", script, number_of_keys, key))
        return self.reply

    def get(self, key: str) -> bytes | None:
        self.calls.append(("get", key))
        return self.reply


def test_the_redis_adapter_maps_each_operation_onto_its_command() -> None:
    redis = RecordingRedis()
    backend = RedisRealtimeTicketBackend(redis)

    assert backend.put_if_absent("ticket", "payload", 60) is True
    backend.put("revoked", "1", 28800)
    assert backend.consume("ticket") == "value"
    assert backend.get("revoked") == "value"

    assert redis.calls == [
        ("set", "ticket", "payload", 60, True),
        ("set", "revoked", "1", 28800, False),
        ("eval", CONSUME_TICKET_LUA, 1, "ticket"),
        ("get", "revoked"),
    ]


def test_the_redis_adapter_returns_str_and_bool() -> None:
    redis = RecordingRedis()
    redis.set_result = None
    backend = RedisRealtimeTicketBackend(redis)

    assert backend.put_if_absent("ticket", "payload", 60) is False
    assert isinstance(backend.consume("ticket"), str)
    assert isinstance(backend.get("ticket"), str)
    redis.reply = None
    assert backend.consume("ticket") is None
    assert backend.get("ticket") is None
