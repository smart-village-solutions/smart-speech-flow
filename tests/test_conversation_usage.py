"""Conversation minutes reflect paid elapsed time, with isolated scope totals."""

from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.conversation_usage import ConversationUsage, UsageUnavailable
from services.api_gateway.session_manager import TenantSessionManager
from services.api_gateway.session_models import Session
from services.api_gateway.session_store import MemoryTenantSessionStore

REVISION = f"sha256:{'a' * 64}"


class Clock:
    def __init__(self):
        self.current = datetime(2026, 11, 18, 8, tzinfo=timezone.utc)

    def __call__(self):
        return self.current

    def advance(self, **kwargs):
        self.current += timedelta(**kwargs)


@pytest.fixture
def setup_usage(tmp_path):
    clock = Clock()
    usage = ConversationUsage(str(tmp_path / "usage.sqlite3"), clock=clock)
    manager = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=AudioStore.from_environment(),
        clock=clock,
        usage=usage,
    )
    return clock, usage, manager


async def test_waiting_is_excluded_pauses_and_language_intervals_count(setup_usage):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("tenant-a", REVISION, owner_ref="alice")
    clock.advance(minutes=5)
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=10)
    await manager.activate_session(session.key, "uk")
    clock.advance(minutes=15)
    await manager.terminate_session(session.key)
    await manager.terminate_session(session.key)
    report = await manager.conversation_usage_report("tenant-a", "alice")
    assert report.personal.total_seconds == 1500
    assert report.personal.by_language == {"ar": 600, "uk": 900}
    assert report.organisation == report.personal == report.server
    assert report.complete is False
    assert "usage_language_changes" not in session.to_public_dict()
    restored = Session.from_dict(session.to_dict())
    assert restored.usage_language_changes == session.usage_language_changes


async def test_scopes_and_ongoing_conversations_are_counted_once(setup_usage):
    clock, usage, manager = setup_usage
    for tenant, owner, language in [("a", "alice", "ar"), ("a", "bob", "uk"), ("b", "eve", "ar")]:
        session = await manager.create_admin_session(tenant, REVISION, owner_ref=owner)
        await manager.activate_session(session.key, language)
    clock.advance(minutes=10)
    report = await manager.conversation_usage_report("a", "alice")
    assert report.personal.total_seconds == 600
    assert report.organisation.total_seconds == 1200
    assert report.server.total_seconds == 1800
    assert report.server.by_language == {"ar": 1200, "uk": 600}
    other = await manager.conversation_usage_report("b", "alice")
    assert other.personal.total_seconds == 0
    assert other.organisation.total_seconds == 600


async def test_pending_and_legacy_active_sessions_do_not_invent_start_times(setup_usage):
    clock, usage, manager = setup_usage
    await manager.create_admin_session("a", REVISION, owner_ref="alice")
    clock.advance(minutes=10)
    assert (await manager.conversation_usage_report("a", "alice")).server.total_seconds == 0
    session = await manager.create_admin_session("a", REVISION, owner_ref="bob")
    await manager.activate_session(session.key, "ar")
    session.usage_language_changes = []  # Represents an old active record.
    await manager.activate_session(session.key, "uk")
    assert session.usage_language_changes == []


async def test_restart_and_content_expiry_preserve_usage(setup_usage, tmp_path):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=20)
    await manager.terminate_session(session.key)
    coverage = (await usage.report("a", "alice", clock())).coverage_start
    manager.store.expire_now(session.key)
    await usage.close()
    restarted = ConversationUsage(str(tmp_path / "usage.sqlite3"), clock=clock)
    report = await restarted.report("a", "alice", clock())
    assert report.personal.by_language == {"ar": 1200}
    assert report.coverage_start == coverage
    assert await manager.store.load(session.key) is None
    await restarted.close()


async def test_window_clips_language_intervals_and_prunes_old_usage(setup_usage):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=10)
    await manager.activate_session(session.key, "uk")
    clock.advance(minutes=20)
    await manager.terminate_session(session.key)
    clock.advance(days=30, minutes=-15)
    report = await usage.report("a", "alice", clock())
    assert report.personal.total_seconds == 900
    assert report.personal.by_language == {"uk": 900}
    assert report.complete is True
    clock.advance(minutes=16)
    assert (await usage.report("a", "alice", clock())).server.total_seconds == 0


async def test_same_language_selection_does_not_split_or_duplicate_usage(setup_usage):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=5)
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=5)
    assert len(session.usage_language_changes) == 1
    assert (await manager.conversation_usage_report("a", "alice")).personal.by_language == {
        "ar": 600
    }


async def test_broken_storage_is_unavailable_not_zero(tmp_path):
    usage = ConversationUsage(str(tmp_path / "missing" / "usage.sqlite3"))
    with pytest.raises(UsageUnavailable):
        await usage.report("a", "alice", datetime.now(timezone.utc))


async def test_usage_outage_keeps_conversation_live_and_retries_metadata(tmp_path):
    clock = Clock()
    usage = ConversationUsage(str(tmp_path / "offline" / "usage.db"), clock=clock)
    manager = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=AudioStore.from_environment(),
        clock=clock,
        usage=usage,
    )
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=10)
    with pytest.raises(UsageUnavailable):
        await manager.conversation_usage_report("a", "alice")
    (tmp_path / "offline").mkdir()
    report = await manager.conversation_usage_report("a", "alice")
    assert report.personal.by_language == {"ar": 600}
    await manager.terminate_session(session.key)
    await usage.close()


async def test_unknown_language_keeps_elapsed_minutes(setup_usage):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "")
    clock.advance(minutes=2)
    report = await manager.conversation_usage_report("a", "alice")
    assert report.personal.by_language == {"unknown": 120}
    assert report.personal.total_seconds == 120


async def test_terminal_usage_cannot_be_reopened_by_stale_projection(setup_usage):
    from services.api_gateway.conversation_usage import UsageSnapshot

    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    stale = UsageSnapshot.of(session, clock())
    clock.advance(minutes=10)
    await manager.terminate_session(session.key)
    await usage.record(stale)
    clock.advance(minutes=10)
    report = await usage.report("a", "alice", clock())
    assert report.personal.total_seconds == 600


async def test_rehydration_preserves_first_activation_and_language_intervals(setup_usage):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=10)
    # Roundtrip as Redis does; restarted managers must not substitute restart time.
    restored = Session.from_dict(session.to_dict())
    manager.store._sessions[session.key] = restored
    restarted = TenantSessionManager(
        store=manager.store,
        audio_store=manager.audio_store,
        clock=clock,
        usage=usage,
    )
    await restarted.rehydrate_tenant_sessions()
    await restarted.activate_session(restored.key, "uk")
    clock.advance(minutes=5)
    report = await restarted.conversation_usage_report("a", "alice")
    assert report.personal.by_language == {"ar": 600, "uk": 300}


async def test_failed_activation_does_not_create_paid_usage(setup_usage):
    from services.api_gateway.session_store import SessionStoreConsistencyError

    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")

    class FailingStore(MemoryTenantSessionStore):
        async def save(self, session):
            raise SessionStoreConsistencyError("not saved")

    manager.store = FailingStore()
    with pytest.raises(SessionStoreConsistencyError):
        await manager.activate_session(session.key, "ar")
    clock.advance(minutes=10)
    report = await manager.conversation_usage_report("a", "alice")
    assert report.personal.total_seconds == 0


async def test_unclean_restart_retains_completed_usage_but_discards_unconfirmed_open_rows(
    setup_usage, tmp_path
):
    clock, usage, manager = setup_usage
    first = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(first.key, "ar")
    clock.advance(minutes=10)
    await manager.terminate_session(first.key)
    second = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(second.key, "uk")
    clock.advance(minutes=10)
    await usage.close(clean=False)
    restarted = ConversationUsage(str(tmp_path / "usage.sqlite3"), clock=clock)
    report = await restarted.report("a", "alice", clock())
    assert report.personal.by_language == {"ar": 600}
    assert report.coverage_start == clock()
    assert report.complete is False
    await restarted.close()


async def test_retained_terminal_records_repair_missing_usage_after_restart(setup_usage, tmp_path):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=10)
    await usage.close()
    manager.usage = ConversationUsage(str(tmp_path / "offline" / "usage.db"), clock=clock)
    await manager.terminate_session(session.key)
    restarted_usage = ConversationUsage(str(tmp_path / "usage.sqlite3"), clock=clock)
    restarted = TenantSessionManager(
        store=manager.store,
        audio_store=manager.audio_store,
        clock=clock,
        usage=restarted_usage,
    )
    await restarted.rehydrate_tenant_sessions()
    clock.advance(minutes=10)
    report = await restarted.conversation_usage_report("a", "alice")
    assert report.personal.total_seconds == 600
    assert restarted.sessions == {}
    await restarted_usage.close()


async def test_restart_after_redis_loss_does_not_keep_billing_open_conversations(
    setup_usage, tmp_path
):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=10)
    await usage.close()
    restarted_usage = ConversationUsage(str(tmp_path / "usage.sqlite3"), clock=clock)
    restarted = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=manager.audio_store,
        clock=clock,
        usage=restarted_usage,
    )
    await restarted.rehydrate_tenant_sessions()
    report = await restarted.conversation_usage_report("a", "alice")
    assert report.personal.total_seconds == 0
    assert report.coverage_start == clock()
    assert report.complete is False
    await restarted_usage.close()


async def test_reporting_during_failed_activation_does_not_persist_proposed_state(setup_usage):
    import asyncio

    from services.api_gateway.session_store import SessionStoreConsistencyError

    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    saving, release = asyncio.Event(), asyncio.Event()

    class BlockedFailingStore(MemoryTenantSessionStore):
        async def save(self, session):
            saving.set()
            await release.wait()
            raise SessionStoreConsistencyError("not committed")

    manager.store = BlockedFailingStore()
    activation = asyncio.create_task(manager.activate_session(session.key, "ar"))
    await saving.wait()
    try:
        await manager.conversation_usage_report("a", "alice")
    finally:
        release.set()
        with pytest.raises(SessionStoreConsistencyError):
            await activation
    clock.advance(minutes=10)
    assert (await manager.conversation_usage_report("a", "alice")).personal.total_seconds == 0


async def test_failed_startup_recovery_blocks_reports_until_retried(setup_usage, tmp_path):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    clock.advance(minutes=10)
    await usage.close()
    unavailable = [True]

    class RecoveringUsage(ConversationUsage):
        async def finish_recovery(self, known_keys, now):
            if unavailable[0]:
                raise UsageUnavailable("offline")
            await super().finish_recovery(known_keys, now)

    restarted_usage = RecoveringUsage(str(tmp_path / "usage.sqlite3"), clock=clock)
    restarted = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=manager.audio_store,
        clock=clock,
        usage=restarted_usage,
    )
    await restarted.rehydrate_tenant_sessions()
    with pytest.raises(UsageUnavailable):
        await restarted.conversation_usage_report("a", "alice")
    unavailable[0] = False
    clock.advance(minutes=10)
    report = await restarted.conversation_usage_report("a", "alice")
    assert report.personal.total_seconds == 0
    assert report.coverage_start == clock()
    await restarted_usage.close()


async def test_termination_uses_committed_activation_metadata(setup_usage):
    import asyncio

    from services.api_gateway.session_store import SessionStoreConsistencyError

    clock, usage, manager = setup_usage
    original = manager.store
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    saving, release = asyncio.Event(), asyncio.Event()

    class BlockedFailingStore(MemoryTenantSessionStore):
        async def save(self, session):
            saving.set()
            await release.wait()
            raise SessionStoreConsistencyError("not committed")

        async def terminate(self, session):
            return await original.terminate(session)

    manager.store = BlockedFailingStore()
    activation = asyncio.create_task(manager.activate_session(session.key, "ar"))
    await saving.wait()
    try:
        clock.advance(minutes=1)
        termination = asyncio.create_task(manager.terminate_session(session.key))
    finally:
        release.set()
        with pytest.raises(SessionStoreConsistencyError):
            await activation
    await termination
    assert (await manager.conversation_usage_report("a", "alice")).personal.total_seconds == 0
    assert (await original.load(session.key)).usage_language_changes == []


async def test_conversation_started_during_recovery_keeps_its_usage(setup_usage, tmp_path):
    import asyncio

    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.activate_session(session.key, "ar")
    await usage.close()
    recovering, release, saving = asyncio.Event(), asyncio.Event(), asyncio.Event()
    first = [True]

    class PausedRecovery(ConversationUsage):
        async def finish_recovery(self, known_keys, now):
            if first[0]:
                first[0] = False
                raise UsageUnavailable("retry recovery")
            recovering.set()
            await release.wait()
            await super().finish_recovery(known_keys, now)

    class ObservableStore(MemoryTenantSessionStore):
        async def save(self, session):
            await super().save(session)
            saving.set()

    restarted_usage = PausedRecovery(str(tmp_path / "usage.sqlite3"), clock=clock)
    restarted = TenantSessionManager(
        store=ObservableStore(),
        audio_store=manager.audio_store,
        clock=clock,
        usage=restarted_usage,
    )
    await restarted.rehydrate_tenant_sessions()
    report_task = asyncio.create_task(restarted.conversation_usage_report("a", "alice"))
    await recovering.wait()
    new_session = await restarted.create_admin_session("a", REVISION, owner_ref="alice")
    activation = asyncio.create_task(restarted.activate_session(new_session.key, "uk"))
    await saving.wait()
    # Allow a projection to run if recovery and projection are not serialised.
    await asyncio.wait({activation}, timeout=0.1)
    release.set()
    await report_task
    await activation
    clock.advance(minutes=10)
    assert (await restarted.conversation_usage_report("a", "alice")).personal.by_language == {
        "uk": 600
    }
    await restarted_usage.close()


async def test_termination_preserves_activation_committed_before_save_response(setup_usage):
    import asyncio

    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    original = manager.store
    saved, release = asyncio.Event(), asyncio.Event()

    class DelayedResponseStore(MemoryTenantSessionStore):
        async def save(self, session):
            await original.save(Session.from_dict(session.to_dict()))
            saved.set()
            await release.wait()

        async def terminate(self, session):
            return await original.terminate(session)

    manager.store = DelayedResponseStore()
    activation = asyncio.create_task(manager.activate_session(session.key, "ar"))
    await saved.wait()
    try:
        clock.advance(minutes=1)
        termination = asyncio.create_task(manager.terminate_session(session.key))
    finally:
        release.set()
        await activation
    await termination
    assert (await manager.conversation_usage_report("a", "alice")).personal.by_language == {
        "ar": 60
    }


async def test_reconnect_replaces_obsolete_failed_disconnect_projection(setup_usage):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    await manager.admin_connected(session.key)
    await manager.activate_session(session.key, "ar")
    original_record = usage.record
    offline = [True]

    async def flaky_record(snapshot):
        if offline[0]:
            raise UsageUnavailable("offline")
        await original_record(snapshot)

    usage.record = flaky_record
    clock.advance(minutes=1)
    await manager.admin_disconnected(session.key)
    clock.advance(minutes=1)
    await manager.admin_connected(session.key)
    offline[0] = False
    clock.advance(hours=1)
    report = await manager.conversation_usage_report("a", "alice")
    assert report.personal.total_seconds == 3720


async def test_presence_save_cannot_project_a_failed_activation(setup_usage):
    import asyncio

    from services.api_gateway.session_store import SessionStoreConsistencyError

    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    original = manager.store
    entered, release = asyncio.Event(), asyncio.Event()
    calls = [0]

    class DelayedStore(MemoryTenantSessionStore):
        async def save(self, session):
            calls[0] += 1
            this_call = calls[0]
            if this_call == 1:
                entered.set()
                await release.wait()
                raise SessionStoreConsistencyError("not committed")
            await release.wait()
            await original.save(session)

        async def load(self, key):
            return await original.load(key)

    manager.store = DelayedStore()
    activation = asyncio.create_task(manager.activate_session(session.key, "ar"))
    await entered.wait()
    presence = asyncio.create_task(manager.admin_connected(session.key))
    await asyncio.wait({presence}, timeout=0.05)
    release.set()
    with pytest.raises(SessionStoreConsistencyError):
        await activation
    await presence
    clock.advance(minutes=10)
    assert (await manager.conversation_usage_report("a", "alice")).personal.total_seconds == 0


async def test_commit_then_error_is_reconciled_before_termination(setup_usage):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    original = manager.store

    class LostAcknowledgement(MemoryTenantSessionStore):
        async def save(self, session):
            await original.save(session)
            raise OSError("acknowledgement lost")

        async def load(self, key):
            return await original.load(key)

        async def terminate(self, session):
            return await original.terminate(session)

    manager.store = LostAcknowledgement()
    with pytest.raises(OSError):
        await manager.activate_session(session.key, "ar")
    clock.advance(minutes=1)
    await manager.terminate_session(session.key)
    assert (await manager.conversation_usage_report("a", "alice")).personal.by_language == {
        "ar": 60
    }


async def test_unreadable_uncertain_save_evicts_cache_and_blocks_usage_until_reconciled(
    setup_usage,
):
    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    original = manager.store
    offline = [True]

    class UncertainSave(MemoryTenantSessionStore):
        async def save(self, session):
            await original.save(session)
            raise OSError("acknowledgement lost")

        async def load(self, key):
            if offline[0]:
                raise OSError("persistence offline")
            return await original.load(key)

    manager.store = UncertainSave()
    with pytest.raises(OSError):
        await manager.activate_session(session.key, "ar")
    assert session.key not in manager.sessions
    with pytest.raises(UsageUnavailable):
        await manager.conversation_usage_report("a", "alice")
    offline[0] = False
    clock.advance(minutes=10)
    assert (await manager.conversation_usage_report("a", "alice")).personal.by_language == {
        "ar": 600
    }


@pytest.mark.parametrize("operation", ["warning", "sweep"])
async def test_queued_maintenance_reloads_an_evicted_proposed_session(setup_usage, operation):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from services.api_gateway.session_models import ClientType, SessionMessage

    clock, usage, manager = setup_usage
    session = await manager.create_admin_session("a", REVISION, owner_ref="alice")
    original = manager.store
    entered, release = asyncio.Event(), asyncio.Event()
    saving = [True]
    reading = [True]

    class UncertainStore(MemoryTenantSessionStore):
        async def save(self, value):
            if saving[0]:
                saving[0] = False
                entered.set()
                await release.wait()
                raise OSError("save rejected")
            await original.save(value)

        async def load(self, key):
            if reading[0]:
                reading[0] = False
                raise OSError("canonical read unavailable")
            return await original.load(key)

    manager.store = UncertainStore()
    manager.websocket_manager = SimpleNamespace(broadcast_to_session=AsyncMock())
    session.messages.append(
        SessionMessage(
            id="message",
            sender=ClientType.ADMIN,
            original_text="hello",
            translated_text="hallo",
            audio_base64=None,
            source_lang="en",
            target_lang="de",
            timestamp=clock(),
        )
    )
    activation = asyncio.create_task(manager.activate_session(session.key, "ar"))
    await entered.wait()
    action = (
        manager._send_timeout_warning if operation == "warning" else manager._sweep_session_content
    )
    maintenance = asyncio.create_task(action(session))
    clock.advance(minutes=10)
    release.set()
    with pytest.raises(OSError):
        await activation
    await maintenance
    assert (await manager.conversation_usage_report("a", "alice")).personal.total_seconds == 0
