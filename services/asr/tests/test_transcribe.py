import hashlib
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.asr import app as asr_app
from services.asr.app import app

client = TestClient(app)
SAMPLE_WAV = Path(__file__).with_name("sample.wav")


@pytest.fixture
def without_ffmpeg(monkeypatch):
    """Normalisation is ffmpeg's job, and CI has no ffmpeg; these tests are about the rest."""

    def copy_as_normalised(path):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as copy:
            shutil.copyfile(path, copy.name)
            return copy.name

    monkeypatch.setattr(asr_app, "normalize_to_wav16k", copy_as_normalised)


def test_model_loader_uses_large_v3_turbo(monkeypatch):
    calls = []

    def load_model(model_name, *, device):
        calls.append((model_name, device))
        return object()

    monkeypatch.setattr(asr_app.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(asr_app.whisper, "load_model", load_model)

    asr_app._load_asr_model()

    assert calls == [("large-v3-turbo", "cpu")]


@pytest.mark.usefixtures("without_ffmpeg")
def test_transcribe_success():
    with SAMPLE_WAV.open("rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"lang": "de"},
        )
    assert response.status_code == 200
    # The model's own words: "any non-empty text" also passed for the error
    # transcript this service used to invent when transcription failed.
    assert response.json() == {
        "text": "dummy transcription in de",
        "fallback": False,
        "model": "whisper-large-v3-turbo",
        "model_version": "unknown",
        # The stand-in normalisation copies the upload, so its hash is the upload's.
        "input_sha256": hashlib.sha256(SAMPLE_WAV.read_bytes()).hexdigest(),
    }


def test_model_version_is_the_checkpoint_hash_in_whispers_model_url(monkeypatch):
    checkpoint = "aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a"
    monkeypatch.setattr(
        asr_app.whisper,
        "_MODELS",
        {
            "large-v3-turbo": f"https://example.invalid/whisper/models/{checkpoint}/large-v3-turbo.pt"
        },
        raising=False,
    )

    assert asr_app._model_version() == checkpoint


def test_model_version_is_unknown_for_a_url_without_a_checkpoint_hash(monkeypatch):
    monkeypatch.setattr(
        asr_app.whisper,
        "_MODELS",
        {"large-v3-turbo": "https://example.invalid/large-v3-turbo.pt"},
        raising=False,
    )

    assert asr_app._model_version() == "unknown"


@pytest.mark.usefixtures("without_ffmpeg")
def test_transcribe_debug_response_identifies_large_v3_turbo():
    with SAMPLE_WAV.open("rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"lang": "de", "debug": "true"},
        )

    assert response.status_code == 200
    assert response.json()["debug"]["model"] == "whisper-large-v3-turbo"


PRODUCT_LANGUAGES = [
    "de", "en", "ar", "tr", "ru", "uk", "am", "fa",
    "it", "ro", "pl", "bg", "el", "fr", "es", "pt", "sq", "hu", "zh", "hi",
]  # fmt: skip


def test_supported_languages_are_the_product_languages():
    response = client.get("/supported-languages")

    assert sorted(response.json()["languages"]) == sorted(PRODUCT_LANGUAGES)


@pytest.mark.usefixtures("without_ffmpeg")
@pytest.mark.parametrize("lang", PRODUCT_LANGUAGES)
def test_transcribes_in_every_product_language(lang):
    with SAMPLE_WAV.open("rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"lang": lang},
        )

    assert response.status_code == 200
    assert response.json()["text"] == f"dummy transcription in {lang}"


@pytest.mark.parametrize("language", ["xx", "ti", "ku"])
def test_transcribe_invalid_language(language):
    with SAMPLE_WAV.open("rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"lang": language},
        )
    assert response.status_code == 400


def test_a_failed_normalisation_is_a_500_not_a_transcript(monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN", "/nonexistent/ffmpeg")

    with SAMPLE_WAV.open("rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"lang": "de"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Transcription failed"}
