from fastapi.testclient import TestClient

from services.translation.app import app

client = TestClient(app)


def test_languages():
    response = client.get("/languages")
    assert response.status_code == 200
    data = response.json()
    assert "languages" in data
    assert isinstance(data["languages"], list)


def test_language_discovery_excludes_removed_model_languages():
    response = client.get("/languages")
    assert response.status_code == 200
    assert response.json()["languages"] == ["ar", "de", "en", "tr"]
    assert response.json()["count"] == 4
