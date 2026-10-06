"""What the async session store and manager guarantee when handlers interleave (#428).

With a synchronous store every session read and write ran to completion before
another handler could start. Once they await, two handlers can be inside the
same session at once; these tests pin what must still hold.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.clock import utc_now
from services.api_gateway.session_manager import TenantSessionManager
from services.api_gateway.session_models import ClientType, Session, SessionMessage
from services.api_gateway.session_store import (
    MemoryTenantSessionStore,
    RedisTenantSessionStore,
    SessionStoreConsistencyError,
    join_key,
    session_key,
    tenant_sessions_key,
)
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey
from services.api_gateway.websocket import WebSocketManager
from tests.realtime_sessions import websocket_monitor
from tests.test_tenant_persistence_lifespan import PersistentFakeRedis

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


def make_session(tenant_id: str, session_id: str) -> Session:
    return Session(id=session_id, tenant_id=tenant_id, runtime_configuration=SNAPSHOT)


class SlowFirstEvalRedis:
    """The first EVAL takes longer than the second, as two pool connections may."""

    def __init__(self) -> None:
        self.saved: list[str] = []
        self.calls = 0

    async def eval(self, script: str, numkeys: int, *args: object) -> int:
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(0.05)
        self.saved.append(str(args[numkeys]))
        return 1


async def test_concurrent_saves_leave_the_latest_state() -> None:
    redis = SlowFirstEvalRedis()
    store = RedisTenantSessionStore(redis)
    session = make_session("tenant-a", "ABC12345")
    session.customer_language = "en"
    first = asyncio.create_task(store.save(session))
    await asyncio.sleep(0)
    session.customer_language = "ar"

    await asyncio.gather(first, store.save(session))

    assert json.loads(redis.saved[-1])["customer_language"] == "ar"


async def test_writes_to_different_sessions_do_not_wait_for_each_other() -> None:
    redis = SlowFirstEvalRedis()
    store = RedisTenantSessionStore(redis)
    slow = make_session("tenant-a", "ABC12345")
    fast = make_session("tenant-a", "XYZ98765")

    slow_save = asyncio.create_task(store.save(slow))
    await asyncio.sleep(0)
    await asyncio.wait_for(store.save(fast), 0.04)
    await slow_save

    assert [json.loads(payload)["id"] for payload in redis.saved] == ["XYZ98765", "ABC12345"]


async def test_the_write_locks_are_released_once_no_writer_remains() -> None:
    store = RedisTenantSessionStore(SlowFirstEvalRedis())
    session = make_session("tenant-a", "ABC12345")

    await asyncio.gather(store.save(session), store.save(session), store.create(session))

    assert len(store._write_locks) == 0


class FreshCopyStore(MemoryTenantSessionStore):
    """Loads a new object each time and yields first, as a Redis round trip does."""

    async def load(self, key: TenantSessionKey) -> Session | None:
        await asyncio.sleep(0)
        stored = await super().load(key)
        return None if stored is None else Session.from_dict(stored.to_dict(include_messages=True))


async def test_concurrent_cache_misses_share_one_session(tmp_path: Path) -> None:
    store = FreshCopyStore()
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)
    manager = TenantSessionManager(store=store, audio_store=AudioStore(tmp_path))

    first, second = await asyncio.gather(
        manager.get_session(session.key), manager.get_session(session.key)
    )

    assert first is not None
    assert first is second
    assert manager.sessions[session.key] is first


def _message(message_id: str, *, age: timedelta) -> SessionMessage:
    return SessionMessage(
        id=message_id,
        sender=ClientType.ADMIN,
        original_text="Hallo",
        translated_text="Hello",
        audio_base64=None,
        source_lang="de",
        target_lang="en",
        timestamp=utc_now() - age,
        record_authorized=True,
    )


class SweepSaveFailsStore(MemoryTenantSessionStore):
    """The sweep's save waits for a concurrent append, then fails; other saves succeed."""

    def __init__(self) -> None:
        super().__init__()
        self.sweep_saving = asyncio.Event()
        self.appended = asyncio.Event()
        self.fail_next_save = False

    async def save(self, session: Session) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            self.sweep_saving.set()
            await self.appended.wait()
            raise ConnectionError("redis went away")
        await super().save(session)


async def test_a_failed_sweep_keeps_a_message_appended_while_it_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "24")
    store = SweepSaveFailsStore()
    manager = TenantSessionManager(store=store, audio_store=AudioStore(tmp_path))
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)
    manager.sessions[session.key] = session
    session.messages.append(_message("expired", age=timedelta(hours=30)))

    async def append_during_the_sweep() -> None:
        await store.sweep_saving.wait()
        await manager.add_message(session.key, _message("fresh", age=timedelta(0)))
        store.appended.set()

    store.fail_next_save = True
    appender = asyncio.create_task(append_during_the_sweep())
    counts = await manager.sweep_expired_content(utc_now())
    await appender

    assert counts["failed"] == 1
    assert [message.id for message in session.messages] == ["expired", "fresh"]


class TerminatingBetweenReadsRedis:
    """Commits a termination after the first single-key read, as a concurrent handler could."""

    def __init__(self, session: Session) -> None:
        self.values = {
            session_key("ssf", session.key): RedisTenantSessionStore._session_payload(session),
            join_key("ssf", session.id): json.dumps(
                {"active": True, "session_id": session.id, "tenant_id": session.tenant_id}
            ),
        }
        self.join = join_key("ssf", session.id)
        self.revoked = json.dumps(
            {"active": False, "session_id": session.id, "tenant_id": session.tenant_id}
        )

    async def get(self, key: str) -> str | None:
        value = self.values.get(key)
        self.values[self.join] = self.revoked
        return value

    async def mget(self, *keys: str) -> list[str | None]:
        return [self.values.get(key) for key in keys]


async def test_a_load_reads_the_record_and_its_join_as_one_snapshot() -> None:
    session = make_session("tenant-a", "ABC12345")
    store = RedisTenantSessionStore(TerminatingBetweenReadsRedis(session))

    assert await store.load(session.key) == session


class SuspendingStore(MemoryTenantSessionStore):
    """Suspends around lists and terminations, as Redis round trips do.

    A listing reads first and answers later, as Redis does: the server reads at
    once and the reply arrives after the loop has run other handlers.
    """

    async def list_for_tenant(self, tenant_id: str) -> list[Session]:
        listed = await super().list_for_tenant(tenant_id)
        await asyncio.sleep(0)
        return listed

    async def terminate(self, session: Session) -> Session:
        await asyncio.sleep(0)
        return await super().terminate(session)


class LifecycleRecorder:
    def __init__(self) -> None:
        self.phases: list[str] = []

    def emit_session_lifecycle(self, **fields: object) -> None:
        self.phases.append(str(fields["phase"]))


async def test_concurrent_terminations_commit_and_report_once(tmp_path: Path) -> None:
    manager = TenantSessionManager(store=SuspendingStore(), audio_store=AudioStore(tmp_path))
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    recorder = LifecycleRecorder()
    manager.attach_quality_telemetry(recorder)

    await asyncio.gather(
        manager.terminate_session(session.key, "session_timeout"),
        manager.terminate_session(session.key, "manual_admin_termination"),
    )

    assert len(recorder.phases) == 1
    assert session.termination_reason == "session_timeout"


async def test_one_admins_concurrent_creates_leave_one_live_session(tmp_path: Path) -> None:
    manager = TenantSessionManager(store=SuspendingStore(), audio_store=AudioStore(tmp_path))

    await asyncio.gather(
        manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref="owner-1"),
        manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref="owner-1"),
    )

    live = await manager.get_active_sessions(tenant_id="tenant-a", owner_ref="owner-1")
    assert len(live) == 1
    assert len(manager._creation_locks) == 0


class StalledCreateStore(SuspendingStore):
    """One owner's create stalls in the store until released."""

    def __init__(self, stalled_owner: str) -> None:
        super().__init__()
        self.stalled_owner = stalled_owner
        self.release = asyncio.Event()

    async def create(self, session: Session) -> bool:
        if session.owner_ref == self.stalled_owner:
            await self.release.wait()
        return await super().create(session)


async def test_different_admins_create_without_waiting_for_each_other(tmp_path: Path) -> None:
    store = StalledCreateStore("owner-1")
    manager = TenantSessionManager(store=store, audio_store=AudioStore(tmp_path))
    stalled = asyncio.create_task(
        manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref="owner-1")
    )
    for _ in range(5):
        await asyncio.sleep(0)

    created = await asyncio.wait_for(
        manager.create_admin_session("tenant-a", SNAPSHOT, owner_ref="owner-2"), 1
    )
    store.release.set()
    await stalled

    assert created.owner_ref == "owner-2"


async def test_a_failed_sweep_does_not_restore_content_onto_a_terminated_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "24")
    store = SweepSaveFailsStore()
    manager = TenantSessionManager(store=store, audio_store=AudioStore(tmp_path))
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    session.messages.append(_message("expired", age=timedelta(hours=30)))

    async def terminate_during_the_sweep() -> None:
        await store.sweep_saving.wait()
        await manager.terminate_session(session.key, "manual_admin_termination")
        store.appended.set()

    store.fail_next_save = True
    terminator = asyncio.create_task(terminate_during_the_sweep())
    await manager.sweep_expired_content(utc_now())
    await terminator

    assert session.status.value == "terminated"
    assert session.messages == []


async def test_a_failed_sweep_keeps_an_authorization_recorded_while_it_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "24")
    store = SweepSaveFailsStore()
    manager = TenantSessionManager(store=store, audio_store=AudioStore(tmp_path))
    session = make_session("tenant-a", "ABC12345")
    await store.create(session)
    manager.sessions[session.key] = session
    session.messages.append(_message("expired", age=timedelta(hours=30)))
    pending = _message("pending", age=timedelta(0))
    pending.record_authorized = False
    session.messages.append(pending)

    async def authorize_during_the_sweep() -> None:
        await store.sweep_saving.wait()
        await manager.record_message_authorization(
            session.key, "pending", record=True, original_audio=True, translated_audio=False
        )
        store.appended.set()

    store.fail_next_save = True
    authorizer = asyncio.create_task(authorize_during_the_sweep())
    await manager.sweep_expired_content(utc_now())
    await authorizer

    restored = {message.id: message for message in session.messages}
    assert list(restored) == ["expired", "pending"]
    assert restored["pending"].record_authorized is True
    assert restored["pending"].original_audio_authorized is True


class CountingRedis:
    """Serves stored values and counts the round trips the store makes."""

    def __init__(self, values: dict[str, str], members: dict[str, set[str]]) -> None:
        self.values = values
        self.members = members
        self.round_trips: list[str] = []

    async def smembers(self, key: str) -> set[str]:
        self.round_trips.append("smembers")
        return self.members.get(key, set())

    async def mget(self, *keys: str) -> list[str | None]:
        self.round_trips.append("mget")
        return [self.values.get(key) for key in keys]


async def test_a_tenant_listing_reads_every_record_in_one_round_trip() -> None:
    sessions = [make_session("tenant-a", f"SESSION{index}") for index in range(5)]
    values: dict[str, str] = {}
    for session in sessions:
        values[session_key("ssf", session.key)] = RedisTenantSessionStore._session_payload(session)
        values[join_key("ssf", session.id)] = json.dumps(
            {"active": True, "session_id": session.id, "tenant_id": "tenant-a"}
        )
    values[session_key("ssf", sessions[0].key)] = "{not json"
    redis = CountingRedis(
        values, {tenant_sessions_key("ssf", "tenant-a"): {session.id for session in sessions}}
    )

    listed = await RedisTenantSessionStore(redis).list_for_tenant("tenant-a")

    assert redis.round_trips == ["smembers", "mget"]
    assert sorted(session.id for session in listed) == [f"SESSION{index}" for index in range(1, 5)]


class HeldTerminationRedis(PersistentFakeRedis):
    """The Lua-faithful fake, holding a termination script until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.release_termination = asyncio.Event()

    async def eval(self, script, number_of_keys, *values):
        if number_of_keys == 3 and str(values[1]).endswith(":active-admin"):
            await self.release_termination.wait()
        return await super().eval(script, number_of_keys, *values)


def _message_now(message_id: str) -> SessionMessage:
    return _message(message_id, age=timedelta(0))


CHANGES_REFUSED_AFTER_TERMINATION = {
    "admin_connected": (lambda manager, key: manager.admin_connected(key), KeyError),
    "customer_connected": (lambda manager, key: manager.customer_connected(key), KeyError),
    "activate_session": (lambda manager, key: manager.activate_session(key, "en"), ValueError),
    "add_message": (
        lambda manager, key: manager.add_message(key, _message_now("late")),
        SessionStoreConsistencyError,
    ),
}


@pytest.mark.parametrize("change", sorted(CHANGES_REFUSED_AFTER_TERMINATION))
async def test_a_change_waiting_behind_a_termination_is_refused(
    change: str, tmp_path: Path
) -> None:
    """The termination holds the write lock while the change waits for it.

    The waiting save then carries the terminal record the termination copied
    onto the cached session, which the store accepts unchanged, so the change
    itself is lost. It must fail as the change would have failed had the
    termination come first, not report success.
    """
    redis = HeldTerminationRedis()
    store = RedisTenantSessionStore(redis)
    manager = TenantSessionManager(store=store, audio_store=AudioStore(tmp_path))
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    recorder = LifecycleRecorder()
    manager.attach_quality_telemetry(recorder)
    apply, refusal = CHANGES_REFUSED_AFTER_TERMINATION[change]

    terminating = asyncio.create_task(manager.terminate_session(session.key, "manual"))
    changing = asyncio.create_task(apply(manager, session.key))
    for _ in range(10):
        await asyncio.sleep(0)
    entry = store._write_locks._entries[session.key]
    assert entry.holders == 2, "the change must be waiting behind the termination"
    redis.release_termination.set()

    with pytest.raises(refusal):
        await changing
    await terminating

    assert session.status.value == "terminated"
    assert recorder.phases == ["SessionLifecyclePhase.TERMINATED"]
    assert [message.id for message in session.messages] == []


async def test_a_guest_socket_that_connects_behind_a_termination_is_closed(
    tmp_path: Path,
) -> None:
    """The guest must not join the live set after the termination broadcast went out."""
    redis = HeldTerminationRedis()
    store = RedisTenantSessionStore(redis)
    manager = TenantSessionManager(store=store, audio_store=AudioStore(tmp_path))
    sockets = WebSocketManager(manager, monitor=websocket_monitor())
    sockets.start_heartbeat_system = AsyncMock()
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    await manager.activate_session(session.key, "en")
    guest = AsyncMock()

    terminating = asyncio.create_task(manager.terminate_session(session.key, "manual"))
    connecting = asyncio.create_task(
        sockets.connect_websocket(guest, session.key, ClientType.CUSTOMER)
    )
    for _ in range(10):
        await asyncio.sleep(0)
    assert store._write_locks._entries[session.key].holders == 2
    redis.release_termination.set()

    with pytest.raises(RuntimeError):
        await connecting
    await terminating

    guest.close.assert_awaited_once_with(code=4404, reason="Session not found")
    assert sockets.session_connections.get(session.key, {}) == {}
