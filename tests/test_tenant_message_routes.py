"""Trusted role assignment and tenant-owned message artifacts."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.audio_storage import AudioStore, AudioVariant, scope_pipeline_audio_urls
from services.api_gateway.message_processing import (
    broadcast_message_to_session,
    transform_pipeline_metadata,
)
from services.api_gateway.session_manager import (
    ClientType,
    TenantSessionManager,
    SessionMessage,
    SessionStatus,
)
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import (
    RuntimeConfigurationSnapshot,
    TenantSessionKey,
)
from tests.pipeline_helpers import speech_pipeline

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
def client(session_manager) -> TestClient:
    session_manager.reset(clear_persistence=True)
    return TestClient(app)


@pytest.mark.parametrize(
    ("prefix", "spoofed_role", "expected_role"),
    [
        ("admin", "customer", ClientType.ADMIN),
        ("customer", "admin", ClientType.CUSTOMER),
    ],
)
def test_message_route_uses_server_assigned_role(
    client: TestClient,
    gateway_dependencies,
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    spoofed_role: str,
    expected_role: ClientType,
) -> None:
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    process = AsyncMock(return_value={"status": "success"})
    monkeypatch.setattr(gateway_dependencies.conversation_service, "process", process)

    response = client.post(
        f"/api/{prefix}/session/{session_id}/message",
        json={
            "text": "Hallo",
            "source_lang": "de",
            "target_lang": "en",
            "client_type": spoofed_role,
        },
    )

    assert response.status_code == 200
    key, sender, _request = process.await_args.args
    assert key.tenant_id == "tenant-test"
    assert key.session_id == session_id
    assert sender is expected_role


def test_audio_lookup_requires_message_ownership(session_manager, client: TestClient) -> None:
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    other = asyncio.run(session_manager.create_admin_session("tenant-other", SNAPSHOT))
    message = SessionMessage(
        id="other-message",
        sender=ClientType.CUSTOMER,
        original_text="Hello",
        translated_text="Hallo",
        audio_base64="UklGRg==",
        source_lang="en",
        target_lang="de",
        timestamp=datetime.now(timezone.utc),
    )
    session_manager.add_message(other.key, message)

    response = client.get(f"/api/admin/session/{session_id}/audio/{message.id}/translated.wav")

    assert response.status_code == 404
    assert response.json() == {"detail": "Audio file not found"}


def test_translated_audio_is_unavailable_after_its_retained_file_is_gone(
    session_manager,
    client: TestClient,
) -> None:
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    key = session_manager.resolve_customer_session(session_id)
    assert key is not None
    session_manager.add_message(
        key,
        SessionMessage(
            id="message-1",
            sender=ClientType.CUSTOMER,
            original_text="Hello",
            translated_text="Hallo",
            audio_base64="UklGRmxlZ2FjeS1hdWRpbw==",
            source_lang="en",
            target_lang="de",
            timestamp=datetime.now(timezone.utc),
        ),
    )

    response = client.get(f"/api/admin/session/{session_id}/audio/message-1/translated.wav")

    assert response.status_code == 404
    assert response.json() == {"detail": "Audio file not found"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sender_type", "receiver_type"),
    [
        (ClientType.ADMIN, ClientType.CUSTOMER),
        (ClientType.CUSTOMER, ClientType.ADMIN),
    ],
)
async def test_live_audio_urls_are_scoped_to_each_receiving_role(
    sender_type: ClientType,
    receiver_type: ClientType,
) -> None:
    key = (
        await TenantSessionManager(
            store=MemoryTenantSessionStore(), audio_store=AudioStore.from_environment()
        ).create_admin_session("tenant-a", SNAPSHOT)
    ).key
    message = SessionMessage(
        id="message-1",
        sender=sender_type,
        original_text="Hallo",
        translated_text="Hello",
        audio_base64=None,
        source_lang="de",
        target_lang="en",
        timestamp=datetime.now(timezone.utc),
        translated_audio_available=True,
        pipeline_metadata={
            "input": {
                "type": "audio",
                "audio_url": (
                    f"/api/{sender_type.value}/session/{key.session_id}/audio/"
                    "message-1/original.wav"
                ),
            },
            "steps": [
                {
                    "name": "tts",
                    "output": {"audio_url": "/api/audio/message-1.wav"},
                }
            ],
        },
        original_audio_url=(
            f"/api/{sender_type.value}/session/{key.session_id}/audio/" "message-1/original.wav"
        ),
    )
    manager = SimpleNamespace(
        broadcast_with_differentiated_content=AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                total_connections=2,
                successful_sends=2,
                failed_sends=0,
                session_has_connections=True,
                errors=[],
            )
        )
    )

    await broadcast_message_to_session(key, message, sender_type, manager)

    sent = manager.broadcast_with_differentiated_content.await_args.kwargs
    sender_payload = sent["original_message"]
    receiver_payload = sent["translated_message"]
    assert sender_payload["original_audio_url"] == (
        f"/api/{sender_type.value}/session/{key.session_id}/audio/" "message-1/original.wav"
    )
    assert receiver_payload["original_audio_url"] == (
        f"/api/{receiver_type.value}/session/{key.session_id}/audio/" "message-1/original.wav"
    )
    assert receiver_payload["audio_url"] == (
        f"/api/{receiver_type.value}/session/{key.session_id}/audio/" "message-1/translated.wav"
    )
    assert sender_payload["pipeline_metadata"]["input"]["audio_url"] == (
        f"/api/{sender_type.value}/session/{key.session_id}/audio/" "message-1/original.wav"
    )
    assert receiver_payload["pipeline_metadata"]["input"]["audio_url"] == (
        f"/api/{receiver_type.value}/session/{key.session_id}/audio/" "message-1/original.wav"
    )
    assert receiver_payload["pipeline_metadata"]["steps"][0]["output"]["audio_url"] == (
        f"/api/{receiver_type.value}/session/{key.session_id}/audio/" "message-1/translated.wav"
    )
    assert "/api/audio/" not in repr(sent)


def test_history_audio_urls_are_scoped_to_requesting_role(
    session_manager,
    client: TestClient,
) -> None:
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    key = session_manager.resolve_customer_session(session_id)
    assert key is not None
    session_manager.add_message(
        key,
        SessionMessage(
            id="message-1",
            sender=ClientType.ADMIN,
            original_text="Hallo",
            translated_text="Hello",
            audio_base64=None,
            source_lang="de",
            target_lang="en",
            timestamp=datetime.now(timezone.utc),
            translated_audio_available=True,
            original_audio_url=(f"/api/admin/session/{session_id}/audio/message-1/original.wav"),
        ),
    )

    for role in ("admin", "customer"):
        response = client.get(f"/api/{role}/session/{session_id}/messages")

        assert response.status_code == 200
        [message] = response.json()["messages"]
        assert message["audio_url"] == (
            f"/api/{role}/session/{session_id}/audio/message-1/translated.wav"
        )
        assert message["original_audio_url"] == (
            f"/api/{role}/session/{session_id}/audio/message-1/original.wav"
        )
        assert "audio_base64" not in message
        assert "/api/audio/" not in repr(message)


def test_persisted_pipeline_metadata_contains_no_reusable_audio_url() -> None:
    key = TenantSessionKey("tenant-a", "ABC12345")
    metadata = transform_pipeline_metadata(
        {
            "steps": [{"name": "tts", "output": "audio/wav"}],
            "total_duration_ms": 1,
        },
        source_lang="de",
        target_lang="en",
        original_audio_url="/api/audio/input-message-1.wav",
        message_id="message-1",
    )

    assert metadata is not None
    assert metadata["input"]["type"] == "audio"
    assert "/api/audio/" not in repr(metadata)
    assert "audio_url" not in metadata["input"]
    assert "audio_url" not in metadata["steps"][0]["output"]

    scoped = scope_pipeline_audio_urls(metadata, key, ClientType.ADMIN.value, "message-1")
    assert scoped is not None
    assert scoped["input"]["audio_url"] == (
        "/api/admin/session/ABC12345/audio/message-1/original.wav"
    )
    assert scoped["steps"][0]["output"]["audio_url"] == (
        "/api/admin/session/ABC12345/audio/message-1/translated.wav"
    )


class RecordingAudioStore(AudioStore):
    """Records every write instead of touching the disk."""

    def __init__(self) -> None:
        super().__init__(Path("/nonexistent"))
        self.saved: list[tuple[TenantSessionKey, str, AudioVariant, bytes]] = []

    def save(
        self, key: TenantSessionKey, message_id: str, variant: AudioVariant, data: bytes
    ) -> Path:
        self.saved.append((key, message_id, variant, data))
        return self.path(key, message_id, variant)


def test_audio_storage_reports_availability_without_persisting_a_role_url() -> None:
    from services.api_gateway import message_processing

    store = RecordingAudioStore()
    key = TenantSessionKey("tenant-a", "ABC12345")

    available = message_processing._store_audio_artifacts(
        key,
        ClientType.ADMIN,
        "message-1",
        b"original",
        audio_store=store,
    )

    assert available is True
    assert store.saved == [(key, "message-1", AudioVariant.ORIGINAL, b"original")]


@pytest.mark.asyncio
async def test_created_message_persists_translated_audio_without_retaining_bytes() -> None:
    from services.api_gateway import message_processing

    store = RecordingAudioStore()
    manager = TenantSessionManager(store=MemoryTenantSessionStore(), audio_store=store)
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)

    message = await message_processing.create_session_message(
        session_id=session.key,
        client_type=ClientType.ADMIN,
        original_text="Hallo",
        translated_text="Hello",
        audio_bytes=b"translated",
        source_lang="de",
        target_lang="en",
        message_id="message-1",
        sessions=manager,
        audio_store=store,
    )

    assert store.saved == [(session.key, "message-1", AudioVariant.TRANSLATED, b"translated")]
    assert message.audio_base64 is None
    assert message.translated_audio_available is True


@pytest.mark.parametrize("variant", ["original", "translated"])
def test_terminal_session_denies_all_admin_audio_variants(
    gateway_dependencies,
    session_manager,
    client: TestClient,
    variant: str,
) -> None:
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    key = session_manager.resolve_customer_session(session_id)
    assert key is not None
    message = SessionMessage(
        id="message-1",
        sender=ClientType.CUSTOMER,
        original_text="Hello",
        translated_text="Hallo",
        audio_base64="UklGRg==",
        source_lang="en",
        target_lang="de",
        timestamp=datetime.now(timezone.utc),
    )
    session_manager.add_message(key, message)
    original = gateway_dependencies.audio_store.save(
        key, "message-1", AudioVariant(variant), b"RIFForiginal"
    )
    session = session_manager.get_session(key)
    assert session is not None
    session.status = SessionStatus.TERMINATED

    response = client.get(f"/api/admin/session/{session_id}/audio/message-1/{variant}.wav")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}
    assert original.exists()


def test_openapi_exposes_only_role_specific_message_and_audio_routes() -> None:
    paths = app.openapi()["paths"]

    assert "/api/session/{session_id}/message" not in paths
    assert "/api/session/{session_id}/messages" not in paths
    assert "/api/audio/{message_id}.wav" not in paths
    assert "/api/audio/input_{message_id}.wav" not in paths
    assert "/api/admin/session/{session_id}/message" in paths
    assert "/api/customer/session/{session_id}/message" in paths


@pytest.mark.asyncio
async def test_text_processing_ignores_a_spoofed_client_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.api_gateway import message_processing

    manager = TenantSessionManager(
        store=MemoryTenantSessionStore(), audio_store=AudioStore.from_environment()
    )
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    session.status = SessionStatus.ACTIVE
    session.customer_language = "en"
    manager.store.save(session)
    monkeypatch.setattr(
        message_processing,
        "run_pipeline",
        AsyncMock(
            return_value={
                "error": False,
                "asr_text": "Hallo",
                "translation_text": "Hello",
                "audio_bytes": None,
                "debug": None,
            }
        ),
    )
    request = AsyncMock()
    # A real mapping: an AsyncMock would hand the route a coroutine where the
    # correlation header should be.
    request.headers = {}
    request.json.return_value = {
        "text": "Hallo",
        "source_lang": "de",
        "target_lang": "en",
        "client_type": "customer",
    }

    await message_processing.process_text_input(
        session.key,
        ClientType.ADMIN,
        request,
        0.0,
        sessions=manager,
        pipeline=speech_pipeline(),
        audio_store=manager.audio_store,
    )

    assert manager.get_session(session.key).messages[-1].sender is ClientType.ADMIN
