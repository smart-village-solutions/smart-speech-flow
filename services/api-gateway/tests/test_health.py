import pytest
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "Smart Speech Flow API-Gateway" in response.text
