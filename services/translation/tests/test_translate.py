import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_translate_success():
    response = client.post(
        "/translate",
        json={"text": "Hallo Welt", "source_lang": "de", "target_lang": "en"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "translations" in data
    assert isinstance(data["translations"], str) or isinstance(data["translations"], list)
    if isinstance(data["translations"], str):
        assert len(data["translations"]) > 0
    else:
        assert all(isinstance(t, str) and len(t) > 0 for t in data["translations"])

def test_translate_missing_fields():
    response = client.post(
        "/translate",
        json={"text": "Hallo Welt", "source_lang": "de"}  # target_lang fehlt
    )
    assert response.status_code == 400  # Der Service gibt 400 bei fehlenden Feldern

def test_translate_list():
    response = client.post(
        "/translate",
        json={"text": ["Hallo Welt", "Guten Morgen"], "source_lang": "de", "target_lang": "en"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["translations"], list)
    assert len(data["translations"]) == 2
    assert all(isinstance(t, str) and len(t) > 0 for t in data["translations"])

def test_translate_invalid_lang():
    response = client.post(
        "/translate",
        json={"text": "Hallo Welt", "source_lang": "xx", "target_lang": "en"}
    )
    assert response.status_code == 400
    data = response.json()
    assert "Unsupported language code" in data["detail"]

def test_translate_model_unavailable(monkeypatch):
    # Simuliere, dass das Modell nicht geladen ist
    monkeypatch.setattr("app.model_loaded", False)
    response = client.post(
        "/translate",
        json={"text": "Hallo Welt", "source_lang": "de", "target_lang": "en"}
    )
    assert response.status_code == 503
    data = response.json()
    assert "Model unavailable" in data["detail"]
    monkeypatch.setattr("app.model_loaded", True)  # Rücksetzen

def test_translate_empty_text():
    response = client.post(
        "/translate",
        json={"text": "", "source_lang": "de", "target_lang": "en"}
    )
    assert response.status_code in (400, 422)
