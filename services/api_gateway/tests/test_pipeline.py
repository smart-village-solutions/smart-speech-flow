import pytest
from fastapi.testclient import TestClient
import os
from services.api_gateway.app import app

client = TestClient(app)
SAMPLE_WAV_PATH = os.path.join(os.path.dirname(__file__), "sample.wav")

def test_speech_translate_sample():
    with open(SAMPLE_WAV_PATH, "rb") as f:
        response = client.post(
            "/pipeline",
            files={"file": ("sample.wav", f, "audio/wav")},
            data={"source_lang": "de", "target_lang": "en"}
        )
    assert response.status_code in (200, 400, 422)

# Mapping: Dateiname -> (source_lang, target_lang)
EXAMPLES = [
    ("examples/German.wav", "de", "en"),
    ("examples/Amharic.wav", "am", "de"),
    ("examples/Arabic.wav", "ar", "de"),
    ("examples/English.wav", "en", "de"),
    ("examples/Persian.wav", "fa", "de"),
    ("examples/Russian.wav", "ru", "de"),
    ("examples/Turkish.wav", "tr", "de"),
    ("examples/Ukrainian.wav", "uk", "de"),
]

@pytest.mark.parametrize("file_path,source_lang,target_lang", EXAMPLES)
def test_pipeline_example(file_path, source_lang, target_lang):
    assert os.path.exists(file_path), f"Datei nicht gefunden: {file_path}"
    with open(file_path, "rb") as f:
        response = client.post(
            "/pipeline",
            files={"file": (os.path.basename(file_path), f, "audio/wav")},
            data={"source_lang": source_lang, "target_lang": target_lang}
        )
    assert response.status_code == 200, f"Status: {response.status_code}, Inhalt: {response.text}"
    data = response.json()
    assert "translatedText" in data, f"Kein 'translatedText' im Ergebnis: {data}"
    assert isinstance(data["translatedText"], str) and len(data["translatedText"]) > 0
    assert "originalText" in data, f"Kein 'originalText' im Ergebnis: {data}"
    assert isinstance(data["originalText"], str)
    assert "audioBase64" in data, f"Kein 'audioBase64' im Ergebnis: {data}"
    assert isinstance(data["audioBase64"], (str, type(None)))
