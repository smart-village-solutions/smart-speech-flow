from pathlib import Path

from fastapi.testclient import TestClient

from services.asr.app import app

client = TestClient(app)
SAMPLE_WAV = Path(__file__).with_name("sample.wav")


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


def test_transcribe_invalid_language():
    with SAMPLE_WAV.open("rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"lang": "xx"},
        )
    assert response.status_code == 400
