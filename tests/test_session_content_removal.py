"""Outside a recording nothing of a conversation outlives its session (spec §5.4, §5.5)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from services.api_gateway import session_store as session_store_module
from services.api_gateway.audio_storage import AudioStore, AudioVariant
from services.api_gateway.clock import utc_now
from services.api_gateway.session_manager import TenantSessionManager
from services.api_gateway.session_models import ClientType, Session, SessionMessage, SessionStatus
from services.api_gateway.session_store import (
    MemoryTenantSessionStore,
    RedisTenantSessionStore,
    _join_payload,
    join_key,
    session_key,
)
from tests.test_tenant_session_store import RecordingRedis

REVISION = f"sha256:{'a' * 64}"


def _message(message_id: str) -> SessionMessage:
    return SessionMessage(
        id=message_id,
        sender=ClientType.CUSTOMER,
        original_text="Guten Tag",
        translated_text="Good day",
        audio_base64=None,
        source_lang="de",
        target_lang="en",
        timestamp=utc_now(),
        translated_audio_available=True,
    )


def _manager(tmp_path: Path, store: MemoryTenantSessionStore | None = None) -> TenantSessionManager:
    return TenantSessionManager(
        store=store or MemoryTenantSessionStore(), audio_store=AudioStore(tmp_path)
    )


async def _conversation(manager: TenantSessionManager, *message_ids: str) -> Session:
    """A live session whose messages each have both audio files on disk."""
    session = await manager.create_admin_session("tenant-a", REVISION)
    for message_id in message_ids:
        await manager.add_message(session.key, _message(message_id))
        for variant in AudioVariant:
            manager.audio_store.save(session.key, message_id, variant, b"RIFF-audio")
    return session


def _audio_files(manager: TenantSessionManager, session: Session) -> list[Path]:
    return [
        manager.audio_store.path(session.key, message.id, variant)
        for message in session.messages
        for variant in AudioVariant
        if manager.audio_store.path(session.key, message.id, variant).exists()
    ]


def _session_audio_dir(manager: TenantSessionManager, session: Session) -> Path:
    return manager.audio_store.base_dir / "v2" / session.key.tenant_ref / session.id


class _FailingTerminateStore(MemoryTenantSessionStore):
    async def terminate(self, session: Session) -> Session:
        raise ConnectionError("redis went away")


class _FailingSaveStore(MemoryTenantSessionStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_saves = False

    async def save(self, session: Session) -> None:
        if self.fail_saves:
            raise ConnectionError("redis went away")
        await super().save(session)


async def test_termination_strips_every_message_but_keeps_their_count(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = await _conversation(manager, "m1", "m2", "m3")

    await manager.terminate_session(session.key, "manual_admin_termination")

    stored = await manager.store.load(session.key)
    assert stored is not None and stored.status is SessionStatus.TERMINATED
    assert stored.messages == []
    assert stored.ended_message_count == 3
    assert stored.to_public_dict()["message_count"] == 3
    assert session.messages == []
    assert session.to_public_dict()["message_count"] == 3


async def test_the_terminal_record_holds_no_conversation_text(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = await _conversation(manager, "m1")

    await manager.terminate_session(session.key, "manual_admin_termination")

    stored = await manager.store.load(session.key)
    payload = json.dumps(stored.to_dict(include_messages=True))
    assert "Guten Tag" not in payload
    assert "Good day" not in payload


async def test_termination_deletes_all_of_the_sessions_audio(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = await _conversation(manager, "m1", "m2")
    other = await manager.create_admin_session("tenant-b", REVISION)
    manager.audio_store.save(other.key, "m9", AudioVariant.TRANSLATED, b"RIFF-audio")
    assert len(_audio_files(manager, session)) == 4

    await manager.terminate_session(session.key, "manual_admin_termination")

    assert not _session_audio_dir(manager, session).exists()
    assert manager.audio_store.path(other.key, "m9", AudioVariant.TRANSLATED).exists()


async def test_a_failed_termination_leaves_the_live_messages_and_audio_untouched(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path, _FailingTerminateStore())
    session = await _conversation(manager, "m1", "m2")

    with pytest.raises(ConnectionError):
        await manager.terminate_session(session.key, "manual_admin_termination")

    assert session.status is not SessionStatus.TERMINATED
    assert [message.id for message in session.messages] == ["m1", "m2"]
    assert session.ended_message_count is None
    assert len(_audio_files(manager, session)) == 4


def _shift_store_clock(monkeypatch: pytest.MonkeyPatch, offset: timedelta) -> None:
    real = datetime

    class _Shifted(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz) + offset

    monkeypatch.setattr(session_store_module, "datetime", _Shifted)


async def test_the_terminal_record_expires_after_the_configured_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", "6")
    manager = _manager(tmp_path)
    session = await _conversation(manager, "m1")
    await manager.terminate_session(session.key, "manual_admin_termination")

    _shift_store_clock(monkeypatch, timedelta(hours=5, minutes=59))
    assert await manager.store.load(session.key) is not None

    _shift_store_clock(monkeypatch, timedelta(hours=6, seconds=1))
    assert await manager.store.load(session.key) is None
    # The tombstone outlives the record, so the identifier is not reused.
    assert await manager.store.create(Session(session.id, "tenant-a", REVISION)) is False


async def _aged(manager: TenantSessionManager, *message_ids: str, hours: float) -> Session:
    session = await _conversation(manager, *message_ids)
    session.created_at = utc_now() - timedelta(hours=hours)
    return session


async def test_the_sweep_strips_a_session_past_its_maximum_lifetime(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = await _aged(manager, "m1", "m2", hours=9)
    audio_dir = _session_audio_dir(manager, session)
    assert audio_dir.exists()

    counts = await manager.sweep_expired_content(utc_now())

    assert counts == {"removed": 2, "failed": 0}
    assert session.messages == []
    assert (await manager.store.load(session.key)).messages == []
    assert not audio_dir.exists()


async def test_the_sweep_leaves_a_session_younger_than_its_maximum_lifetime(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    session = await _aged(manager, "m1", hours=7)

    counts = await manager.sweep_expired_content(utc_now())

    assert counts == {"removed": 0, "failed": 0}
    assert [message.id for message in session.messages] == ["m1"]
    assert len(_audio_files(manager, session)) == 2


async def test_the_sweep_skips_a_terminated_session(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = await _aged(manager, "m1", hours=9)
    await manager.terminate_session(session.key, "manual_admin_termination")
    # A cached terminal record is immutable in the store; the sweep must not write it.
    session.messages = [_message("late")]
    manager.audio_store.save(session.key, "late", AudioVariant.TRANSLATED, b"RIFF-audio")

    counts = await manager.sweep_expired_content(utc_now())

    assert counts == {"removed": 0, "failed": 0}
    assert [message.id for message in session.messages] == ["late"]
    assert manager.audio_store.path(session.key, "late", AudioVariant.TRANSLATED).exists()


async def test_a_sweep_whose_save_fails_keeps_the_messages_and_audio(tmp_path: Path) -> None:
    store = _FailingSaveStore()
    manager = _manager(tmp_path, store)
    session = await _aged(manager, "m1", "m2", hours=9)
    store.fail_saves = True

    counts = await manager.sweep_expired_content(utc_now())

    assert counts == {"removed": 0, "failed": 1}
    assert [message.id for message in session.messages] == ["m1", "m2"]
    assert len(_audio_files(manager, session)) == 4


def _record_with_consent() -> dict:
    session = Session(id="OLDREC01", tenant_id="tenant-a", configuration_revision=REVISION)
    session.status = SessionStatus.ACTIVE
    session.messages = [_message("m1")]
    record = session.to_dict(include_messages=True)
    record.update(
        consent_status="granted",
        consent_retention_hours=4320,
        consent_configuration_revision=REVISION,
    )
    record["messages"][0].update(
        record_authorized=True,
        original_audio_authorized=True,
        translated_audio_authorized=False,
    )
    return record


def test_a_stored_record_with_consent_and_authorization_keys_still_loads() -> None:
    session = Session.from_dict(_record_with_consent())

    assert session.key.session_id == "OLDREC01"
    assert session.status is SessionStatus.ACTIVE
    assert [message.id for message in session.messages] == ["m1"]
    assert not hasattr(session, "consent_status")
    assert not hasattr(session.messages[0], "record_authorized")


async def test_the_redis_store_loads_a_record_written_with_consent() -> None:
    redis = RecordingRedis()
    store = RedisTenantSessionStore(redis, namespace="ssf")
    record = _record_with_consent()
    loaded_key = Session.from_dict(record).key
    redis.set(session_key("ssf", loaded_key), json.dumps(record))
    redis.set(join_key("ssf", loaded_key.session_id), _join_payload(loaded_key, active=True))

    loaded = await store.load(loaded_key)

    assert loaded is not None
    assert [message.original_text for message in loaded.messages] == ["Guten Tag"]


async def test_a_message_finishing_after_the_end_is_refused_and_not_kept(tmp_path: Path) -> None:
    from services.api_gateway.session_store import SessionStoreConsistencyError

    manager = _manager(tmp_path)
    session = await _conversation(manager, "m1")
    await manager.terminate_session(session.key, "manual_termination")

    with pytest.raises(SessionStoreConsistencyError):
        await manager.add_message(session.key, _message("late"))

    assert session.messages == []
    stored = await manager.store.load(session.key)
    assert stored is not None and stored.messages == []


async def test_a_late_message_leaves_no_audio_behind(tmp_path: Path) -> None:
    """The pipeline outran the termination: its files land after the end deleted the rest."""
    from services.api_gateway import message_processing
    from services.api_gateway.session_store import SessionStoreConsistencyError

    manager = _manager(tmp_path)
    session = await _conversation(manager, "m1")
    await manager.terminate_session(session.key, "manual_termination")

    with pytest.raises(SessionStoreConsistencyError):
        await message_processing._complete_message(
            key=session.key,
            client_type=ClientType.CUSTOMER,
            result={"translation_text": "Good day", "audio_bytes": b"RIFF-late", "debug": {}},
            source_lang="de",
            target_lang="en",
            original_text="Guten Tag",
            original_audio=b"RIFF-original",
            pipeline_type="audio",
            manager=None,
            sessions=manager,
            audio_store=manager.audio_store,
            start_time=0.0,
        )

    assert list(tmp_path.rglob("*.wav")) == []


async def test_a_recording_that_cannot_end_does_not_undo_the_termination(tmp_path):
    # The termination committed first; recording's own end is retried by its archive.
    manager = _manager(tmp_path)
    session = await _conversation(manager, "m1")

    class Recording:
        async def note_recorded(self, key):
            return None

        async def session_ended(self, key):
            raise ConnectionError("redis down")

    manager.recording = Recording()
    await manager.terminate_session(session.key, "manual_termination")

    stored = await manager.store.load(session.key)
    assert stored is not None and stored.status is SessionStatus.TERMINATED
    assert await manager.create_admin_session(session.tenant_id, "rev") is not None
