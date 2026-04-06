from fastapi.testclient import TestClient

from services.tts.app import app

client = TestClient(app)


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "# HELP" in response.text
