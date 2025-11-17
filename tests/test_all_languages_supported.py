"""
Test zur Sicherstellung, dass alle 10 unterstützten Sprachen funktionieren
"""

import pytest
import os
from services.api_gateway.routes.session import SUPPORTED_LANGUAGES

# Liste aller unterstützten Sprachen
ALL_SUPPORTED_LANGUAGES = list(SUPPORTED_LANGUAGES.keys())

# Erwartete 10 Sprachen gemäß Anforderungen
REQUIRED_LANGUAGES = ["de", "en", "ar", "tr", "ku", "ti", "am", "fa", "ru", "uk"]

# Skip Integration-Tests wenn nicht explizit aktiviert
SKIP_SERVICE_TESTS = os.getenv("TEST_SERVICES", "false").lower() != "true"
skip_service_msg = "Service tests disabled. Set TEST_SERVICES=true to enable."


def test_all_required_languages_are_supported():
    """Stelle sicher, dass alle 10 geforderten Sprachen unterstützt werden"""
    for lang in REQUIRED_LANGUAGES:
        assert lang in ALL_SUPPORTED_LANGUAGES, (
            f"Sprache '{lang}' fehlt in SUPPORTED_LANGUAGES. "
            f"Verfügbar: {ALL_SUPPORTED_LANGUAGES}"
        )


def test_exactly_10_languages_supported():
    """Stelle sicher, dass genau 10 Sprachen unterstützt werden"""
    assert len(ALL_SUPPORTED_LANGUAGES) == 10, (
        f"Erwartet: 10 Sprachen, Gefunden: {len(ALL_SUPPORTED_LANGUAGES)} - "
        f"{ALL_SUPPORTED_LANGUAGES}"
    )


def test_language_names_are_defined():
    """Stelle sicher, dass alle Sprachen Name und Native-Name haben"""
    for lang_code, lang_info in SUPPORTED_LANGUAGES.items():
        assert "name" in lang_info, f"Sprache {lang_code} hat keinen 'name'"
        assert "native" in lang_info, f"Sprache {lang_code} hat keinen 'native' Name"
        assert isinstance(lang_info["name"], str), f"{lang_code} name ist kein String"
        assert isinstance(lang_info["native"], str), f"{lang_code} native ist kein String"
        assert len(lang_info["name"]) > 0, f"{lang_code} name ist leer"
        assert len(lang_info["native"]) > 0, f"{lang_code} native ist leer"


@pytest.mark.skipif(SKIP_SERVICE_TESTS, reason=skip_service_msg)
@pytest.mark.parametrize("lang_code", REQUIRED_LANGUAGES)
def test_asr_service_supports_language(lang_code):
    """
    Stelle sicher, dass ASR-Service alle Sprachen unterstützt
    Testet den laufenden Docker-Service via HTTP
    """
    import httpx

    try:
        response = httpx.get("http://localhost:8001/supported-languages", timeout=2.0)
        if response.status_code == 200:
            supported_langs = response.json().get("languages", [])
            assert lang_code in supported_langs, (
                f"ASR-Service unterstützt '{lang_code}' nicht. "
                f"Verfügbare Sprachen: {supported_langs}"
            )
        else:
            pytest.skip(f"ASR-Service nicht erreichbar (Status: {response.status_code})")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("ASR-Service nicht erreichbar")


@pytest.mark.skipif(SKIP_SERVICE_TESTS, reason=skip_service_msg)
def test_tts_service_has_fallback_for_all_languages():
    """
    Stelle sicher, dass TTS-Service alle Sprachen unterstützt
    Testet den laufenden Docker-Service via HTTP
    """
    import httpx

    try:
        response = httpx.get("http://localhost:8003/supported-languages", timeout=2.0)
        if response.status_code == 200:
            supported_langs = response.json().get("languages", [])
            for lang_code in REQUIRED_LANGUAGES:
                assert lang_code in supported_langs, (
                    f"TTS-Service unterstützt '{lang_code}' nicht. "
                    f"Verfügbare Sprachen: {supported_langs}"
                )
        else:
            pytest.skip(f"TTS-Service nicht erreichbar (Status: {response.status_code})")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("TTS-Service nicht erreichbar")


@pytest.mark.skipif(SKIP_SERVICE_TESTS, reason=skip_service_msg)
def test_language_consistency_across_services():
    """
    Stelle sicher, dass alle Services die gleichen Sprachen unterstützen
    Testet die laufenden Docker-Services via HTTP
    """
    import httpx

    # API Gateway definiert die Wahrheit
    api_langs = set(ALL_SUPPORTED_LANGUAGES)

    try:
        # ASR muss alle unterstützen
        asr_response = httpx.get("http://localhost:8001/supported-languages", timeout=2.0)
        if asr_response.status_code == 200:
            asr_langs = set(asr_response.json().get("languages", []))
            missing_in_asr = api_langs - asr_langs
            assert len(missing_in_asr) == 0, (
                f"ASR fehlen Sprachen: {missing_in_asr}"
            )

        # TTS muss alle unterstützen
        tts_response = httpx.get("http://localhost:8003/supported-languages", timeout=2.0)
        if tts_response.status_code == 200:
            tts_langs = set(tts_response.json().get("languages", []))
            missing_in_tts = api_langs - tts_langs
            assert len(missing_in_tts) == 0, (
                f"TTS fehlen Sprachen: {missing_in_tts}"
            )
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("Services nicht erreichbar")


@pytest.mark.integration
def test_api_languages_endpoint_returns_all():
    """
    Stelle sicher, dass /api/languages/supported alle 10 Sprachen zurückgibt
    """
    from fastapi.testclient import TestClient
    from services.api_gateway.app import app

    client = TestClient(app)
    response = client.get("/api/languages/supported")

    assert response.status_code == 200
    data = response.json()

    assert "languages" in data
    returned_languages = set(data["languages"].keys())

    assert returned_languages == set(REQUIRED_LANGUAGES), (
        f"API gibt nicht alle Sprachen zurück. "
        f"Erwartet: {REQUIRED_LANGUAGES}, "
        f"Bekommen: {list(returned_languages)}"
    )
