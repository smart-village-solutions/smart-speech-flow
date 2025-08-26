import pytest
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "model" in data
    assert "gpu" in data


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "asr_requests_total" in response.text


def test_transcribe():
    response = client.post("/transcribe")
    assert response.status_code == 200
    data = response.json()
    assert "text" in data
    assert data["text"] == "Hallo Welt"
