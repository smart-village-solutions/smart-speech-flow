"""
Test zur Sicherstellung, dass alle 10 unterstützten Sprachen funktionieren
"""

import pytest
from services.api_gateway.routes.session import SUPPORTED_LANGUAGES

# Liste aller unterstützten Sprachen
ALL_SUPPORTED_LANGUAGES = list(SUPPORTED_LANGUAGES.keys())

# Erwartete 10 Sprachen gemäß Anforderungen
REQUIRED_LANGUAGES = ["de", "en", "ar", "tr", "ku", "ti", "am", "fa", "ru", "uk"]


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


@pytest.mark.parametrize("lang_code", REQUIRED_LANGUAGES)
def test_asr_service_supports_language(lang_code):
    """
    Stelle sicher, dass ASR-Service alle Sprachen in SUPPORTED_LANGS hat
    WICHTIG: Dieser Test schlägt fehl, wenn ASR-Service aktualisiert werden muss
    """
    from services.asr.app import SUPPORTED_LANGS

    assert lang_code in SUPPORTED_LANGS, (
        f"ASR-Service unterstützt '{lang_code}' nicht. "
        f"Bitte zu services/asr/app.py::SUPPORTED_LANGS hinzufügen. "
        f"Aktuell: {SUPPORTED_LANGS}"
    )


def test_tts_service_has_fallback_for_all_languages():
    """
    Stelle sicher, dass TTS-Service Fallback-Mapping für alle Sprachen hat
    (entweder Coqui-TTS oder HuggingFace MMS-TTS)
    """
    from services.tts.app import tts_models, iso1_to_iso3_hf

    for lang_code in REQUIRED_LANGUAGES:
        has_coqui = lang_code in tts_models
        has_mms_fallback = lang_code in iso1_to_iso3_hf

        assert has_coqui or has_mms_fallback, (
            f"TTS-Service hat weder Coqui noch MMS-Fallback für '{lang_code}'. "
            f"Coqui: {list(tts_models.keys())}, "
            f"MMS: {list(iso1_to_iso3_hf.keys())}"
        )


def test_language_consistency_across_services():
    """
    Stelle sicher, dass alle Services die gleichen Sprachen unterstützen
    """
    from services.asr.app import SUPPORTED_LANGS as asr_langs
    from services.tts.app import iso1_to_iso3_hf

    # API Gateway definiert die Wahrheit
    api_langs = set(ALL_SUPPORTED_LANGUAGES)

    # ASR muss alle unterstützen
    asr_supported = set(asr_langs)
    missing_in_asr = api_langs - asr_supported
    assert len(missing_in_asr) == 0, (
        f"ASR fehlen Sprachen: {missing_in_asr}"
    )

    # TTS muss alle unterstützen (via Fallback)
    from services.tts.app import tts_models
    tts_supported = set(tts_models.keys()) | set(iso1_to_iso3_hf.keys())
    missing_in_tts = api_langs - tts_supported
    assert len(missing_in_tts) == 0, (
        f"TTS fehlen Sprachen: {missing_in_tts}"
    )

    # Translation unterstützt dynamisch alle, aber wir können das nicht einfach testen
    # ohne das Modell zu laden


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
