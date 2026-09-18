"""The authorization outcome is server-side state and defaults to refused."""

from datetime import datetime, timezone

from services.api_gateway.session_manager import ClientType, SessionMessage


def _message(**overrides) -> SessionMessage:
    defaults = dict(
        id="m1",
        sender=ClientType.CUSTOMER,
        original_text="hallo",
        translated_text="hello",
        audio_base64=None,
        source_lang="de",
        target_lang="en",
        timestamp=datetime(2026, 9, 17, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SessionMessage(**defaults)


def test_a_new_message_is_refused_by_default():
    message = _message()
    assert message.record_authorized is False
    assert message.original_audio_authorized is False
    assert message.translated_audio_authorized is False


def test_public_dict_hides_the_outcome():
    message = _message(record_authorized=True, translated_audio_authorized=True)
    data = message.to_dict()
    assert "record_authorized" not in data
    assert "original_audio_authorized" not in data
    assert "translated_audio_authorized" not in data


def test_storage_dict_carries_the_outcome():
    message = _message(record_authorized=True, translated_audio_authorized=True)
    data = message.to_dict(include_authorization=True)
    assert data["record_authorized"] is True
    assert data["original_audio_authorized"] is False
    assert data["translated_audio_authorized"] is True


def test_round_trip_preserves_the_outcome():
    message = _message(record_authorized=True, original_audio_authorized=True)
    restored = SessionMessage.from_dict(message.to_dict(include_authorization=True))
    assert restored.record_authorized is True
    assert restored.original_audio_authorized is True
    assert restored.translated_audio_authorized is False


def test_record_written_before_this_change_restores_as_refused():
    legacy = {
        "id": "m1",
        "sender": "customer",
        "original_text": "hallo",
        "translated_text": "hello",
        "source_lang": "de",
        "target_lang": "en",
        "timestamp": "2026-09-17T00:00:00+00:00",
        "translated_audio_available": True,
    }
    restored = SessionMessage.from_dict(legacy)
    assert restored.record_authorized is False
    assert restored.original_audio_authorized is False
    assert restored.translated_audio_authorized is False
