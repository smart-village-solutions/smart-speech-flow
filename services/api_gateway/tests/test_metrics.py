import pytest
from fastapi.testclient import TestClient
from services.api_gateway.app import app

client = TestClient(app)

def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "# HELP" in response.text or "# TYPE" in response.text
