"""ConversationService owns message processing and the collaborators it needs (#347 §2)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway import message_processing
from services.api_gateway.dependencies import build_gateway_dependencies
from services.api_gateway.session_manager import ClientType, SessionStatus, TenantSessionManager
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey
from services.api_gateway.websocket import BroadcastResult

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")
PIPELINE_SUCCESS = {
    "error": False,
    "asr_text": "Guten Tag",
    "translation_text": "Good day",
    "audio_bytes": None,
    "debug": None,
}


def _text_request() -> Mock:
    request = Mock()
    request.headers = {"content-type": "application/json"}
    request.json = AsyncMock(
        return_value={"text": "Guten Tag", "source_lang": "de", "target_lang": "en"}
    )
    return request


async def _active_session(sessions: TenantSessionManager) -> TenantSessionKey:
    session = await sessions.create_admin_session("tenant-a", SNAPSHOT)
    session.status = SessionStatus.ACTIVE
    session.customer_language = "en"
    sessions.store.save(session)
    return session.key


async def test_the_container_wires_its_own_socket_manager_into_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = build_gateway_dependencies(prometheus_registry=CollectorRegistry())
    key = await _active_session(dependencies.session_manager)
    broadcast = AsyncMock(
        return_value=BroadcastResult(
            success=True,
            total_connections=0,
            successful_sends=0,
            failed_sends=0,
            session_has_connections=False,
            errors=[],
        )
    )
    monkeypatch.setattr(
        dependencies.websocket_manager, "broadcast_with_differentiated_content", broadcast
    )
    monkeypatch.setattr(
        message_processing, "run_pipeline", AsyncMock(return_value=dict(PIPELINE_SUCCESS))
    )

    response = await dependencies.conversation_service.process(
        key, ClientType.ADMIN, _text_request()
    )

    assert response.status == "success"
    assert broadcast.await_args is not None
    assert broadcast.await_args.kwargs["session_id"] == key
    assert [m.id for m in dependencies.session_manager.get_session(key).messages] == [
        response.message_id
    ]


async def test_a_failed_broadcast_is_logged_as_a_failure_not_as_a_crash(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sessions = TenantSessionManager(store=MemoryTenantSessionStore())
    key = await _active_session(sessions)
    failed = BroadcastResult(
        success=False,
        total_connections=2,
        successful_sends=1,
        failed_sends=1,
        session_has_connections=True,
        errors=["closed"],
    )
    monkeypatch.setattr(
        message_processing, "broadcast_message_to_session", AsyncMock(return_value=failed)
    )

    with caplog.at_level(logging.ERROR, logger=message_processing.logger.name):
        await message_processing.create_session_message(
            session_id=key,
            client_type=ClientType.ADMIN,
            original_text="Hallo",
            translated_text="Hello",
            audio_bytes=None,
            source_lang="de",
            target_lang="en",
            manager=Mock(),
            sessions=sessions,
        )

    messages = [record.getMessage() for record in caplog.records]
    assert any("WebSocket-Broadcasting fehlgeschlagen" in text for text in messages), messages
    assert not any("WebSocket-Broadcasting-Fehler" in text for text in messages), messages
