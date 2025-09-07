import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "# HELP translation_requests_total" in response.text
