"""Message processing: response shape, pipeline metadata and failure mapping."""

from __future__ import annotations

import pytest

from tests.gateway_contract.contract_support import wav_bytes

MESSAGE_FIELDS = {
    "status",
    "message_id",
    "session_id",
    "original_text",
    "translated_text",
    "audio_available",
    "audio_url",
    "processing_time_ms",
    "pipeline_type",
    "source_lang",
    "target_lang",
    "timestamp",
    "pipeline_metadata",
}
ERROR_FIELDS = {"status", "error_code", "error_message", "details", "timestamp"}


pytestmark = pytest.mark.usefixtures("speech_services")


@pytest.fixture
def active_session(conversations) -> str:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    return session_id


def _send_audio(client, session_id: str, role: str = "admin", source: str = "de"):
    target = "en" if source == "de" else "de"
    return client.post(
        f"/api/{role}/session/{session_id}/message",
        files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
        data={"source_lang": source, "target_lang": target},
    )


def _error(response) -> dict:
    detail = response.json()["detail"]
    assert set(detail) == ERROR_FIELDS
    assert detail["status"] == "error"
    return detail


def test_text_message_response_and_pipeline_metadata(
    conversations, active_session, speech_services
):
    response = conversations.send_text(active_session)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == MESSAGE_FIELDS
    message_id = body["message_id"]
    translated_url = f"/api/admin/session/{active_session}/audio/{message_id}/translated.wav"
    assert (body["status"], body["pipeline_type"], body["session_id"]) == (
        "success",
        "text",
        active_session,
    )
    assert (body["original_text"], body["translated_text"]) == ("Guten Tag", "Good day")
    assert (body["source_lang"], body["target_lang"]) == ("de", "en")
    assert body["audio_available"] is True
    assert body["audio_url"] == translated_url
    assert body["processing_time_ms"] >= 1
    assert speech_services.calls == ["translation", "tts"]

    metadata = body["pipeline_metadata"]
    assert set(metadata) == {
        "input",
        "steps",
        "total_duration_ms",
        "pipeline_started_at",
        "pipeline_completed_at",
    }
    assert metadata["input"] == {"type": "text", "source_lang": "de"}
    assert [step["name"] for step in metadata["steps"]] == ["translation", "tts"]
    for step in metadata["steps"]:
        assert {"name", "input", "output", "started_at", "completed_at", "duration_ms"} <= set(step)
    tts_output = metadata["steps"][1]["output"]
    assert tts_output["audio_available"] is True
    assert tts_output["format"] == "wav"
    assert tts_output["audio_url"] == translated_url


def test_audio_message_runs_asr_and_records_its_original(client, active_session, speech_services):
    response = _send_audio(client, active_session)

    assert response.status_code == 200
    body = response.json()
    message_id = body["message_id"]
    assert (body["pipeline_type"], body["original_text"]) == ("audio", "Guten Tag")
    assert speech_services.calls == ["asr", "translation", "tts"]
    metadata = body["pipeline_metadata"]
    assert metadata["input"] == {
        "type": "audio",
        "source_lang": "de",
        "audio_url": f"/api/admin/session/{active_session}/audio/{message_id}/original.wav",
    }
    assert [step["name"] for step in metadata["steps"]] == ["asr", "translation", "tts"]


def test_history_and_audio_are_served_with_role_scoped_urls(client, conversations, active_session):
    message_id = conversations.send_text(active_session).json()["message_id"]

    for role in ("admin", "customer"):
        listing = client.get(f"/api/{role}/session/{active_session}/messages")
        assert listing.status_code == 200
        body = listing.json()
        assert body["session_id"] == active_session
        [message] = body["messages"]
        audio_url = f"/api/{role}/session/{active_session}/audio/{message_id}/translated.wav"
        assert message["id"] == message_id
        assert message["audio_url"] == audio_url
        assert "audio_base64" not in message
        assert message["pipeline_metadata"]["steps"][-1]["output"]["audio_url"] == audio_url

        audio = client.get(audio_url)
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        assert audio.content[:4] == b"RIFF"


def test_customer_message_is_attributed_to_the_customer(client, conversations, active_session):
    response = conversations.send_text(active_session, role="customer", source="en", target="de")

    assert response.status_code == 200
    body = response.json()
    assert body["audio_url"].startswith(f"/api/customer/session/{active_session}/audio/")
    [message] = client.get(f"/api/admin/session/{active_session}/messages").json()["messages"]
    assert message["sender"] == "customer"


@pytest.mark.parametrize("path", ["text", "audio"])
def test_a_shedding_upstream_is_reported_as_retryable_busy(
    client, conversations, active_session, speech_services, path
):
    speech_services.fail("tts", 503, headers={"Retry-After": "7"})

    if path == "text":
        response = conversations.send_text(active_session)
    else:
        response = _send_audio(client, active_session)

    assert response.status_code == 503
    assert _error(response)["error_code"] == "SYSTEM_BUSY"
    assert "Retry-After" in response.headers


@pytest.mark.parametrize("service", ["asr", "translation", "tts"])
def test_a_failed_audio_pipeline_stage_is_a_server_error(
    client, active_session, speech_services, service
):
    speech_services.fail(service, 500)

    response = _send_audio(client, active_session)

    assert response.status_code == 500
    assert _error(response)["error_code"] == "PIPELINE_ERROR"


@pytest.mark.parametrize("role", ["admin", "customer"])
def test_a_pending_session_does_not_accept_messages(conversations, speech_services, role):
    session_id = conversations.create()

    response = conversations.send_text(session_id, role=role)

    assert response.status_code == 400
    assert _error(response)["error_code"] == "SESSION_NOT_ACTIVE"
    assert speech_services.calls == []


@pytest.mark.parametrize(
    ("request_options", "error_code"),
    [
        (
            {"content": b"plain", "headers": {"Content-Type": "text/plain"}},
            "UNSUPPORTED_CONTENT_TYPE",
        ),
        (
            {"content": b"{not json", "headers": {"Content-Type": "application/json"}},
            "INVALID_JSON",
        ),
        (
            {"json": {"text": "x" * 501, "source_lang": "en", "target_lang": "de"}},
            "VALIDATION_ERROR",
        ),
        ({"json": {"text": "   ", "source_lang": "en", "target_lang": "de"}}, "VALIDATION_ERROR"),
        ({"json": {"source_lang": "en", "target_lang": "de"}}, "VALIDATION_ERROR"),
        (
            {"json": {"text": "hi", "source_lang": "xx", "target_lang": "de"}},
            "UNSUPPORTED_LANGUAGE",
        ),
        ({"data": {"source_lang": "en"}, "files": {"other": ("a", b"a")}}, "MISSING_FIELDS"),
    ],
)
def test_malformed_customer_messages_are_client_errors(
    client, active_session, speech_services, request_options, error_code
):
    response = client.post(f"/api/customer/session/{active_session}/message", **request_options)

    assert response.status_code == 400
    assert _error(response)["error_code"] == error_code
    assert speech_services.calls == []
