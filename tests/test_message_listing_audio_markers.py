"""Message listings advertise audio from the markers the writer recorded, never from a stat."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.api_gateway.audio_storage import AudioStore, AudioVariant
from services.api_gateway.conversation_service import ConversationService
from services.api_gateway.session_manager import ClientType, TenantSessionManager, SessionMessage
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey
from tests.pipeline_helpers import speech_pipeline

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


class UndeletableAudioStore(AudioStore):
    """Every removal fails, as an unlink refused by the filesystem does."""

    def delete(self, *_args: object, **_kwargs: object) -> bool:
        return False


@pytest.fixture
def audio_store(tmp_path: Path) -> AudioStore:
    return AudioStore(tmp_path)


@pytest.fixture
def manager(audio_store: AudioStore) -> TenantSessionManager:
    return TenantSessionManager(store=MemoryTenantSessionStore(), audio_store=audio_store)


def _conversations(manager: TenantSessionManager) -> ConversationService:
    return ConversationService(
        manager, pipeline=speech_pipeline(), audio_store=manager.audio_store
    )


def _audio_message(
    *, original_authorized: bool = True, translated_authorized: bool = True
) -> SessionMessage:
    return SessionMessage(
        id="m1",
        sender=ClientType.CUSTOMER,
        original_text="hallo",
        translated_text="hello",
        audio_base64=None,
        source_lang="de",
        target_lang="en",
        timestamp=datetime.now(timezone.utc),
        translated_audio_available=True,
        pipeline_metadata={"input": {"type": "audio", "source_lang": "de"}, "steps": []},
        original_audio_url="available",
        record_authorized=True,
        original_audio_authorized=original_authorized,
        translated_audio_authorized=translated_authorized,
    )


def _list_without_filesystem(
    manager: TenantSessionManager, key: TenantSessionKey, role: ClientType
) -> list[dict[str, object]]:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("listing messages must not touch the filesystem")

    with pytest.MonkeyPatch.context() as patch:
        for name in ("is_file", "exists", "stat"):
            patch.setattr(Path, name, refuse)
        return _conversations(manager).messages(key, role)


def _save_both(key: TenantSessionKey, audio_store: AudioStore) -> None:
    for variant in AudioVariant:
        audio_store.save(key, "m1", variant, b"wav")


async def test_listing_advertises_recorded_audio_without_a_filesystem_stat(
    manager: TenantSessionManager, audio_store: AudioStore
) -> None:
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    manager.add_message(session.key, _audio_message())

    [item] = _list_without_filesystem(manager, session.key, ClientType.ADMIN)

    base = f"/api/admin/session/{session.id}/audio/m1"
    assert item["audio_url"] == f"{base}/translated.wav"
    assert item["original_audio_url"] == f"{base}/original.wav"


async def test_listing_advertises_no_audio_for_a_message_without_markers(
    manager: TenantSessionManager, audio_store: AudioStore
) -> None:
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    message = _audio_message()
    message.translated_audio_available = False
    message.original_audio_url = None
    message.pipeline_metadata = None
    manager.add_message(session.key, message)

    [item] = _list_without_filesystem(manager, session.key, ClientType.CUSTOMER)

    assert "audio_url" not in item
    assert "original_audio_url" not in item


async def test_settled_refused_audio_is_not_advertised_even_if_its_file_survives(
    tmp_path: Path,
) -> None:
    """A failed unlink after settlement must not bring the refused audio back into view."""
    audio_store = UndeletableAudioStore(tmp_path)
    manager = TenantSessionManager(store=MemoryTenantSessionStore(), audio_store=audio_store)
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    manager.add_message(
        session.key, _audio_message(original_authorized=False, translated_authorized=False)
    )
    _save_both(session.key, audio_store)

    await manager.terminate_session(session.key, reason="test")

    assert audio_store.path(session.key, "m1", AudioVariant.TRANSLATED).is_file()
    [retained] = manager.get_session(session.key).messages
    assert retained.translated_audio_available is False
    assert retained.original_audio_url is None
    [item] = _conversations(manager).messages(session.key, ClientType.ADMIN)
    assert "audio_url" not in item
    assert "original_audio_url" not in item
    assert "audio_url" not in repr(item.get("pipeline_metadata"))


async def test_the_content_sweep_clears_the_markers_it_settles(
    manager: TenantSessionManager, audio_store: AudioStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "0")
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    manager.add_message(
        session.key, _audio_message(original_authorized=False, translated_authorized=False)
    )
    past_lifetime = session.created_at + timedelta(hours=session.maximum_lifetime_hours)

    manager.sweep_expired_content(past_lifetime)

    [item] = _list_without_filesystem(manager, session.key, ClientType.ADMIN)
    assert "audio_url" not in item
    assert "original_audio_url" not in item
    assert "audio_url" not in repr(item.get("pipeline_metadata"))


async def test_serving_audio_still_checks_that_the_file_exists(
    manager: TenantSessionManager, audio_store: AudioStore
) -> None:
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    manager.add_message(session.key, _audio_message())

    with pytest.raises(HTTPException) as missing:
        _conversations(manager).audio(session.key, "m1", AudioVariant.TRANSLATED)

    assert missing.value.status_code == 404
