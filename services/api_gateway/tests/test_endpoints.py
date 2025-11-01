import pytest
from fastapi.testclient import TestClient
from services.api_gateway.app import app

client = TestClient(app)

def test_endpoints_exist():
    for endpoint in ["/", "/upload", "/pipeline", "/metrics"]:
        response = client.options(endpoint)
        assert response.status_code in (200, 204, 405, 422)
