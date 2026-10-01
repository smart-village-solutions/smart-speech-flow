"""What each input mode sends downstream and answers on failure (#230).

Pinned before audio and text share one pipeline tail, so every behaviour
change the sharing makes shows up as a diff to this file.
"""

from __future__ import annotations

import pytest

from tests.gateway_contract.contract_support import wav_bytes

ERROR_FIELDS = {"status", "error_code", "error_message", "details", "timestamp"}
TRANSLATION_PAYLOAD = {
    "text": "Guten Tag",
    "source_lang": "de",
    "target_lang": "en",
    "model": "m2m100_1.2B",
    "debug": "false",
}


@pytest.fixture
def active_session(conversations) -> str:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    return session_id


def _send(client, conversations, session_id: str, mode: str):
    if mode == "audio":
        return client.post(
            f"/api/admin/session/{session_id}/message",
            files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
            data={"source_lang": "de", "target_lang": "en"},
        )
    return conversations.send_text(session_id)


def _error(response) -> dict:
    detail = response.json()["detail"]
    assert set(detail) == ERROR_FIELDS
    return detail


def _history(client, session_id: str) -> list:
    return client.get(f"/api/admin/session/{session_id}/messages").json()["messages"]


@pytest.mark.parametrize("mode", ["audio", "text"])
def test_both_modes_send_translation_the_same_request(
    client, conversations, active_session, speech_services, mode
):
    assert _send(client, conversations, active_session, mode).status_code == 200

    [translation_request] = speech_services.sent_to("translation")
    assert translation_request["json"] == TRANSLATION_PAYLOAD


@pytest.mark.parametrize("mode", ["audio", "text"])
def test_both_modes_send_tts_the_same_request(
    client, conversations, active_session, speech_services, mode
):
    assert _send(client, conversations, active_session, mode).status_code == 200

    [tts_request] = speech_services.sent_to("tts")
    assert tts_request["json"] == {
        "text": "Good day",
        "lang": "en",
        "session_id": active_session,
        "debug": "false",
    }
    assert tts_request["timeout"] == 45


@pytest.mark.parametrize("mode", ["audio", "text"])
@pytest.mark.parametrize("refined", [True, False])
def test_the_translation_services_tts_text_never_reaches_tts(
    client, conversations, active_session, refinement, mode, refined
):
    """TTS reads only `text`; an older translation image may still send `tts_text`."""
    refinement.tts_text = "Guten Tag."
    if not refined:
        refinement.refined_text = "Good day"

    assert _send(client, conversations, active_session, mode).status_code == 200

    [tts_request] = refinement.sent_to("tts")
    assert "tts_text" not in tts_request["json"]


@pytest.mark.parametrize("mode", ["audio", "text"])
def test_a_failed_refinement_keeps_the_translation_in_either_mode(
    client, conversations, active_session, refinement, mode
):
    refinement.fail("refinement", 500)

    response = _send(client, conversations, active_session, mode)

    assert response.status_code == 200
    body = response.json()
    assert body["translated_text"] == "Good day"
    [step] = [s for s in body["pipeline_metadata"]["steps"] if s["name"] == "refinement"]
    assert step["refinement_comparison"]["primary_status"] == "error"
    [tts_request] = refinement.sent_to("tts")
    assert tts_request["json"]["text"] == "Good day"


@pytest.mark.parametrize(
    ("service", "message", "steps"),
    [
        (
            "translation",
            "Translation-Fehler: translation failed",
            ["Text_Validation", "Translation"],
        ),
        (
            "tts",
            "TTS-Fehler: {'detail': 'tts failed'}",
            ["Text_Validation", "Translation", "TTS"],
        ),
    ],
)
def test_a_failed_text_stage_answers_400_text_pipeline_error(
    client, conversations, active_session, speech_services, service, message, steps
):
    speech_services.fail(service, 500)

    response = conversations.send_text(active_session)

    assert response.status_code == 400
    detail = _error(response)
    assert detail["status"] == "error"
    assert detail["error_code"] == "TEXT_PIPELINE_ERROR"
    assert detail["error_message"] == message
    assert detail["details"]["failed_stage"] == service
    assert detail["details"]["error_code"] == "upstream_error"
    assert [step["step"] for step in detail["details"]["steps"]] == steps
    assert _history(client, active_session) == []


@pytest.mark.parametrize("transcript", ["", "   ", "\n\t"], ids=["empty", "spaces", "newline"])
def test_a_recording_with_no_speech_answers_422_and_stores_nothing(
    client, conversations, active_session, speech_services, transcript
):
    speech_services.asr_text = transcript

    response = _send(client, conversations, active_session, "audio")

    assert response.status_code == 422
    detail = _error(response)
    assert detail["status"] == "error"
    assert detail["error_code"] == "NO_SPEECH_RECOGNIZED"
    assert detail["details"] == {}
    assert speech_services.calls == ["asr"]
    assert _history(client, active_session) == []


def test_a_transcript_with_any_character_is_translated(
    client, conversations, active_session, speech_services
):
    speech_services.asr_text = "."

    response = _send(client, conversations, active_session, "audio")

    assert response.status_code == 200
    assert response.json()["original_text"] == "."
    assert speech_services.calls == ["asr", "translation", "tts"]
