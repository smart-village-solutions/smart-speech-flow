"""A message's audio carries the retention its session captured with granted consent."""

import json
import time
from pathlib import Path

import pytest

from services.api_gateway import message_processing
from services.api_gateway.audio_storage import RETENTION_MARKER, AudioStore
from services.api_gateway.consent import ConsentStatus
from services.api_gateway.content_retention import captured_retention_hours
from services.api_gateway.session_manager import TenantSessionManager
from services.api_gateway.session_models import ClientType
from services.api_gateway.session_store import MemoryTenantSessionStore

REVISION = f"sha256:{'a' * 64}"


@pytest.fixture
def audio_store(tmp_path: Path) -> AudioStore:
    return AudioStore(tmp_path)


@pytest.fixture
def manager(audio_store: AudioStore) -> TenantSessionManager:
    return TenantSessionManager(store=MemoryTenantSessionStore(), audio_store=audio_store)


async def _voice_message(manager, audio_store, *, consent: ConsentStatus, hours: int | None):
    session = await manager.create_admin_session("tenant-test", REVISION)
    session.consent_status = consent
    session.consent_retention_hours = hours
    await message_processing._complete_message(
        key=session.key,
        client_type=ClientType.CUSTOMER,
        result={"translation_text": "hello", "audio_bytes": b"RIFF-translated"},
        source_lang="de",
        target_lang="en",
        original_text="hallo",
        original_audio=b"RIFF-original",
        pipeline_type="audio",
        manager=None,
        correlation_id="test-correlation",
        sessions=manager,
        audio_store=audio_store,
        start_time=time.time(),
        retention_hours=captured_retention_hours(session),
    )
    return audio_store.base_dir / "v2" / session.key.tenant_ref / session.id


@pytest.mark.parametrize("hours", [4320, 0])
async def test_a_granted_sessions_audio_gets_the_captured_retention(manager, audio_store, hours):
    session_dir = await _voice_message(
        manager, audio_store, consent=ConsentStatus.GRANTED, hours=hours
    )

    assert len(list(session_dir.rglob("*.wav"))) == 2
    marker = session_dir / RETENTION_MARKER
    assert json.loads(marker.read_text(encoding="utf-8")) == {"hours": hours}


@pytest.mark.parametrize(
    ("consent", "hours"),
    [
        (ConsentStatus.DECLINED, None),
        (ConsentStatus.PENDING, None),
        (ConsentStatus.POLICY_DISABLED, None),
        # Granted before the capture existed: the short default, so no marker.
        (ConsentStatus.GRANTED, None),
    ],
)
async def test_audio_without_a_captured_retention_gets_no_marker(
    manager, audio_store, consent, hours
):
    session_dir = await _voice_message(manager, audio_store, consent=consent, hours=hours)

    assert len(list(session_dir.rglob("*.wav"))) == 2
    assert not (session_dir / RETENTION_MARKER).exists()


async def test_a_text_message_writes_the_marker_of_its_granted_session(
    manager, audio_store, monkeypatch
):
    """Through the caller: the session it already holds supplies the hours."""
    from starlette.requests import Request

    from tests.pipeline_helpers import speech_pipeline

    def translated(text, source_lang, target_lang, **_kwargs):
        return {"translation_text": "hello", "audio_bytes": b"RIFF-translated", "debug": {}}

    monkeypatch.setattr(message_processing, "process_text_pipeline", translated)
    session = await manager.create_admin_session("tenant-test", REVISION)
    session.customer_language = "en"
    session.consent_status = ConsentStatus.GRANTED
    session.consent_retention_hours = 4320
    body = json.dumps({"text": "hallo", "source_lang": "de", "target_lang": "en"}).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {"type": "http", "method": "POST", "headers": [(b"content-type", b"application/json")]},
        receive,
    )
    await message_processing.process_text_input(
        session.key,
        ClientType.ADMIN,
        request,
        time.time(),
        sessions=manager,
        pipeline=speech_pipeline(),
        audio_store=audio_store,
    )

    session_dir = audio_store.base_dir / "v2" / session.key.tenant_ref / session.id
    assert json.loads((session_dir / RETENTION_MARKER).read_text()) == {"hours": 4320}
