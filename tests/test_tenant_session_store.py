"""Tenant-scoped session persistence contract tests."""

from __future__ import annotations

import json
from dataclasses import replace

from services.api_gateway.session_manager import Session, SessionStatus
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
    assert json.loads(call[-2])["active"] is False
    assert call[-1] == "tenant-a"
