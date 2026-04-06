from fastapi.testclient import TestClient

from services.asr.app import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "model" in data
    assert "resources" in data
    assert "autoscaling" in data
