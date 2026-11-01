"""The message-history response carries the public message fields and nothing else."""

from datetime import datetime, timezone

import pytest

from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.conversation_service import ConversationService
from services.api_gateway.session_models import ClientType, SessionMessage
from tests.pipeline_helpers import speech_pipeline

REVISION = f"sha256:{'a' * 64}"


@pytest.fixture
async def session_with_message(session_manager):
    session_manager.reset(clear_persistence=True)
    session = await session_manager.create_admin_session("tenant-test", REVISION)
    await session_manager.add_message(
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
        ),
    )
    return session.key, ClientType.ADMIN


async def test_history_response_holds_only_the_public_message_fields(
    session_manager,
    session_with_message,
):
    key, role = session_with_message
    items = await ConversationService(
        session_manager,
        pipeline=speech_pipeline(),
        audio_store=AudioStore.from_environment(),
    ).messages(key, role)
    assert items
    for item in items:
        assert set(item) == {
            "id",
            "sender",
            "original_text",
            "translated_text",
            "source_lang",
            "target_lang",
            "timestamp",
            "translated_audio_available",
        }
