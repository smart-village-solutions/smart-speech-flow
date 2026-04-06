"""
Produktnahe Smoke-Tests für Live-Services.

Diese Tests sind standardmäßig deaktiviert und werden nur ausgeführt, wenn
TEST_SERVICES=true gesetzt ist. Sie prüfen die zuletzt auffälligen
Regressionspfade direkt gegen laufende Docker-Services.
"""

from __future__ import annotations

import os

import httpx
import pytest


REQUIRED_LANGUAGES = {"de", "en", "ar", "tr", "ru", "uk", "am", "ti", "ku", "fa"}
SAMPLE_TEXTS = {
    "de": "Hallo und guten Tag.",
    "en": "Hello and good day.",
    "ar": "مرحبا، يوم سعيد.",
    "tr": "Merhaba, iyi gunler.",
    "ru": "Здравствуйте, добрый день.",
    "uk": "Добрий день.",
    "am": "ሰላም እንደምን አለህ።",
    "ti": "ሰላም ከመይ ኣለኻ።",
    "ku": "Silav, roj bas.",
    "fa": "سلام، روز بخیر.",
}

SKIP_SERVICE_TESTS = os.getenv("TEST_SERVICES", "false").lower() != "true"
skip_service_msg = "Service tests disabled. Set TEST_SERVICES=true to enable."

API_BASE_URL = os.getenv("SMOKE_API_BASE_URL", "http://localhost:8000")
TTS_BASE_URL = os.getenv("SMOKE_TTS_BASE_URL", "http://localhost:8003")


@pytest.fixture
def live_client() -> httpx.Client:
    with httpx.Client(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
        yield client


@pytest.mark.skipif(SKIP_SERVICE_TESTS, reason=skip_service_msg)
def test_tts_supported_languages_match_required_set(live_client: httpx.Client):
    response = live_client.get(f"{TTS_BASE_URL}/supported-languages")
    response.raise_for_status()

    payload = response.json()
    assert set(payload["languages"]) == REQUIRED_LANGUAGES


@pytest.mark.skipif(SKIP_SERVICE_TESTS, reason=skip_service_msg)
@pytest.mark.parametrize("lang_code", sorted(REQUIRED_LANGUAGES))
def test_tts_synthesizes_audio_for_each_supported_language(
    live_client: httpx.Client, lang_code: str
):
    response = live_client.post(
        f"{TTS_BASE_URL}/synthesize",
        json={
            "text": SAMPLE_TEXTS[lang_code],
            "lang": lang_code,
            "session_id": f"smoke-{lang_code}",
        },
    )

    assert (
        response.status_code == 200
    ), f"TTS failed for {lang_code}: {response.status_code} {response.text[:200]}"
    assert response.headers["content-type"].startswith("audio/")
    assert len(response.content) > 0


@pytest.mark.skipif(SKIP_SERVICE_TESTS, reason=skip_service_msg)
def test_session_lifecycle_smoke_cleans_up_old_session(live_client: httpx.Client):
    first_create = live_client.post(f"{API_BASE_URL}/api/admin/session/create")
    first_create.raise_for_status()
    first_session_id = first_create.json()["session_id"]

    activate = live_client.post(
        f"{API_BASE_URL}/api/customer/session/activate",
        json={"session_id": first_session_id, "customer_language": "ru"},
    )
    activate.raise_for_status()

    first_status_active = live_client.get(
        f"{API_BASE_URL}/api/customer/session/{first_session_id}/status"
    )
    first_status_active.raise_for_status()
    assert first_status_active.json()["status"] == "active"

    second_create = live_client.post(f"{API_BASE_URL}/api/admin/session/create")
    second_create.raise_for_status()
    second_session_id = second_create.json()["session_id"]
    assert second_session_id != first_session_id

    first_status_terminated = live_client.get(
        f"{API_BASE_URL}/api/customer/session/{first_session_id}/status"
    )
    first_status_terminated.raise_for_status()
    terminated_payload = first_status_terminated.json()
    assert terminated_payload["status"] == "terminated"
    assert terminated_payload["is_active"] is False
    assert terminated_payload["can_send_messages"] is False

    current_response = live_client.get(
        f"{API_BASE_URL}/api/admin/session/current",
        params={"session_id": second_session_id},
    )
    current_response.raise_for_status()
    current_payload = current_response.json()
    assert current_payload["session_id"] == second_session_id
    assert current_payload["status"] == "pending"

    terminate_second = live_client.delete(
        f"{API_BASE_URL}/api/admin/session/{second_session_id}/terminate"
    )
    terminate_second.raise_for_status()

    second_status = live_client.get(
        f"{API_BASE_URL}/api/customer/session/{second_session_id}/status"
    )
    second_status.raise_for_status()
    assert second_status.json()["status"] == "terminated"
