"""Trusted role assignment and tenant-owned message artifacts."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.conversation_service import conversation_service
from services.api_gateway.session_manager import (
    ClientType,
    SessionMessage,
    SessionManager,
    SessionStatus,
    session_manager,
)
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
def client() -> TestClient:
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
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    spoofed_role: str,
    expected_role: ClientType,
) -> None:
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    process = AsyncMock(return_value={"status": "success"})
    monkeypatch.setattr(conversation_service, "process", process)

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
    key, sender, _request, _manager = process.await_args.args
    assert key.tenant_id == "tenant-test"
    assert key.session_id == session_id
    assert sender is expected_role


def test_audio_lookup_requires_message_ownership(client: TestClient) -> None:
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
    from services.api_gateway.routes import session as session_routes

    manager = SessionManager(store=MemoryTenantSessionStore())
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    session.status = SessionStatus.ACTIVE
    session.customer_language = "en"
    manager.store.save(session)
    monkeypatch.setattr(session_routes, "session_manager", manager)
    monkeypatch.setattr(
        session_routes,
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
    request.json.return_value = {
        "text": "Hallo",
        "source_lang": "de",
        "target_lang": "en",
        "client_type": "customer",
    }

    await session_routes.process_text_input(
        session.key,
        ClientType.ADMIN,
        request,
        0.0,
    )

    assert manager.get_session(session.key).messages[-1].sender is ClientType.ADMIN
