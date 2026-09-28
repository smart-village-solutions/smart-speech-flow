"""The message-history response must not leak the authorization outcome."""

from datetime import datetime, timezone

import pytest

from services.api_gateway.conversation_service import ConversationService
from services.api_gateway.session_manager import (
    ClientType,
    SessionMessage,
)
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot
from tests.pipeline_helpers import speech_pipeline

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
async def granted_session_with_message(session_manager):
    session_manager.reset(clear_persistence=True)
    session = await session_manager.create_admin_session("tenant-test", SNAPSHOT)
    session_manager.add_message(
        session.key,
        SessionMessage(
            id="m1",
            sender=ClientType.CUSTOMER,
            original_text="hallo",
            translated_text="hello",
            audio_base64=None,
            source_lang="de",
            target_lang="en",
            timestamp=datetime.now(timezone.utc),
            record_authorized=True,
            translated_audio_authorized=True,
        ),
    )
    return session.key, ClientType.ADMIN


async def test_history_response_has_no_authorization_field(
    session_manager,
    granted_session_with_message,
):
    key, role = granted_session_with_message
    items = ConversationService(session_manager, pipeline=speech_pipeline()).messages(key, role)
    assert items
    for item in items:
        assert "record_authorized" not in item
        assert "original_audio_authorized" not in item
        assert "translated_audio_authorized" not in item
