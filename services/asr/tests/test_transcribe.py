from pathlib import Path

from fastapi.testclient import TestClient

from services.asr import app as asr_app
from services.asr.app import app

client = TestClient(app)
SAMPLE_WAV = Path(__file__).with_name("sample.wav")


def test_model_loader_uses_large_v3_turbo():
    calls = []

    def load_model(model_name, *, device):
        calls.append((model_name, device))
        return object()

    original_loader = asr_app.whisper.load_model
    asr_app.whisper.load_model = load_model
    try:
        asr_app._load_asr_model()
    finally:
        asr_app.whisper.load_model = original_loader

    assert calls == [("large-v3-turbo", "cpu")]


def test_transcribe_success():
    # Beispiel: Test mit einer Dummy-Audiodatei
    with SAMPLE_WAV.open("rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"lang": "de"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "text" in data
    assert isinstance(data["text"], str)
    assert len(data["text"]) > 0


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
