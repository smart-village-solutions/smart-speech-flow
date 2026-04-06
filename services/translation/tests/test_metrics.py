from fastapi.testclient import TestClient

from services.translation.app import app

client = TestClient(app)


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "# HELP translation_requests_total" in response.text
