import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.api_gateway.app import app

client = TestClient(app)


def test_endpoints_exist():
    for endpoint in ["/", "/upload", "/pipeline", "/metrics"]:
        response = client.options(endpoint)
        assert response.status_code in (200, 204, 405, 422)


def test_public_languages_endpoint():
    response = client.get("/languages")
    assert response.status_code == 200

    payload = response.json()
    assert "languages" in payload
    assert isinstance(payload["languages"], dict)
    assert "de" in payload["languages"]
