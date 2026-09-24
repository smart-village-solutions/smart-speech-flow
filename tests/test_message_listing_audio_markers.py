"""Message listings advertise audio from the markers the writer recorded, never from a stat."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.api_gateway import audio_storage
from services.api_gateway.audio_storage import AudioVariant, audio_path, save_audio
from services.api_gateway.conversation_service import ConversationService
from services.api_gateway.session_manager import ClientType, TenantSessionManager, SessionMessage
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
def manager() -> TenantSessionManager:
    return TenantSessionManager(store=MemoryTenantSessionStore())


@pytest.fixture
def audio_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point every audio path the gateway derives at this test's directory."""
    monkeypatch.setattr(
        "services.api_gateway.conversation_service.audio_path",
        lambda key, message_id, variant: audio_path(key, message_id, variant, base_dir=tmp_path),
    )
    return tmp_path


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
        return ConversationService(manager).messages(key, role)


def _save_both(key: TenantSessionKey, audio_dir: Path) -> None:
    for variant in AudioVariant:
        save_audio(key, "m1", variant, b"wav", base_dir=audio_dir)


async def test_listing_advertises_recorded_audio_without_a_filesystem_stat(
    manager: TenantSessionManager, audio_dir: Path
) -> None:
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    manager.add_message(session.key, _audio_message())

    [item] = _list_without_filesystem(manager, session.key, ClientType.ADMIN)

    base = f"/api/admin/session/{session.id}/audio/m1"
    assert item["audio_url"] == f"{base}/translated.wav"
    assert item["original_audio_url"] == f"{base}/original.wav"


async def test_listing_advertises_no_audio_for_a_message_without_markers(
    manager: TenantSessionManager, audio_dir: Path
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
    manager: TenantSessionManager, audio_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed unlink after settlement must not bring the refused audio back into view."""
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    manager.add_message(
        session.key, _audio_message(original_authorized=False, translated_authorized=False)
    )
    _save_both(session.key, audio_dir)
    monkeypatch.setattr(audio_storage, "delete_message_audio", lambda *_args, **_kwargs: False)

    await manager.terminate_session(session.key, reason="test")

    [retained] = manager.get_session(session.key).messages
    assert retained.translated_audio_available is False
    assert retained.original_audio_url is None
    [item] = ConversationService(manager).messages(session.key, ClientType.ADMIN)
    assert "audio_url" not in item
    assert "original_audio_url" not in item
    assert "audio_url" not in repr(item.get("pipeline_metadata"))


async def test_the_content_sweep_clears_the_markers_it_settles(
    manager: TenantSessionManager, audio_dir: Path, monkeypatch: pytest.MonkeyPatch
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
    manager: TenantSessionManager, audio_dir: Path
) -> None:
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    manager.add_message(session.key, _audio_message())

    with pytest.raises(HTTPException) as missing:
        ConversationService(manager).audio(session.key, "m1", AudioVariant.TRANSLATED)

    assert missing.value.status_code == 404
