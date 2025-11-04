import os
import sys

import pytest
import torch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from app import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "resources" in data
    assert "autoscaling" in data


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GPU nicht verfügbar")
def test_gpu_used():
    # Lade ein Modell durch Synthese-Request
    synth_response = client.post(
        "/synthesize", json={"text": "Hallo Welt", "lang": "de"}
    )
    assert synth_response.status_code == 200
    # Prüfe Health-Status
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "gpu_used" in data
    assert data["model"] is True
    assert data["gpu_used"] is True
    assert "resources" in data
    assert data["resources"]["gpu"]["available"] is True
