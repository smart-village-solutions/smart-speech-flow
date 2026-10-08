"""A session's captured retention governs its authorised text; refused text goes regardless."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.api_gateway.audio_storage import AudioStore, AudioVariant
from services.api_gateway.consent import ConsentStatus
from services.api_gateway.session_manager import TenantSessionManager
from services.api_gateway.session_models import ClientType, SessionMessage
from services.api_gateway.session_models import SessionStatus
from services.api_gateway.session_store import (
    MemoryTenantSessionStore,
    SessionStoreConsistencyError,
)

REVISION = f"sha256:{'a' * 64}"
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
# Captured but never consulted: none of these sessions granted consent.
UNGRANTED = None


@pytest.fixture(autouse=True)
def default_terminal_period(monkeypatch):
    monkeypatch.delenv("SSF_TERMINAL_RECORD_HOURS", raising=False)


@pytest.fixture
def audio_store(tmp_path: Path) -> AudioStore:
    return AudioStore(tmp_path)


@pytest.fixture
def manager(audio_store: AudioStore) -> TenantSessionManager:
    return TenantSessionManager(store=MemoryTenantSessionStore(), audio_store=audio_store)


async def _session_aged(
    manager, *, age: timedelta, authorized: bool, retention: int | None = UNGRANTED
):
    session = await manager.create_admin_session("tenant-test", REVISION)
    session.created_at = NOW - age
    if retention is not None:
        session.consent_status = ConsentStatus.GRANTED
        session.consent_retention_hours = retention
    await manager.add_message(
        session.key,
        SessionMessage(
            id="m1",
            sender=ClientType.CUSTOMER,
            original_text="hallo",
            translated_text="hello",
            audio_base64=None,
            source_lang="de",
            target_lang="en",
            timestamp=NOW - age,
            record_authorized=authorized,
            original_audio_authorized=authorized,
            translated_audio_authorized=authorized,
        ),
    )
    return session.key


async def test_authorised_text_expires_at_the_captured_retention(manager):
    key = await _session_aged(manager, age=timedelta(hours=73), authorized=True, retention=72)
    await manager.sweep_expired_content(NOW)
    assert (await manager.get_session(key)).messages == []


async def test_authorised_text_survives_inside_the_captured_retention(manager):
    key = await _session_aged(manager, age=timedelta(hours=71), authorized=True, retention=72)
    await manager.sweep_expired_content(NOW)
    assert len((await manager.get_session(key)).messages) == 1


async def test_a_long_captured_retention_outlasts_the_short_default(manager):
    key = await _session_aged(manager, age=timedelta(hours=25), authorized=True, retention=4320)
    await manager.sweep_expired_content(NOW)
    assert len((await manager.get_session(key)).messages) == 1


async def test_a_captured_zero_never_expires_authorised_text(manager):
    key = await _session_aged(manager, age=timedelta(days=30), authorized=True, retention=0)
    await manager.sweep_expired_content(NOW)
    assert len((await manager.get_session(key)).messages) == 1


async def test_text_without_granted_consent_expires_at_the_short_default(manager):
    key = await _session_aged(manager, age=timedelta(hours=25), authorized=True)
    await manager.sweep_expired_content(NOW)
    assert (await manager.get_session(key)).messages == []


async def test_the_short_default_is_configurable(manager, monkeypatch):
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", "48")
    key = await _session_aged(manager, age=timedelta(hours=25), authorized=True)
    await manager.sweep_expired_content(NOW)
    assert len((await manager.get_session(key)).messages) == 1


async def test_each_session_is_swept_by_its_own_retention(manager):
    kept = await _session_aged(manager, age=timedelta(hours=30), authorized=True, retention=4320)
    expired = await _session_aged(manager, age=timedelta(hours=30), authorized=True, retention=24)

    await manager.sweep_expired_content(NOW)

    assert len((await manager.get_session(kept)).messages) == 1
    assert (await manager.get_session(expired)).messages == []


async def test_refused_content_in_an_abandoned_session_is_removed(manager):
    # A captured zero must not retain refused content.
    key = await _session_aged(manager, age=timedelta(hours=9), authorized=False, retention=0)
    await manager.sweep_expired_content(NOW)
    assert (await manager.get_session(key)).messages == []


async def test_refused_content_survives_inside_the_session_lifetime(manager):
    # Removal belongs to termination; the sweep is the net for what never ends.
    key = await _session_aged(manager, age=timedelta(hours=2), authorized=False, retention=0)
    await manager.sweep_expired_content(NOW)
    assert len((await manager.get_session(key)).messages) == 1


class _LifecycleEnforcingStore(MemoryTenantSessionStore):
    """Models the one Redis rule the plain memory store does not.

    `SAVE_SESSION_LUA` refuses every change to a terminated record, so a sweep
    that mutates one raises `SessionStoreConsistencyError` in production and
    passes silently against `MemoryTenantSessionStore`. Without this double the
    suite cannot see the failure at all.
    """

    def __init__(self) -> None:
        super().__init__()
        self.saves: list = []

    async def save(self, session):
        existing = self._sessions.get(session.key)
        if existing is not None and existing.status is SessionStatus.TERMINATED:
            raise SessionStoreConsistencyError(
                "session lifecycle does not permit save"
            )
        self.saves.append(session.key)
        await super().save(session)


@pytest.fixture
def strict_manager(audio_store: AudioStore) -> TenantSessionManager:
    return TenantSessionManager(store=_LifecycleEnforcingStore(), audio_store=audio_store)


async def test_one_terminated_session_does_not_abort_the_whole_sweep(
    strict_manager, audio_store, monkeypatch
):
    terminated = await _session_aged(
        strict_manager, age=timedelta(hours=25), authorized=True
    )
    await strict_manager.terminate_session(terminated, reason="test")
    live = await _session_aged(
        strict_manager, age=timedelta(hours=25), authorized=True
    )

    await strict_manager.sweep_expired_content(NOW)

    # The live session is swept even though a terminated one came first.
    assert (await strict_manager.get_session(live)).messages == []


async def test_the_sweep_leaves_terminated_records_untouched(
    strict_manager, audio_store, monkeypatch
):
    # A terminated record is immutable in the store. Pruning it in memory only
    # would drift from Redis and resurrect on the next load.
    key = await _session_aged(
        strict_manager, age=timedelta(hours=25), authorized=True
    )
    await strict_manager.terminate_session(key, reason="test")

    await strict_manager.sweep_expired_content(NOW)

    assert len((await strict_manager.store.load(key)).messages) == 1


async def test_an_audio_only_removal_is_persisted(
    strict_manager, audio_store, monkeypatch
):
    # The message count is unchanged, so a count-based dirty check would keep
    # `translated_audio_available: true` in the store for a file that is gone.
    session = await strict_manager.create_admin_session("tenant-test", REVISION)
    session.created_at = NOW - timedelta(hours=9)
    session.consent_status = ConsentStatus.GRANTED
    session.consent_retention_hours = 0
    await strict_manager.add_message(
        session.key,
        SessionMessage(
            id="m1",
            sender=ClientType.CUSTOMER,
            original_text="hallo",
            translated_text="hello",
            audio_base64=None,
            source_lang="de",
            target_lang="en",
            timestamp=NOW - timedelta(hours=9),
            translated_audio_available=True,
            record_authorized=True,
            original_audio_authorized=True,
            translated_audio_authorized=False,
        ),
    )

    strict_manager.store.saves.clear()
    await strict_manager.sweep_expired_content(NOW)

    # `MemoryTenantSessionStore.load` returns the very object the sweep
    # mutated, so only a recorded write proves this survives a restart.
    assert session.key in strict_manager.store.saves
    stored = await strict_manager.store.load(session.key)
    assert len(stored.messages) == 1
    assert stored.messages[0].translated_audio_available is False


async def test_a_legacy_session_sweeps_without_logging_a_failure(monkeypatch, caplog):
    """`Session.key` raises without a tenant, and the sweep read it blindly.

    The prune commits first, so the ValueError is pure noise -- but it is
    logged as a sweep failure on every hourly pass and makes the legacy branch
    of the persist helper unreachable.
    """
    import logging

    from services.api_gateway.legacy_session_manager import LegacySessionManager
    from services.api_gateway.session_models import Session

    legacy = Session(id="LEGACY01")
    legacy.created_at = NOW - timedelta(hours=25)
    legacy.messages = [
        SessionMessage(
            id="m1",
            sender=ClientType.CUSTOMER,
            original_text="hallo",
            translated_text="hello",
            audio_base64=None,
            source_lang="de",
            target_lang="en",
            timestamp=NOW - timedelta(hours=25),
            record_authorized=True,
        )
    ]
    manager = LegacySessionManager()
    manager.sessions[legacy.id] = legacy

    with caplog.at_level(logging.WARNING):
        await manager.sweep_expired_content(NOW)

    assert legacy.messages == []
    assert "content_sweep_failed" not in caplog.text


async def test_a_failed_sweep_write_retries_on_the_next_pass(
    strict_manager, audio_store, monkeypatch
):
    """A sweep that prunes before committing strands the files it meant to drop.

    `terminate_session` settles a copy and deletes only after the commit. The
    sweep must do the same: pruning the live list first means the next pass
    sees nothing refused, returns an empty deletion list, and the files are
    never removed while Redis still holds the unpruned record.
    """
    session = await strict_manager.create_admin_session("tenant-test", REVISION)
    session.created_at = NOW - timedelta(hours=9)
    session.consent_status = ConsentStatus.GRANTED
    session.consent_retention_hours = 0
    await strict_manager.add_message(
        session.key,
        SessionMessage(
            id="m1",
            sender=ClientType.CUSTOMER,
            original_text="hallo",
            translated_text="hello",
            audio_base64=None,
            source_lang="de",
            target_lang="en",
            timestamp=NOW - timedelta(hours=9),
            record_authorized=False,
        ),
    )
    audio_store.save(session.key, "m1", AudioVariant.TRANSLATED, b"wav")

    failed = {"count": 0}
    real_save = strict_manager.store.save

    async def _flaky(sess):
        if failed["count"] == 0:
            failed["count"] += 1
            raise SessionStoreConsistencyError("transient")
        return await real_save(sess)

    monkeypatch.setattr(strict_manager.store, "save", _flaky)

    await strict_manager.sweep_expired_content(NOW)
    # The write failed, so nothing may have been removed yet.
    assert len((await strict_manager.store.load(session.key)).messages) == 1
    assert audio_store.path(session.key, "m1", AudioVariant.TRANSLATED).exists()

    await strict_manager.sweep_expired_content(NOW)
    assert (await strict_manager.store.load(session.key)).messages == []
    assert not audio_store.path(session.key, "m1", AudioVariant.TRANSLATED).exists()


async def test_a_session_the_sweep_could_not_save_is_reported(manager, audio_store, monkeypatch):
    """The retention pass must not call itself complete over unsaved deletions."""
    key = await _session_aged(manager, age=timedelta(hours=25), authorized=True)

    def unavailable(_session):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(manager.store, "save", unavailable)

    assert await manager.sweep_expired_content(NOW) == {
        "refused_removed": 0,
        "expired_removed": 0,
        "failed": 1,
    }
    assert len((await manager.get_session(key)).messages) == 1
