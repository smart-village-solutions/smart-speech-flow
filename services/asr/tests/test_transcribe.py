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
    assert response.json() == {"text": "dummy transcription in de", "fallback": False}


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


def test_transcribe_invalid_language():
    with SAMPLE_WAV.open("rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"lang": "xx"},
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
