"""No policy read may be awaited before the participant sees their result."""

import asyncio
from pathlib import Path

import pytest

from services.api_gateway import audio_storage
from services.api_gateway.audio_storage import AudioVariant, audio_path
from services.api_gateway.consent import ConsentStatus
from services.api_gateway.routes import session as session_routes
from services.api_gateway.runtime_policy import (
    PolicyDecision,
    PolicyReason,
    bind_runtime_policy,
)
from services.api_gateway.session_manager import ClientType, session_manager
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
def audio_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect every audio write below the test's own directory."""
    real_save = audio_storage.save_audio

    def save(key, message_id, variant, data, *, base_dir=None):
        return real_save(key, message_id, variant, data, base_dir=tmp_path)

    monkeypatch.setattr(audio_storage, "save_audio", save)
    return tmp_path


async def _session_with_consent(status: ConsentStatus):
    session_manager.reset(clear_persistence=True)
    session = await session_manager.create_admin_session("tenant-test", SNAPSHOT)
    session.consent_status = status
    session_manager.store.save(session)
    return session.key


async def test_broadcast_precedes_every_policy_read(monkeypatch, audio_dir):
    # The read blocks until the test releases it. If it were awaited before the
    # broadcast, the broadcast would never happen and the wait below times out.
    released = asyncio.Event()
    broadcast_seen = asyncio.Event()

    class _BlockingGate:
        async def authorize(self, tenant_id, consent_status, correlation_id):
            await released.wait()
            return PolicyDecision(True, PolicyReason.GRANTED)

    async def _broadcast(*args, **kwargs):
        broadcast_seen.set()

        class _Result:
            success = True
            total_connections = 0
            successful_sends = 0
            failed_sends = 0
            errors: list = []

        return _Result()

    monkeypatch.setattr(session_routes, "broadcast_message_to_session", _broadcast)
    bind_runtime_policy(_BlockingGate())
    key = await _session_with_consent(ConsentStatus.GRANTED)

    task = asyncio.create_task(
        session_routes.create_session_message(
            key,
            ClientType.CUSTOMER,
            "hallo",
            "hello",
            b"audio-bytes",
            "de",
            "en",
            manager=object(),
        )
    )
    try:
        await asyncio.wait_for(broadcast_seen.wait(), timeout=1.0)
        assert not task.done(), "the policy read completed before the broadcast"
    finally:
        released.set()
        await task


async def test_declined_session_still_gets_playable_audio(audio_dir):
    class _RefusingGate:
        async def authorize(self, tenant_id, consent_status, correlation_id):
            return PolicyDecision(False, PolicyReason.CONSENT_DECLINED)

    bind_runtime_policy(_RefusingGate())
    key = await _session_with_consent(ConsentStatus.DECLINED)

    message = await session_routes.create_session_message(
        key,
        ClientType.CUSTOMER,
        "hallo",
        "hello",
        b"audio-bytes",
        "de",
        "en",
    )

    # Live delivery is untouched: the response builder reads exactly this flag
    # to decide whether to hand the listener an audio URL.
    assert message.translated_audio_available is True
    saved = audio_path(
        key, message.id, AudioVariant.TRANSLATED, base_dir=audio_dir
    )
    assert saved.is_file()
    # The outcome is recorded as refused, for removal at termination.
    assert message.record_authorized is False
    assert message.translated_audio_authorized is False
