import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from app import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_transcribe_success():
    # Beispiel: Test mit einer Dummy-Audiodatei
    with open("tests/sample.wav", "rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"language": "de"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "text" in data
    assert isinstance(data["text"], str)
    assert len(data["text"]) > 0


def test_transcribe_invalid_language():
    with open("tests/sample.wav", "rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"lang": "xx"},
        )
    assert response.status_code == 400
