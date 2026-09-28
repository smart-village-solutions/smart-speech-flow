"""No policy read may be awaited before the result is delivered.

Scope, precisely: the broadcast to the receiving participant precedes every
read. The sender's own HTTP acknowledgement does complete after its message's
reads -- deliberate, and recorded in the tracked spec.
"""

import asyncio
from pathlib import Path

import pytest

from services.api_gateway.audio_storage import AudioStore, AudioVariant
from services.api_gateway.consent import ConsentStatus
from services.api_gateway import message_processing
from services.api_gateway.runtime_policy import PolicyDecision, PolicyReason
from services.api_gateway.session_manager import ClientType
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
def audio_store(tmp_path: Path) -> AudioStore:
    """Every audio write lands below the test's own directory."""
    return AudioStore(tmp_path)


async def _session_with_consent(session_manager, status: ConsentStatus):
    session_manager.reset(clear_persistence=True)
    session = await session_manager.create_admin_session("tenant-test", SNAPSHOT)
    session.consent_status = status
    session_manager.store.save(session)
    return session.key


async def test_broadcast_precedes_every_policy_read(session_manager, monkeypatch):
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

    monkeypatch.setattr(message_processing, "broadcast_message_to_session", _broadcast)
    session_manager.runtime_policy = _BlockingGate()
    key = await _session_with_consent(session_manager, ConsentStatus.GRANTED)

    task = asyncio.create_task(
        message_processing.create_session_message(
            key,
            ClientType.CUSTOMER,
            "hallo",
            "hello",
            "de",
            "en",
            manager=object(),
            sessions=session_manager,
            translated_audio_available=True,
        )
    )
    try:
        await asyncio.wait_for(broadcast_seen.wait(), timeout=1.0)
        assert not task.done(), "the policy read completed before the broadcast"
    finally:
        released.set()
        await task


async def test_declined_session_still_gets_playable_audio(session_manager, audio_store):
    class _RefusingGate:
        async def authorize(self, tenant_id, consent_status, correlation_id):
            return PolicyDecision(False, PolicyReason.CONSENT_DECLINED)

    session_manager.runtime_policy = _RefusingGate()
    key = await _session_with_consent(session_manager, ConsentStatus.DECLINED)

    available = message_processing._store_translated_audio(
        key, "m1", b"audio-bytes", audio_store=audio_store
    )
    message = await message_processing.create_session_message(
        key,
        ClientType.CUSTOMER,
        "hallo",
        "hello",
        "de",
        "en",
        message_id="m1",
        sessions=session_manager,
        translated_audio_available=available,
    )

    # Live delivery is untouched: the response builder reads exactly this flag
    # to decide whether to hand the listener an audio URL.
    assert message.translated_audio_available is True
    saved = audio_store.path(key, "m1", AudioVariant.TRANSLATED)
    assert saved.is_file()
    # The outcome is recorded as refused, for removal at termination.
    assert message.record_authorized is False
    assert message.translated_audio_authorized is False


async def test_a_terminated_session_does_not_fail_a_delivered_message(
    monkeypatch, session_manager
):
    """Recording the outcome must not fail a request already served.

    The policy reads open a window in which the admin can terminate. Redis then
    refuses the write-back, and raising here would 500 a message the other
    party already received over the WebSocket -- a retry would duplicate it.
    """
    from services.api_gateway.session_store import SessionStoreConsistencyError

    class _Granting:
        async def authorize(self, tenant_id, consent_status, correlation_id):
            return PolicyDecision(True, PolicyReason.GRANTED)

    session_manager.runtime_policy = _Granting()
    key = await _session_with_consent(session_manager, ConsentStatus.GRANTED)

    # Only the write-back that follows the policy reads, not the delivery
    # write that precedes them: the pre-existing `add_message` exposure is a
    # window of microseconds and is not what this covers.
    def _refuse(*_args, **_kwargs):
        raise SessionStoreConsistencyError("session lifecycle does not permit save")

    monkeypatch.setattr(
        session_manager, "record_message_authorization", _refuse
    )

    message = await message_processing.create_session_message(
        key,
        ClientType.CUSTOMER,
        "hallo",
        "hello",
        "de",
        "en",
        sessions=session_manager,
        translated_audio_available=True,
    )

    assert message.translated_audio_available is True


async def test_the_production_default_refuses_when_no_gate_is_bound(session_manager):
    """conftest sets a permissive gate for every suite; this asserts the real
    default it hides.

    An unbound gate is what a process with no Studio configuration runs with,
    and it must retain nothing.
    """
    session_manager.runtime_policy = None
    key = await _session_with_consent(session_manager, ConsentStatus.GRANTED)

    message = await message_processing.create_session_message(
        key,
        ClientType.CUSTOMER,
        "hallo",
        "hello",
        "de",
        "en",
        sessions=session_manager,
        translated_audio_available=True,
    )

    assert message.record_authorized is False
    assert message.original_audio_authorized is False
    assert message.translated_audio_authorized is False
    # And the conversation itself is untouched.
    assert message.translated_audio_available is True
