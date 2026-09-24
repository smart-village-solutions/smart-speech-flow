"""Behavioral gaps around session state extraction and index validation."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.session_manager import (
    ClientType,
    SessionManager,
    SessionStatus,
)
from services.api_gateway.session_store import (
    MemoryTenantSessionStore,
    RedisTenantSessionStore,
    SessionStoreConsistencyError,
    join_key,
    session_key,
    tenant_active_sessions_key,
)
from services.api_gateway.tenant_session import TenantSessionKey
from services.api_gateway.websocket_polling_routes import TenantPollingStore
from tests.test_tenant_session_store import RecordingRedis, make_session

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


class IndexedRedis(RecordingRedis):
    """Redis read boundary with configurable encoded index members."""

    def __init__(self, active_key, member):
        super().__init__()
        self.active_key = active_key
        self.member = member

    def scan_iter(self, *, match):
        assert match == "ssf:v2:tenant:*:active-admin"
        return iter([self.active_key])

    def smembers(self, key):
        return {self.member}


@pytest.mark.parametrize("encoded", [False, True])
def test_active_index_decodes_members_without_losing_tenant_scope(encoded):
    session = make_session("tenant-a", "SESSION1")
    active = tenant_active_sessions_key("ssf", "tenant-a")
    redis = IndexedRedis(
        active.encode() if encoded else active, b"SESSION1" if encoded else "SESSION1"
    )
    store = RedisTenantSessionStore(redis)
    redis.set(session_key("ssf", session.key), store._session_payload(session))
    redis.set(
        join_key("ssf", session.id),
        json.dumps(
            {
                "active": True,
                "tenant_id": "tenant-a",
                "session_id": "SESSION1",
            }
        ),
    )

    loaded = store.list_active()

    assert [item.key for item in loaded] == [TenantSessionKey("tenant-a", "SESSION1")]
    assert loaded[0].status is SessionStatus.PENDING


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "json",
        "fields",
        "session-id",
        "tenant-id",
        "join",
        "terminated",
    ],
)
def test_active_index_rejects_corrupt_records_instead_of_rehydrating_them(corruption):
    session = make_session("tenant-a", "SESSION1")
    active = tenant_active_sessions_key("ssf", "tenant-a")
    redis = IndexedRedis(active, "SESSION1")
    store = RedisTenantSessionStore(redis)
    payload = session.to_dict(include_messages=True)
    if corruption == "session-id":
        payload["id"] = "SESSION2"
    if corruption == "tenant-id":
        payload["tenant_id"] = "tenant-b"
    if corruption == "terminated":
        payload["status"] = "terminated"
    raw = {"json": "{", "fields": "{}"}.get(corruption, json.dumps(payload))
    if corruption != "missing":
        redis.set(session_key("ssf", session.key), raw)
    redis.set(
        join_key("ssf", session.id),
        (
            "{"
            if corruption == "join"
            else json.dumps(
                {
                    "active": corruption != "terminated",
                    "tenant_id": "tenant-a",
                    "session_id": "SESSION1",
                }
            )
        ),
    )

    with pytest.raises(SessionStoreConsistencyError) as failure:
        store.list_active()

    assert str(failure.value) == "active session index does not match session"
    assert failure.value.__cause__ is None


@pytest.mark.parametrize("raw", ["{", "{}", "[]", '{"active": "yes"}'])
def test_malformed_join_cannot_resolve_a_customer_session(raw):
    redis = RecordingRedis()
    redis.set(join_key("ssf", "SESSION1"), raw)

    assert RedisTenantSessionStore(redis).resolve_join("SESSION1") is None


def test_malformed_session_is_quarantined_instead_of_loaded():
    redis = RecordingRedis()
    key = TenantSessionKey("tenant-a", "SESSION1")
    redis.set(session_key("ssf", key), "{")

    assert RedisTenantSessionStore(redis).load(key) is None


def test_tenant_active_lookup_rejects_ambiguity_and_excludes_other_tenants():
    store = MemoryTenantSessionStore()
    manager = SessionManager(store=store)
    first = make_session("tenant-a", "SESSION1")
    second = make_session("tenant-a", "SESSION2")
    foreign = make_session("tenant-b", "SESSION3")
    for session in (first, second, foreign):
        assert store.create(session)

    with pytest.raises(ValueError) as failure:
        manager.get_active_session(tenant_id="tenant-a")

    assert str(failure.value) == (
        "Mehrere aktive Sessions vorhanden; explizite session_id erforderlich"
    )
    selected = manager.get_active_session("SESSION2", tenant_id="tenant-a")
    assert selected["id"] == "SESSION2"
    assert "tenant_id" not in selected
    assert "runtime_configuration" not in selected
    assert manager.get_active_session("SESSION3", tenant_id="tenant-a") is None
    first.status = second.status = SessionStatus.TERMINATED
    assert manager.get_active_session(tenant_id="tenant-a") is None
    manager.store = None
    assert manager.get_active_session(tenant_id="tenant-a") is None


async def test_unknown_expired_polling_client_does_not_prevent_customer_disconnect():
    store = MemoryTenantSessionStore()
    manager = SessionManager(store=store, clock=lambda: NOW)
    session = make_session("tenant-a", "SESSION1")
    session.created_at = NOW
    assert store.create(session)
    manager.customer_connected(session.key)
    tick = 0.0
    polling = TenantPollingStore(clock=lambda: tick)
    polling.activate(TenantSessionKey("tenant-a", "MISSING1"), ClientType.ADMIN)
    polling.activate(session.key, ClientType.CUSTOMER)
    manager.attach_realtime(None, polling)
    tick = 1000.0

    await manager.check_session_timeouts()

    assert session.customer_connection_count == 0
    assert session.customer_connected is False
    assert session.status is SessionStatus.PENDING


def test_sweep_preserves_snapshot_when_store_adds_session_during_write(monkeypatch):
    from services.api_gateway.session_manager import SessionMessage

    store = MemoryTenantSessionStore()
    manager = SessionManager(store=store)
    first = make_session("tenant-a", "SESSION1")
    second = make_session("tenant-b", "SESSION2")
    for session in (first, second):
        session.created_at = NOW - timedelta(hours=25)
        session.messages = [
            SessionMessage(
                id="m1",
                sender=ClientType.ADMIN,
                original_text="old",
                translated_text="old",
                audio_base64=None,
                source_lang="de",
                target_lang="en",
                timestamp=NOW - timedelta(hours=25),
                record_authorized=True,
            )
        ]
        assert store.create(session)
        manager.sessions[session.key] = session
    original_save = store.save

    def save_and_add(session):
        original_save(session)
        added = make_session("tenant-c", "SESSION3")
        manager.sessions[added.key] = added

    monkeypatch.setattr(store, "save", save_and_add)
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "24")

    assert manager.sweep_expired_content(NOW) == {
        "refused_removed": 0,
        "expired_removed": 2,
    }
    assert first.messages == second.messages == []
    assert len(manager.sessions) == 3
