"""A message survives a failed audio write, and the failure is not silent.

Production spent months answering every conversation with text and no audio:
the audio volume was root-owned, `save_audio` raised PermissionError on every
message, and the only trace was a warning nobody read while the request still
reported success. These tests pin both halves of the contract -- the customer
keeps their message, and the loss is logged loudly enough to find.
"""

import logging

import pytest

from services.api_gateway import audio_storage
from services.api_gateway.consent import ConsentStatus
from services.api_gateway.routes import session as session_routes
from services.api_gateway.session_manager import ClientType
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
def refusing_audio_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every write fails the way a root-owned volume makes it fail."""

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied", "/data/audio")

    monkeypatch.setattr(audio_storage, "save_audio", refuse)


async def _session(session_manager) -> object:
    session_manager.reset(clear_persistence=True)
    session = await session_manager.create_admin_session("tenant-test", SNAPSHOT)
    session.consent_status = ConsentStatus.GRANTED
    session_manager.store.save(session)
    return session.key


async def test_a_failed_translated_audio_write_still_delivers_the_message(
    refusing_audio_storage, caplog, session_manager
):
    key = await _session(session_manager)

    with caplog.at_level(logging.ERROR, logger=session_routes.logger.name):
        message = await session_routes.create_session_message(
            key,
            ClientType.CUSTOMER,
            "hallo",
            "hello",
            b"audio-bytes",
            "de",
            "en",
            sessions=session_manager,
        )

    assert message.translated_text == "hello"
    # The response builder reads exactly this flag to decide whether the
    # listener is handed an audio URL, which is what gates the player.
    assert message.translated_audio_available is False

    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("Failed to save translated audio" in record.getMessage() for record in errors)
    assert any("PermissionError" in record.getMessage() for record in errors)


def test_a_failed_original_audio_write_is_reported_not_swallowed(refusing_audio_storage, caplog):
    key = TenantSessionKey("tenant-test", "audio-failure-session")

    with caplog.at_level(logging.ERROR, logger=session_routes.logger.name):
        available = session_routes._store_audio_artifacts(
            key, ClientType.CUSTOMER, "message-id", b"audio-bytes"
        )

    assert available is False
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("Failed to save original audio" in record.getMessage() for record in errors)


def test_the_failure_log_carries_a_traceback_without_the_exception_text(
    refusing_audio_storage, caplog
):
    """`_redacted_exception_info` keeps the stack and replaces the message.

    The traceback is what makes the cause findable; the exception's own text
    is what could carry a path or a payload into the log, so it is swapped for
    a fixed string.
    """
    key = TenantSessionKey("tenant-test", "audio-failure-session")

    with caplog.at_level(logging.ERROR, logger=session_routes.logger.name):
        session_routes._store_audio_artifacts(
            key, ClientType.CUSTOMER, "message-id", b"audio-bytes"
        )

    record = next(r for r in caplog.records if r.levelno >= logging.ERROR)
    exception_type, exception, traceback = record.exc_info
    assert traceback is not None, "the stack must survive redaction"
    assert exception_type is RuntimeError, "the real exception class is not logged"
    assert str(exception) == "Exception details redacted"
    # The useful half still reaches the log: the class name is in the message.
    assert "PermissionError" in record.getMessage()
