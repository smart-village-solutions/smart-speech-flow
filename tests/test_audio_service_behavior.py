"""Behavioral regression tests for audio processing and speech services."""

import base64
import io
import os
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_service_app_helpers import (
    FakeUploadFile,
    build_request,
    build_fastapi_stub,
    build_prometheus_stub,
    build_soundfile_stub,
    build_torch_stub,
    build_transformers_stub,
    build_tts_stub,
    load_module,
)


def _wav_bytes(duration_seconds: float = 0.2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * int(16000 * duration_seconds))
    return buffer.getvalue()


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
    tts_pkg, tts_api = build_tts_stub()
    fastapi_stub, responses_stub = build_fastapi_stub()
    return load_module(
        monkeypatch,
        "services.tts.app",
        "services/tts/app.py",
        {
            "torch": build_torch_stub(),
            "transformers": build_transformers_stub(),
            "soundfile": build_soundfile_stub(),
            "TTS": tts_pkg,
            "TTS.api": tts_api,
            "fastapi": fastapi_stub,
            "fastapi.responses": responses_stub,
            "prometheus_client": build_prometheus_stub(),
        },
    )


def test_enhanced_audio_validator_converts_browser_audio_and_rejects_invalid_output(monkeypatch):
    from services.api_gateway.enhanced_audio_validation import EnhancedAudioValidator

    validator = EnhancedAudioValidator()
    validator.ffmpeg_available = True
    monkeypatch.setattr(validator, "_convert_with_ffmpeg", lambda *_: _wav_bytes())

    success, converted, error, details = validator.validate_and_convert_audio(b"ID3browser-audio")

    assert success is True
    assert error == ""
    assert converted.startswith(b"RIFF")
    assert details["conversion_method"] == "ffmpeg"
    assert details["sample_rate"] == 16000

    monkeypatch.setattr(validator, "_convert_with_ffmpeg", lambda *_: b"not-a-wav")
    success, _, error, details = validator.validate_and_convert_audio(b"ID3broken-audio")

    assert success is False
    assert "konnte nicht" in error.lower()
    assert "conversion_wav_error" in details


def test_enhanced_audio_validation_preserves_valid_wav_metadata():
    from services.api_gateway.enhanced_audio_validation import enhanced_validate_audio_input

    result = enhanced_validate_audio_input(_wav_bytes())

    assert result.is_valid is True
    assert result.sample_rate == 16000
    assert result.channels == 1
    assert result.duration_seconds == pytest.approx(0.2)
    assert result.details["format_details"]["original_format"] == "wav"


def test_audio_storage_separates_files_and_cleans_only_expired_audio(monkeypatch, tmp_path):
    from services.api_gateway import audio_storage

    original_dir = tmp_path / "original"
    translated_dir = tmp_path / "translated"
    monkeypatch.setattr(audio_storage, "AUDIO_BASE_DIR", tmp_path)
    monkeypatch.setattr(audio_storage, "ORIGINAL_AUDIO_DIR", original_dir)
    monkeypatch.setattr(audio_storage, "TRANSLATED_AUDIO_DIR", translated_dir)

    payload = base64.b64encode(b"WAV-DATA").decode()
    assert audio_storage.save_original_audio("message-1", payload) == "/api/audio/input_message-1.wav"
    assert audio_storage.save_translated_audio("message-1", payload) == "/api/audio/message-1.wav"
    assert audio_storage.get_audio_file_path("input_message-1.wav") == original_dir / "input_message-1.wav"
    assert audio_storage.get_audio_file_path("message-1.wav") == translated_dir / "message-1.wav"

    expired = original_dir / "input-expired.wav"
    fresh = translated_dir / "fresh.wav"
    expired.write_bytes(b"old")
    fresh.write_bytes(b"new")
    old_timestamp = time.time() - (audio_storage.RETENTION_HOURS + 1) * 3600
    os.utime(expired, (old_timestamp, old_timestamp))

    stats = audio_storage.cleanup_old_audio_files()

    assert stats["deleted_original"] == 1
    assert stats["deleted_translated"] == 0
    assert not expired.exists()
    assert fresh.exists()
    assert audio_storage.get_disk_usage()["total_files"] == 3


@pytest.mark.asyncio
async def test_asr_returns_debuggable_fallback_when_model_is_unavailable(asr_service):
    asr_service.model_loaded = False

    response = await asr_service.transcribe(
        FakeUploadFile(b"audio"), build_request(query_params={"debug": "true"}), lang="de"
    )

    assert response["text"] == "Hallo Welt"
    assert response["fallback"] is True
    assert response["debug"]["error"] == "ASR-Modell nicht geladen"


@pytest.mark.asyncio
async def test_translation_returns_debug_response_when_generation_fails(translation_service, monkeypatch):
    translation_service.model_loaded = True
    translation_service.m2m_model = object()
    translation_service.m2m_tokenizer = SimpleNamespace(lang_code_to_id={"de": 0, "en": 1})
    translation_service.supported_langs = ["de", "en"]
    monkeypatch.setattr(
        translation_service,
        "_translate_texts",
        lambda *_: (_ for _ in ()).throw(RuntimeError("backend unavailable")),
    )

    response = await translation_service.translate(
        build_request(
            {"text": "Hallo", "source_lang": "de", "target_lang": "en", "debug": True}
        )
    )

    assert response.status_code == 500
    assert b'"translations":null' in response.body
    assert b"Translation failed: backend unavailable" in response.body


@pytest.mark.asyncio
async def test_tts_returns_structured_error_when_renderer_fails(tts_service, monkeypatch):
    monkeypatch.setattr(tts_service, "get_tts_model", lambda _: object())

    async def fail_renderer(*_args):
        raise RuntimeError("audio renderer failed")

    monkeypatch.setattr(tts_service, "_render_audio_bytes", fail_renderer)
    response = await tts_service.synthesize(
        build_request({"text": "Hallo", "lang": "de", "debug": True})
    )

    assert response.status_code == 500
    assert b'"fallback":false' in response.body
    assert b"TTS fehlgeschlagen: audio renderer failed" in response.body
