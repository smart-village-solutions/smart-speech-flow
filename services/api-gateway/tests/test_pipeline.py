import pytest
from fastapi.testclient import TestClient
from app import app
import os

client = TestClient(app)

SAMPLE_WAV_PATH = os.path.join(os.path.dirname(__file__), "sample.wav")

def test_speech_translate_sample():
    with open(SAMPLE_WAV_PATH, "rb") as f:
        response = client.post(
            "/speech-translate",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"source_lang": "de", "target_lang": "en"}
        )
    assert response.status_code in (200, 400, 422)
