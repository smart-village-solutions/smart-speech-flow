"""Termination keeps authorised content and removes everything else."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.api_gateway import audio_storage
from services.api_gateway.audio_storage import AudioVariant, audio_path, save_audio
from services.api_gateway.session_manager import (
    ClientType,
    SessionManager,
    SessionMessage,
)
from services.api_gateway.session_store import (
    MemoryTenantSessionStore,
    SessionStoreConsistencyError,
)
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
def audio_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect every audio delete below the test's own directory."""
    real_delete = audio_storage.delete_message_audio

    def delete(key, message_id, variant, *, base_dir=None):
        return real_delete(key, message_id, variant, base_dir=tmp_path)

    monkeypatch.setattr(audio_storage, "delete_message_audio", delete)
    return tmp_path


@pytest.fixture
def manager() -> SessionManager:
    return SessionManager(store=MemoryTenantSessionStore())


def _message(message_id: str, *, record: bool, original: bool, translated: bool):
    return SessionMessage(
        id=message_id,
        sender=ClientType.CUSTOMER,
        original_text="hallo",
        translated_text="hello",
        audio_base64=None,
        source_lang="de",
        target_lang="en",
        timestamp=datetime.now(timezone.utc),
        translated_audio_available=True,
        record_authorized=record,
        original_audio_authorized=original,
        translated_audio_authorized=translated,
    )


async def _session_with(manager, audio_dir, messages):
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    for message in messages:
        manager.add_message(session.key, message)
        for variant in (AudioVariant.ORIGINAL, AudioVariant.TRANSLATED):
            save_audio(session.key, message.id, variant, b"wav", base_dir=audio_dir)
    return session, session.key, manager


@pytest.fixture
async def declined_session_with_content(manager, audio_dir):
    return await _session_with(
        manager,
        audio_dir,
        [_message("m1", record=False, original=False, translated=False)],
    )


@pytest.fixture
async def granted_session_with_content(manager, audio_dir):
    return await _session_with(
        manager,
        audio_dir,
        [_message("m1", record=True, original=True, translated=True)],
    )


@pytest.fixture
async def mixed_session_with_content(manager, audio_dir):
    return await _session_with(
        manager,
        audio_dir,
        [
            _message("m1", record=True, original=True, translated=True),
            _message("m2", record=True, original=True, translated=False),
            _message("m3", record=False, original=False, translated=False),
        ],
    )


async def test_declined_session_retains_nothing(
    declined_session_with_content, audio_dir
):
    session, key, manager = declined_session_with_content
    await manager.terminate_session(key, reason="test")
    assert manager.get_session(key).messages == []
    for variant in (AudioVariant.ORIGINAL, AudioVariant.TRANSLATED):
        assert not audio_path(key, "m1", variant, base_dir=audio_dir).exists()


async def test_granted_session_retains_everything(
    granted_session_with_content, audio_dir
):
    session, key, manager = granted_session_with_content
    await manager.terminate_session(key, reason="test")
    assert len(manager.get_session(key).messages) == 1
    for variant in (AudioVariant.ORIGINAL, AudioVariant.TRANSLATED):
        assert audio_path(key, "m1", variant, base_dir=audio_dir).exists()


async def test_mixed_session_retains_only_the_authorised(
    mixed_session_with_content, audio_dir
):
    # m1 fully authorised; m2 record authorised but its translated audio
    # refused; m3 refused outright.
    session, key, manager = mixed_session_with_content
    await manager.terminate_session(key, reason="test")
    reloaded = manager.get_session(key)
    assert [m.id for m in reloaded.messages] == ["m1", "m2"]
    translated = AudioVariant.TRANSLATED
    assert audio_path(key, "m1", translated, base_dir=audio_dir).exists()
    assert not audio_path(key, "m2", translated, base_dir=audio_dir).exists()
    assert not audio_path(key, "m3", translated, base_dir=audio_dir).exists()


async def test_dropping_a_message_removes_its_audio(
    mixed_session_with_content, audio_dir
):
    session, key, manager = mixed_session_with_content
    await manager.terminate_session(key, reason="test")
    # m3's record was refused, so neither of its files may survive even though
    # nothing separately marked them.
    assert not audio_path(key, "m3", AudioVariant.ORIGINAL, base_dir=audio_dir).exists()


async def test_a_retained_message_stops_advertising_removed_audio(
    mixed_session_with_content,
):
    session, key, manager = mixed_session_with_content
    await manager.terminate_session(key, reason="test")
    retained = {m.id: m for m in manager.get_session(key).messages}
    # m2 keeps its record but lost its translated audio; still advertising it
    # would hand a listener an audio URL that 404s.
    assert retained["m2"].translated_audio_available is False
    assert retained["m1"].translated_audio_available is True


async def test_termination_is_idempotent(declined_session_with_content):
    session, key, manager = declined_session_with_content
    await manager.terminate_session(key, reason="test")
    await manager.terminate_session(key, reason="test")
    assert manager.get_session(key).messages == []


async def test_a_retained_message_stops_advertising_removed_original_audio(
    manager, audio_dir, monkeypatch
):
    """The original variant needs the same treatment as the translated one.

    `conversation_service.messages` derives `original_audio_url` from stored
    markers with no existence check, so a retained message whose original audio
    was refused would hand a listener a URL whose file is gone.
    """
    from services.api_gateway.conversation_service import conversation_service

    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    message = _message("m1", record=True, original=False, translated=True)
    message.original_audio_url = "available"
    message.pipeline_metadata = {"input": {"type": "audio"}}
    manager.add_message(session.key, message)
    for variant in (AudioVariant.ORIGINAL, AudioVariant.TRANSLATED):
        save_audio(session.key, "m1", variant, b"wav", base_dir=audio_dir)

    await manager.terminate_session(session.key, reason="test")

    retained = manager.get_session(session.key).messages[0]
    assert retained.original_audio_url is None

    monkeypatch.setattr(
        "services.api_gateway.conversation_service.session_manager", manager
    )
    monkeypatch.setattr(
        "services.api_gateway.conversation_service.audio_path",
        lambda key, mid, variant: audio_path(key, mid, variant, base_dir=audio_dir),
    )
    items = conversation_service.messages(session.key, ClientType.ADMIN)
    assert "original_audio_url" not in items[0]


async def test_a_failed_termination_leaves_the_audio_in_place(
    manager, audio_dir, monkeypatch
):
    """Deleting before the commit destroys content a retry still needs.

    Termination treats a store failure as transient: the session stays active
    and the caller retries. Files removed ahead of that commit are gone for a
    conversation that is still running.
    """
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    manager.add_message(
        session.key, _message("m1", record=False, original=False, translated=False)
    )
    for variant in (AudioVariant.ORIGINAL, AudioVariant.TRANSLATED):
        save_audio(session.key, "m1", variant, b"wav", base_dir=audio_dir)

    def _refuse(_session):
        raise SessionStoreConsistencyError("transient store failure")

    monkeypatch.setattr(manager.store, "terminate", _refuse)

    with pytest.raises(SessionStoreConsistencyError):
        await manager.terminate_session(session.key, reason="test")

    for variant in (AudioVariant.ORIGINAL, AudioVariant.TRANSLATED):
        assert audio_path(session.key, "m1", variant, base_dir=audio_dir).exists()
    # The live session still has the message it is still able to deliver.
    assert len(manager.get_session(session.key).messages) == 1
