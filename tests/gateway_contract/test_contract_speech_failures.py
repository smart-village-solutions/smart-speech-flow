"""How speech-service failures, open circuit breakers and refinement reach the client.

The speech services and the refiner are answered at their HTTP boundary. Only
public routes are driven: the message routes, the legacy /pipeline and /upload
routes, and the /api/health and /api/admin/circuit-breakers routes.
"""

from __future__ import annotations

import base64

import pytest
import requests

from tests.gateway_contract.conftest import (
    REFINER_MODEL,
    REFINER_SKIPPED_TARGET,
)
from tests.gateway_contract.contract_support import wav_bytes

ERROR_FIELDS = {"status", "error_code", "error_message", "details", "timestamp"}
RECOVERY_TIMEOUT_SECONDS = 45
FAILURE_THRESHOLD = 3

AUDIO_STAGES = {
    "asr": {
        "prefix": "ASR-Fehler: ",
        "calls": ["asr"],
        "steps": ["asr"],
        "asr_text": None,
        "translation_text": None,
    },
    "translation": {
        "prefix": "Translation-Fehler: ",
        "calls": ["asr", "translation"],
        "steps": ["asr", "translation"],
        "asr_text": "Guten Tag",
        "translation_text": None,
    },
    "tts": {
        "prefix": "TTS-Fehler: ",
        "calls": ["asr", "translation", "tts"],
        "steps": ["asr", "translation", "tts"],
        "asr_text": "Guten Tag",
        "translation_text": "Good day",
    },
}
PATH_STAGES = [
    ("audio", "asr"),
    ("audio", "translation"),
    ("audio", "tts"),
    ("text", "translation"),
    ("text", "tts"),
]


@pytest.fixture
def active_session(conversations) -> str:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    return session_id


def _send_audio(client, session_id: str, target: str = "en"):
    return client.post(
        f"/api/admin/session/{session_id}/message",
        files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
        data={"source_lang": "de", "target_lang": target},
    )


def _send(client, conversations, session_id: str, path: str):
    if path == "audio":
        return _send_audio(client, session_id)
    return conversations.send_text(session_id)


def _error(response) -> dict:
    detail = response.json()["detail"]
    assert set(detail) == ERROR_FIELDS
    assert detail["status"] == "error"
    return detail


def _history(client, session_id: str) -> list:
    return client.get(f"/api/admin/session/{session_id}/messages").json()["messages"]


def _circuit(client, service: str) -> dict:
    response = client.get("/api/health/circuit-breakers")
    assert response.status_code == 200
    return response.json()["circuits"][service]


def _step_names(pipeline_result: dict) -> list[str]:
    return [step["name"] for step in pipeline_result["debug"]["steps"]]


@pytest.mark.parametrize("service", sorted(AUDIO_STAGES))
def test_a_failed_audio_stage_reports_its_stage_and_keeps_the_work_done(
    client, active_session, speech_services, service
):
    stage = AUDIO_STAGES[service]
    speech_services.fail(service, 500)

    response = _send_audio(client, active_session)

    assert response.status_code == 500
    assert "Retry-After" not in response.headers
    detail = _error(response)
    assert detail["error_code"] == "PIPELINE_ERROR"
    assert detail["error_message"].startswith(f"Audio pipeline failed: {stage['prefix']}")
    result = detail["details"]["pipeline_result"]
    assert result["error"] is True
    assert result["error_msg"].startswith(stage["prefix"])
    assert (result["asr_text"], result["translation_text"], result["audio_bytes"]) == (
        stage["asr_text"],
        stage["translation_text"],
        None,
    )
    assert result["debug"]["failed_stage"] == service
    assert result["debug"]["error_code"] == "upstream_error"
    assert _step_names(result) == stage["steps"]
    assert speech_services.calls == stage["calls"]
    assert _history(client, active_session) == []


def test_tts_answering_without_audio_is_a_malformed_reply(client, active_session, speech_services):
    speech_services.answer_tts_without_audio()

    response = _send_audio(client, active_session)

    assert response.status_code == 500
    detail = _error(response)
    assert detail["error_code"] == "PIPELINE_ERROR"
    assert detail["error_message"] == "Audio pipeline failed: TTS-Fehler: synthesis failed"
    result = detail["details"]["pipeline_result"]
    assert result["debug"]["failed_stage"] == "tts"
    assert result["debug"]["error_code"] == "upstream_malformed_response"


def test_a_stage_rejecting_the_request_is_a_pipeline_error(client, active_session, speech_services):
    speech_services.fail("translation", 422)

    response = _send_audio(client, active_session)

    assert response.status_code == 500
    detail = _error(response)
    assert detail["error_code"] == "PIPELINE_ERROR"
    result = detail["details"]["pipeline_result"]
    assert result["debug"]["failed_stage"] == "translation"
    assert result["debug"]["error_code"] == "upstream_rejected"


@pytest.mark.parametrize("service", sorted(AUDIO_STAGES))
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            requests.ConnectionError("HTTPConnectionPool(host='speech-internal', port=8000)"),
            "upstream_unreachable",
        ),
        (
            requests.Timeout("HTTPConnectionPool(host='speech-internal', port=8000)"),
            "upstream_timeout",
        ),
    ],
    ids=["unreachable", "timeout"],
)
def test_a_transport_failure_reaches_the_client_only_as_its_taxonomy_code(
    client, active_session, speech_services, service, error, code
):
    speech_services.raise_on(service, error)

    response = _send_audio(client, active_session)

    assert response.status_code == 500
    detail = _error(response)
    assert detail["error_code"] == "PIPELINE_ERROR"
    assert detail["error_message"] == f"Audio pipeline failed: Pipeline-Fehler: {code}"
    result = detail["details"]["pipeline_result"]
    assert result["debug"]["failed_stage"] == "unknown"
    assert result["debug"]["error_code"] == code
    assert "speech-internal" not in response.text
    assert _history(client, active_session) == []


@pytest.mark.parametrize("service", ["translation", "tts"])
def test_a_text_message_hides_the_transport_failure_and_stores_nothing(
    client, conversations, active_session, speech_services, service
):
    speech_services.raise_on(
        service, requests.ConnectionError("HTTPConnectionPool(host='speech-internal', port=8000)")
    )

    response = conversations.send_text(active_session)

    assert response.status_code >= 400
    assert "speech-internal" not in response.text
    assert _history(client, active_session) == []


@pytest.mark.parametrize(("path", "service"), PATH_STAGES)
def test_a_shedding_stage_is_busy_with_its_own_retry_after(
    client, conversations, active_session, speech_services, path, service
):
    speech_services.fail(service, 503, headers={"Retry-After": "9"})

    response = _send(client, conversations, active_session, path)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "9"
    detail = _error(response)
    assert detail["error_code"] == "SYSTEM_BUSY"
    assert detail["details"]["retry_after_seconds"] == 9
    assert detail["details"]["upstream_error"].startswith(AUDIO_STAGES[service]["prefix"])
    assert _history(client, active_session) == []


@pytest.mark.parametrize("path", ["audio", "text"])
def test_a_503_without_retry_after_is_busy_with_the_default_delay(
    client, conversations, active_session, speech_services, path
):
    speech_services.fail("translation", 503)

    response = _send(client, conversations, active_session, path)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert _error(response)["details"]["retry_after_seconds"] == 5


def _open_breaker(client, session_id: str, speech_services, service: str) -> None:
    speech_services.fail(service, 500)
    for attempt in range(1, FAILURE_THRESHOLD + 1):
        assert _circuit(client, service)["state"] == "closed", attempt
        assert _send_audio(client, session_id).status_code == 500
    speech_services.recover(service)


@pytest.mark.parametrize(("path", "service"), PATH_STAGES)
def test_an_open_breaker_is_busy_until_its_recovery_window_ends(
    client, conversations, active_session, speech_services, path, service
):
    _open_breaker(client, active_session, speech_services, service)
    circuit = _circuit(client, service)
    assert circuit["state"] == "open"
    assert circuit["circuit_info"]["failure_count"] == FAILURE_THRESHOLD
    assert circuit["circuit_info"]["current_recovery_timeout"] == RECOVERY_TIMEOUT_SECONDS
    speech_services.calls.clear()

    response = _send(client, conversations, active_session, path)

    assert response.status_code == 503
    detail = _error(response)
    assert detail["error_code"] == "SYSTEM_BUSY"
    retry_after = int(response.headers["Retry-After"])
    assert 1 <= retry_after <= RECOVERY_TIMEOUT_SECONDS
    assert detail["details"]["retry_after_seconds"] == retry_after
    assert detail["details"]["upstream_error"] == (
        f"Service '{service}' unavailable: circuit breaker open"
    )
    assert service not in speech_services.calls
    assert _history(client, active_session) == []


@pytest.mark.parametrize("service", sorted(AUDIO_STAGES))
def test_an_open_breaker_is_reported_and_an_operator_reset_closes_it(
    client, active_session, speech_services, service
):
    _open_breaker(client, active_session, speech_services, service)

    summary = client.get("/api/health/summary").json()
    assert summary["summary"]["circuit_states"][service] == "open"
    assert {
        "level": "error",
        "type": "circuit_open",
        "message": f"Circuit Breaker für '{service}' ist OPEN",
    } in summary["alerts"]

    reset = client.post(f"/api/admin/circuit-breakers/{service}/reset")

    assert reset.status_code == 200
    assert reset.json() == {
        "status": "success",
        "message": f"Circuit breaker for '{service}' has been reset",
        "service_name": service,
        "old_state": "open",
        "new_state": "closed",
    }
    assert _circuit(client, service)["state"] == "closed"
    assert _send_audio(client, active_session).status_code == 200


def test_tts_answering_without_audio_counts_toward_its_breaker(
    client, active_session, speech_services
):
    speech_services.answer_tts_without_audio()
    for _ in range(FAILURE_THRESHOLD):
        assert _send_audio(client, active_session).status_code == 500

    assert _circuit(client, "tts")["state"] == "open"


@pytest.mark.parametrize(
    ("status_code", "headers"),
    [(503, {"Retry-After": "3"}), (422, None)],
    ids=["load-shed", "client-error"],
)
def test_load_shedding_and_rejected_requests_leave_the_breaker_closed(
    client, active_session, speech_services, status_code, headers
):
    speech_services.fail("translation", status_code, headers=headers)
    for _ in range(FAILURE_THRESHOLD + 1):
        _send_audio(client, active_session)

    assert _circuit(client, "translation")["state"] == "closed"
    assert speech_services.calls.count("translation") == FAILURE_THRESHOLD + 1


def test_breaker_reports_list_the_three_speech_services(client, speech_services):
    circuits = client.get("/api/health/circuit-breakers").json()

    assert circuits["total_circuits"] == 3
    assert list(circuits["circuits"]) == ["asr", "translation", "tts"]
    for name, circuit in circuits["circuits"].items():
        assert circuit["service_name"] == name
        assert circuit["state"] == "closed"


def _refinement_step(body: dict) -> dict:
    steps = body["pipeline_metadata"]["steps"]
    [step] = [step for step in steps if step["name"] == "refinement"]
    return step


@pytest.mark.parametrize("path", ["audio", "text"])
def test_an_applied_refinement_replaces_the_translation_and_is_spoken(
    client, conversations, active_session, refinement, path
):
    response = _send(client, conversations, active_session, path)

    assert response.status_code == 200
    body = response.json()
    assert body["translated_text"] == "Good day, refined"
    expected_calls = ["translation", "refinement", "tts"]
    assert refinement.calls == (["asr", *expected_calls] if path == "audio" else expected_calls)
    assert [step["name"] for step in body["pipeline_metadata"]["steps"]][-3:] == [
        "translation",
        "refinement",
        "tts",
    ]
    step = _refinement_step(body)
    assert step["input"] == {"enabled": True, "changed": True}
    assert step["output"] == {"text": "Good day, refined", "changed": True, "model": REFINER_MODEL}
    assert step["refinement_comparison"] == {
        "primary_model": REFINER_MODEL,
        "primary_status": "success",
        "candidate_model": None,
        "candidate_status": None,
    }
    [tts_request] = refinement.sent_to("tts")
    assert tts_request["json"]["text"] == "Good day, refined"
    [refinement_request] = refinement.sent_to("refinement")
    assert refinement_request["json"]["model"] == REFINER_MODEL
    assert "Current translation candidate: Good day" in refinement_request["json"]["prompt"]


@pytest.mark.parametrize(
    ("configure", "status"),
    [
        (lambda services: setattr(services, "refined_text", "Good day"), "success"),
        (lambda services: services.fail("refinement", 500), "error"),
        (lambda services: setattr(services, "refined_text", ""), "error"),
    ],
    ids=["unchanged", "failed", "empty"],
)
def test_a_refinement_that_changes_nothing_keeps_the_translation(
    client, conversations, active_session, refinement, configure, status
):
    configure(refinement)

    response = conversations.send_text(active_session)

    assert response.status_code == 200
    body = response.json()
    assert body["translated_text"] == "Good day"
    step = _refinement_step(body)
    assert step["output"] == {"text": "Good day", "changed": False, "model": REFINER_MODEL}
    assert step["refinement_comparison"]["primary_status"] == status
    [tts_request] = refinement.sent_to("tts")
    assert tts_request["json"]["text"] == "Good day"


def test_a_skipped_target_language_is_never_sent_to_the_refiner(client, conversations, refinement):
    session_id = conversations.create()
    conversations.activate(session_id, REFINER_SKIPPED_TARGET)

    response = client.post(
        f"/api/admin/session/{session_id}/message",
        json={"text": "Guten Tag", "source_lang": "de", "target_lang": REFINER_SKIPPED_TARGET},
    )

    assert response.status_code == 200
    body = response.json()
    assert "refinement" not in refinement.calls
    step = _refinement_step(body)
    assert step["output"]["changed"] is False
    assert step["refinement_comparison"]["primary_status"] == "skipped"


@pytest.mark.parametrize(("refined", "spoken_tts_text"), [(True, None), (False, "Guten Tag.")])
def test_a_changed_refinement_drops_the_translation_services_tts_text(
    conversations, active_session, refinement, refined, spoken_tts_text
):
    refinement.tts_text = "Guten Tag."
    if not refined:
        refinement.refined_text = "Good day"

    assert conversations.send_text(active_session).status_code == 200

    [tts_request] = refinement.sent_to("tts")
    assert tts_request["json"].get("tts_text") == spoken_tts_text


def test_without_refinement_the_tts_text_is_spoken_and_no_step_is_recorded(
    conversations, active_session, speech_services
):
    speech_services.tts_text = "Guten Tag."

    response = conversations.send_text(active_session)

    assert response.status_code == 200
    names = [step["name"] for step in response.json()["pipeline_metadata"]["steps"]]
    assert names == ["translation", "tts"]
    [tts_request] = speech_services.sent_to("tts")
    assert tts_request["json"]["tts_text"] == "Guten Tag."


def _post_pipeline(client):
    return client.post(
        "/pipeline",
        files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
        data={"source_lang": "de", "target_lang": "en"},
    )


def test_the_pipeline_route_answers_with_all_three_stages(client, speech_services):
    response = _post_pipeline(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"success", "originalText", "translatedText", "audioBase64", "debug"}
    assert (body["success"], body["originalText"], body["translatedText"]) == (
        True,
        "Guten Tag",
        "Good day",
    )
    assert base64.b64decode(body["audioBase64"])[:4] == b"RIFF"
    assert [step["step"] for step in body["debug"]["steps"]] == [
        "Audio_Validation",
        "ASR",
        "Translation",
        "TTS",
    ]
    assert (body["debug"]["failed_stage"], body["debug"]["error_code"]) == ("none", "none")
    assert speech_services.calls == ["asr", "translation", "tts"]


def test_the_pipeline_route_runs_the_refiner(client, refinement):
    response = _post_pipeline(client)

    assert response.status_code == 200
    body = response.json()
    assert body["translatedText"] == "Good day, refined"
    assert "LLM_Refinement" in [step["step"] for step in body["debug"]["steps"]]
    assert refinement.calls == ["asr", "translation", "refinement", "tts"]


def test_the_upload_route_renders_the_result(client, speech_services):
    response = client.post(
        "/upload",
        files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
        data={"source_lang": "de", "target_lang": "en"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Transkription: Guten Tag" in response.text
    assert "Übersetzung: Good day" in response.text
    assert "data:audio/wav;base64," in response.text
    assert speech_services.calls == ["asr", "translation", "tts"]
