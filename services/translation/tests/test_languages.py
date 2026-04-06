from fastapi.testclient import TestClient

from services.translation.app import app

client = TestClient(app)


def test_languages():
    response = client.get("/languages")
    assert response.status_code == 200
    data = response.json()
    assert "languages" in data
    assert isinstance(data["languages"], list)
