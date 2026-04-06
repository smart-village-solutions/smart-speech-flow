from fastapi.testclient import TestClient

from services.asr.app import app

client = TestClient(app)


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "# HELP asr_requests_total" in response.text or "# HELP" in response.text
