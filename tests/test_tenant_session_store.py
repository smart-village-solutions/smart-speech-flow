"""Tenant-scoped session persistence contract tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

from services.api_gateway.session_manager import (
    ClientType,
    Session,
    SessionMessage,
    SessionStatus,
)
from services.api_gateway.tenant_session import (
    RuntimeConfigurationSnapshot,
    TenantSessionKey,
)
from services.api_gateway.session_store import (
    MemoryTenantSessionStore,
    RedisTenantSessionStore,
    join_key,
    session_key,
    tenant_active_sessions_key,
    tenant_sessions_key,
)

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")
TERMINATED_AT = datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc)


def make_session(tenant_id: str, session_id: str) -> Session:
    return Session(
        id=session_id,
        tenant_id=tenant_id,
        runtime_configuration=SNAPSHOT,
    )


def test_v2_keys_include_encoded_tenant() -> None:
    key = TenantSessionKey("tenant-a", "ABC12345")

    assert session_key("ssf", key) == "ssf:v2:tenant:dGVuYW50LWE:session:ABC12345"
    assert tenant_sessions_key("ssf", "tenant-a") == ("ssf:v2:tenant:dGVuYW50LWE:sessions")
    assert tenant_active_sessions_key("ssf", "tenant-a") == (
        "ssf:v2:tenant:dGVuYW50LWE:active-admin"
    )
    assert join_key("ssf", "ABC12345") == "ssf:v2:join:ABC12345"


def test_memory_store_refuses_global_join_collision_and_retains_tombstone() -> None:
    store = MemoryTenantSessionStore()
    session_a = make_session("tenant-a", "ABC12345")
    session_b = make_session("tenant-b", "ABC12345")

    assert store.create(session_a) is True
    assert store.create(session_b) is False

    session_a.status = SessionStatus.TERMINATED
    store.terminate(session_a)

    assert store.resolve_join(session_a.id) is None
    assert store.load(session_a.key) == session_a
    assert store.create(session_b) is False
    assert store.list_for_tenant("tenant-b") == []


def test_memory_store_fails_closed_for_mismatched_session_payload() -> None:
    store = MemoryTenantSessionStore()
    session = make_session("tenant-a", "ABC12345")
    assert store.create(session) is True

    store._sessions[session.key] = replace(session, tenant_id="tenant-b")

    assert store.load(session.key) is None
    assert store.resolve_join(session.id) is None


class RecordingRedis:
    def __init__(self, eval_result: int = 1) -> None:
        self.eval_result = eval_result
        self.eval_calls: list[tuple[object, ...]] = []
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def eval(self, *arguments: object) -> int:
        self.eval_calls.append(arguments)
        return self.eval_result

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def smembers(self, key: str) -> set[str]:
        return self.sets.get(key, set())


def test_redis_create_is_one_atomic_script_with_exact_v2_keys() -> None:
    redis = RecordingRedis()
    store = RedisTenantSessionStore(redis, namespace="ssf")
    session = make_session("tenant-a", "ABC12345")

    assert store.create(session) is True

    call = redis.eval_calls[0]
    assert call[1] == 4
    assert call[2:6] == (
        session_key("ssf", session.key),
        tenant_sessions_key("ssf", "tenant-a"),
        join_key("ssf", "ABC12345"),
        tenant_active_sessions_key("ssf", "tenant-a"),
    )
    assert json.loads(call[8])["active"] is True


def test_redis_session_payload_never_contains_audio_bytes() -> None:
    session = make_session("tenant-a", "ABC12345")
    session.messages.append(
        SessionMessage(
            id="message-1",
            sender=ClientType.ADMIN,
            original_text="Hallo",
            translated_text="Hello",
            audio_base64="UklGRnNlbnNpdGl2ZS1hdWRpbw==",
            source_lang="de",
            target_lang="en",
            timestamp=datetime.now(timezone.utc),
        )
    )

    payload = RedisTenantSessionStore._session_payload(session)

    assert "audio_base64" not in payload
    assert "UklGRnNlbnNpdGl2ZS1hdWRpbw==" not in payload


def test_redis_terminate_updates_tombstone_in_one_atomic_script() -> None:
    redis = RecordingRedis()
    store = RedisTenantSessionStore(redis, namespace="ssf")
    session = make_session("tenant-a", "ABC12345")
    session.status = SessionStatus.TERMINATED

    store.terminate(session)

    call = redis.eval_calls[0]
    assert call[1] == 3
    assert call[2:5] == (
        session_key("ssf", session.key),
        tenant_active_sessions_key("ssf", "tenant-a"),
        join_key("ssf", "ABC12345"),
    )
    # ARGV: payload, session_id, join_active, join_inactive, tenant_id, ttl
    assert json.loads(call[8])["active"] is False
    assert call[9] == "tenant-a"


def apply_terminate_script(redis: RecordingRedis, call: tuple[object, ...]) -> None:
    """Write what TERMINATE_SESSION_LUA's success branch writes.

    RecordingRedis has no Lua interpreter, so the tombstone the store reads
    back has to be seeded from the script's own arguments rather than a
    hand-written copy that could drift from it: the session record under
    KEYS[1], and the revoked join payload -- ARGV[4] -- under KEYS[3].
    """
    redis.set(str(call[2]), str(call[5]))
    redis.set(str(call[4]), str(call[8]))


def active_join_payload(tenant_id: str, session_id: str) -> str:
    return json.dumps(
        {"active": True, "session_id": session_id, "tenant_id": tenant_id},
        sort_keys=True,
        separators=(",", ":"),
    )


def terminated_redis_store(tenant_id: str, session_id: str):
    """A store whose one session has been terminated the way the script does it.

    The live state is seeded first. TERMINATE_SESSION_LUA reads the join key
    and returns 0 unless it holds the active payload, so terminating against an
    empty keyspace is a state real Redis would refuse -- RecordingRedis accepts
    it only because its eval is canned, which would leave the Redis half of
    these tests resting on a termination that cannot happen.
    """
    redis = RecordingRedis()
    store = RedisTenantSessionStore(redis, namespace="ssf")
    session = make_session(tenant_id, session_id)
    live_join = active_join_payload(tenant_id, session_id)
    redis.set(session_key("ssf", session.key), store._session_payload(session))
    redis.set(join_key("ssf", session_id), live_join)

    session.status = SessionStatus.TERMINATED
    session.terminated_at = TERMINATED_AT
    store.terminate(session)

    # ARGV[3] is the value the script compares the stored join against; if the
    # seed above ever stops matching it, this fixture is fiction.
    assert redis.eval_calls[0][7] == live_join
    apply_terminate_script(redis, redis.eval_calls[0])
    return store, redis, session


class TestEndedJoinResolution:
    """The narrow tombstone reader the feedback path uses (#324).

    `resolve_ended_join` is the mirror of `resolve_join`: it answers only for a
    join the store has already revoked, and only when the record behind it
    loads as terminated. Neither answers for what the other does, so nothing
    that resolves a live session can reach an ended one, and -- the point of
    the pair -- nothing that reaches an ended one can rejoin or observe it.
    """

    def test_memory_store_does_not_resolve_a_live_join(self) -> None:
        store = MemoryTenantSessionStore()
        session = make_session("tenant-a", "ABC12345")
        assert store.create(session) is True

        assert store.resolve_join(session.id) == session.key
        assert store.resolve_ended_join(session.id) is None

    def test_memory_store_resolves_a_revoked_join_to_its_key(self) -> None:
        store = MemoryTenantSessionStore()
        session = make_session("tenant-a", "ABC12345")
        store.create(session)
        session.status = SessionStatus.TERMINATED
        session.terminated_at = TERMINATED_AT
        store.terminate(session)

        assert store.resolve_ended_join(session.id) == (session.key, TERMINATED_AT)

    def test_memory_store_does_not_resolve_an_unknown_id(self) -> None:
        store = MemoryTenantSessionStore()

        assert store.resolve_ended_join("NOSUCH99") is None

    def test_memory_store_fails_closed_on_a_mismatched_record(self) -> None:
        store = MemoryTenantSessionStore()
        session = make_session("tenant-a", "ABC12345")
        store.create(session)
        session.status = SessionStatus.TERMINATED
        session.terminated_at = TERMINATED_AT
        store.terminate(session)

        store._sessions[session.key] = replace(session, tenant_id="tenant-b")

        assert store.resolve_ended_join(session.id) is None

    def test_redis_store_does_not_resolve_a_live_join(self) -> None:
        redis = RecordingRedis()
        store = RedisTenantSessionStore(redis, namespace="ssf")
        session = make_session("tenant-a", "ABC12345")
        redis.set(session_key("ssf", session.key), store._session_payload(session))
        redis.set(join_key("ssf", session.id), active_join_payload("tenant-a", session.id))

        assert store.resolve_join(session.id) == session.key
        assert store.resolve_ended_join(session.id) is None

    def test_redis_store_resolves_a_revoked_join_to_its_key(self) -> None:
        store, _redis, session = terminated_redis_store("tenant-a", "ABC12345")

        assert store.resolve_ended_join(session.id) == (session.key, TERMINATED_AT)

    def test_redis_store_does_not_resolve_an_unknown_id(self) -> None:
        store = RedisTenantSessionStore(RecordingRedis(), namespace="ssf")

        assert store.resolve_ended_join("NOSUCH99") is None

    def test_redis_store_fails_closed_on_a_mismatched_record(self) -> None:
        store, redis, session = terminated_redis_store("tenant-a", "ABC12345")
        redis.set(
            session_key("ssf", session.key),
            store._session_payload(replace(session, tenant_id="tenant-b")),
        )

        assert store.resolve_ended_join(session.id) is None

    def test_a_revoked_join_still_cannot_be_rejoined_in_either_store(self) -> None:
        """Criterion 3 of #324, stated as a test rather than a claim.

        Both stores must keep answering `None` from `resolve_join` for exactly
        the id `resolve_ended_join` now answers for. This is the test that
        fails if a later change tries to satisfy feedback by reactivating the
        join instead of reading the tombstone.
        """
        memory = MemoryTenantSessionStore()
        session = make_session("tenant-a", "ABC12345")
        memory.create(session)
        session.status = SessionStatus.TERMINATED
        session.terminated_at = TERMINATED_AT
        memory.terminate(session)
        redis_store, _redis, redis_session = terminated_redis_store("tenant-a", "ABC12345")

        for store, ended in ((memory, session), (redis_store, redis_session)):
            assert store.resolve_ended_join(ended.id) == (ended.key, TERMINATED_AT)
            assert store.resolve_join(ended.id) is None


def test_terminating_expires_the_record_after_the_retention_period(monkeypatch) -> None:
    """The terminal record is immutable, so retention is an expiry, not a prune.

    Nothing else can remove it: the save script refuses every change to a
    terminated record, and there is no purge job.
    """
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "24")
    redis = RecordingRedis()
    store = RedisTenantSessionStore(redis, namespace="ssf")
    session = make_session("tenant-a", "ABC12345")
    session.status = SessionStatus.TERMINATED

    store.terminate(session)

    call = redis.eval_calls[-1]
    assert call[0].count("EXPIRE") == 1
    assert call[10] == 24 * 3600


def test_zero_retention_never_expires_the_record(monkeypatch) -> None:
    # Zero disables automatic deletion; it must not mean "expire immediately".
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "0")
    redis = RecordingRedis()
    store = RedisTenantSessionStore(redis, namespace="ssf")
    session = make_session("tenant-a", "ABC12345")
    session.status = SessionStatus.TERMINATED

    store.terminate(session)

    assert redis.eval_calls[-1][10] == 0


def test_an_expired_terminal_record_is_gone(monkeypatch) -> None:
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "24")
    store = MemoryTenantSessionStore()
    session = make_session("tenant-a", "ABC12345")
    assert store.create(session) is True
    session.status = SessionStatus.TERMINATED
    store.terminate(session)

    assert store.load(session.key) is not None
    store.expire_now(session.key)
    assert store.load(session.key) is None


def test_the_join_tombstone_outlives_the_expired_record(monkeypatch) -> None:
    # The tombstone carries no conversation content and is what stops a
    # session identifier being reused, so it must not expire with the record.
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "24")
    store = MemoryTenantSessionStore()
    session = make_session("tenant-a", "ABC12345")
    assert store.create(session) is True
    session.status = SessionStatus.TERMINATED
    store.terminate(session)
    store.expire_now(session.key)

    assert store.load(session.key) is None
    assert store.create(make_session("tenant-a", "ABC12345")) is False
