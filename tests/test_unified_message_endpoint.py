"""Focused tests for the role-specific unified message pipeline."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.api_gateway import message_models, message_processing
from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.session_manager import ClientType, TenantSessionManager, SessionStatus
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot
from tests.pipeline_helpers import speech_pipeline

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
async def active_session(monkeypatch: pytest.MonkeyPatch):
    manager = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=AudioStore.from_environment(),
    )
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    session.status = SessionStatus.ACTIVE
    session.customer_language = "en"
    manager.store.save(session)
    return manager, session


def test_text_request_has_no_client_controlled_role() -> None:
    request = message_models.TextMessageRequest(
        text=" Hallo ",
        source_lang="de",
        target_lang="en",
        client_type="customer",
    )

    assert request.text == "Hallo"
    assert not hasattr(request, "client_type")


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_text_request_rejects_invalid_content(text: str) -> None:
    with pytest.raises(ValueError):
        message_models.TextMessageRequest(
            text=text,
            source_lang="de",
            target_lang="en",
        )


@pytest.mark.asyncio
async def test_unified_message_dispatches_json_with_trusted_role(
    active_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, session = active_session
    expected = message_models.MessageResponse(
        status="success",
        message_id="message-1",
        session_id=session.id,
        original_text="Hallo",
        translated_text="Hello",
        audio_available=False,
        processing_time_ms=1,
        pipeline_type="text",
        source_lang="de",
        target_lang="en",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    process = AsyncMock(return_value=expected)
    monkeypatch.setattr(message_processing, "process_text_input", process)
    request = AsyncMock()
    request.headers = {"content-type": "application/json"}

    result = await message_processing.send_unified_message(
        session.key,
        ClientType.ADMIN,
        request,
        None,
        sessions=manager,
        pipeline=speech_pipeline(),
        audio_store=AudioStore.from_environment(),
    )

    assert result == expected
    assert process.await_args.args[:2] == (session.key, ClientType.ADMIN)


@pytest.mark.asyncio
async def test_unified_message_rejects_unsupported_content_type(active_session) -> None:
    manager, session = active_session
    request = AsyncMock()
    request.headers = {"content-type": "text/plain"}

    with pytest.raises(HTTPException) as caught:
        await message_processing.send_unified_message(
            session.key,
            ClientType.ADMIN,
            request,
            None,
            sessions=manager,
            pipeline=speech_pipeline(),
            audio_store=AudioStore.from_environment(),
        )

    assert caught.value.status_code == 400
    assert caught.value.detail["error_code"] == "UNSUPPORTED_CONTENT_TYPE"


@pytest.mark.asyncio
async def test_unified_message_redacts_unexpected_exception_from_response_and_output(
    active_session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manager, session = active_session
    request = AsyncMock()
    request.headers = {"content-type": "application/json"}
    secret = "private-upstream-exception"
    monkeypatch.setattr(
        message_processing,
        "process_text_input",
        AsyncMock(side_effect=RuntimeError(secret)),
    )

    with pytest.raises(HTTPException) as caught:
        await message_processing.send_unified_message(
            session.key,
            ClientType.ADMIN,
            request,
            None,
            sessions=manager,
            pipeline=speech_pipeline(),
            audio_store=AudioStore.from_environment(),
        )

    captured = capsys.readouterr()
    assert caught.value.status_code == 500
    assert caught.value.detail["error_message"] == "Message processing failed"
    assert secret not in repr(caught.value.detail)
    assert secret not in captured.out + captured.err


@pytest.mark.asyncio
async def test_audio_pipeline_requires_only_file_and_languages(active_session) -> None:
    manager, session = active_session
    request = AsyncMock()
    # A real mapping: an AsyncMock would hand the route a coroutine where the
    # correlation header should be.
    request.headers = {}
    request.form.return_value = {"source_lang": "de", "target_lang": "en"}

    with pytest.raises(HTTPException) as caught:
        await message_processing.process_audio_input(
            session.key,
            ClientType.ADMIN,
            request,
            0.0,
            sessions=manager,
            pipeline=speech_pipeline(),
            audio_store=AudioStore.from_environment(),
        )

    assert caught.value.status_code == 400
    assert caught.value.detail["details"]["missing_fields"] == ["file"]


@pytest.mark.asyncio
async def test_create_message_persists_under_the_complete_tenant_key(
    active_session,
) -> None:
    manager, session = active_session

    message = await message_processing.create_session_message(
        session.key,
        ClientType.CUSTOMER,
        "Hello",
        "Hallo",
        None,
        "en",
        "de",
        sessions=manager,
        audio_store=AudioStore.from_environment(),
    )

    stored = manager.get_session(session.key)
    assert stored.messages[-1] == message
    assert stored.messages[-1].sender is ClientType.CUSTOMER
