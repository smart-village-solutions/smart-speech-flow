"""Behavioral coverage for model-backed service endpoints without model downloads."""

import os
import tempfile
from types import SimpleNamespace

import pytest

from test_service_app_helpers import (
    FakeUploadFile,
    build_fastapi_stub,
    build_prometheus_stub,
    build_request,
    build_soundfile_stub,
    build_torch_stub,
    build_transformers_stub,
    build_tts_stub,
    load_module,
)


@pytest.fixture
def asr_service(monkeypatch):
    fastapi_stub, responses_stub = build_fastapi_stub()
    return load_module(
        monkeypatch,
        "services.asr.app",
        "services/asr/app.py",
        {
            "torch": build_torch_stub(),
            "fastapi": fastapi_stub,
            "fastapi.responses": responses_stub,
            "prometheus_client": build_prometheus_stub(),
        },
    )


@pytest.fixture
def translation_service(monkeypatch):
    fastapi_stub, responses_stub = build_fastapi_stub()
    return load_module(
        monkeypatch,
        "services.translation.app",
        "services/translation/app.py",
        {
            "torch": build_torch_stub(),
            "transformers": build_transformers_stub(),
            "fastapi": fastapi_stub,
            "fastapi.responses": responses_stub,
            "prometheus_client": build_prometheus_stub(),
        },
    )


@pytest.fixture
def tts_service(monkeypatch):
    tts_package, tts_api = build_tts_stub()
    fastapi_stub, responses_stub = build_fastapi_stub()
    return load_module(
        monkeypatch,
        "services.tts.app",
        "services/tts/app.py",
        {
            "torch": build_torch_stub(),
            "transformers": build_transformers_stub(),
            "soundfile": build_soundfile_stub(),
            "TTS": tts_package,
            "TTS.api": tts_api,
            "fastapi": fastapi_stub,
            "fastapi.responses": responses_stub,
            "prometheus_client": build_prometheus_stub(),
        },
    )


@pytest.mark.asyncio
async def test_asr_transcription_returns_text_and_removes_temporary_audio(
    asr_service, monkeypatch
):
    input_file = tempfile.NamedTemporaryFile(delete=False)
    input_file.close()
    normalized_file = tempfile.NamedTemporaryFile(delete=False)
    normalized_file.close()

    class ModelStub:
        @staticmethod
        def transcribe(path, language):
            assert path == normalized_file.name
            assert language == "en"
            return {"text": "hello world"}

    monkeypatch.setattr(asr_service, "model_loaded", True)
    monkeypatch.setattr(asr_service, "model", ModelStub())
    monkeypatch.setattr(
        asr_service, "_persist_upload_to_temp", lambda _: input_file.name
    )
    monkeypatch.setattr(
        asr_service, "normalize_to_wav16k", lambda _: normalized_file.name
    )

    response = await asr_service.transcribe(
        FakeUploadFile(b"audio"), build_request(), lang="en"
    )

    assert response == {"text": "hello world", "fallback": False}
    assert not os.path.exists(input_file.name)
    assert not os.path.exists(normalized_file.name)


@pytest.mark.asyncio
async def test_translation_returns_scalar_and_list_results_with_request_metadata(
    translation_service, monkeypatch
):
    translation_service.model_loaded = True
    translation_service.m2m_model = object()
    translation_service.m2m_tokenizer = SimpleNamespace(
        lang_code_to_id={"de": 0, "en": 1}
    )
    translation_service.supported_langs = ["de", "en"]
    monkeypatch.setattr(
        translation_service,
        "_translate_texts",
        lambda texts, *_: [f"translated:{text}" for text in texts],
    )

    scalar_response = await translation_service.translate(
        build_request({"text": "Hallo", "source_lang": "de", "target_lang": "en"})
    )
    list_response = await translation_service.translate(
        build_request(
            {
                "text": ["Hallo", "Welt"],
                "source_lang": "de",
                "target_lang": "en",
                "debug": True,
            }
        )
    )

    assert b'"translations":"translated:Hallo"' in scalar_response.body
    assert b'"count":1' in scalar_response.body
    assert b'"translations":["translated:Hallo","translated:Welt"]' in list_response.body
    assert b'"debug":' in list_response.body


@pytest.mark.asyncio
async def test_translation_returns_debuggable_model_unavailable_response(translation_service):
    translation_service.model_loaded = False
    translation_service.m2m_model = None
    translation_service.m2m_tokenizer = None

    response = await translation_service.translate(
        build_request(
            {"text": "Hallo", "source_lang": "de", "target_lang": "en", "debug": True}
        )
    )

    assert response.status_code == 503
    assert b'"error":"Model unavailable"' in response.body
    assert b'"translations":null' in response.body


@pytest.mark.asyncio
async def test_tts_synthesis_returns_wav_with_model_metadata(tts_service):
    response = await tts_service.synthesize(
        build_request(
            {"text": "Hallo", "lang": "de", "session_id": "session-123", "debug": True}
        )
    )

    assert response.status_code == 200
    assert response.body == b"COQUI-WAV"
    assert response.media_type == "audio/wav"
    assert response.headers["x-tts-language"] == "de"
    assert response.headers["x-tts-model"] == "tts_models/de/thorsten/vits"
    assert b'"seed_source": "session_id"' in response.headers["x-debug-info"].encode()


@pytest.mark.asyncio
async def test_tts_rejects_unknown_language_without_loading_a_model(tts_service, monkeypatch):
    model_lookup_called = False

    def unexpected_model_lookup(_):
        nonlocal model_lookup_called
        model_lookup_called = True
        return object()

    monkeypatch.setattr(tts_service, "get_tts_model", unexpected_model_lookup)

    response = await tts_service.synthesize(
        build_request({"text": "Hallo", "lang": "xx", "debug": True})
    )

    assert response.status_code == 400
    assert model_lookup_called is False
    assert b"Keine TTS-Stimme" in response.body
