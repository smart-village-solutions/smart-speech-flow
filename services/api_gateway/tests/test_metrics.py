from fastapi.testclient import TestClient

from services.api_gateway.app import app

client = TestClient(app)


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "# HELP" in response.text or "# TYPE" in response.text


def test_metrics_have_no_tenant_or_session_identity_labels():
    output = client.get("/metrics").text

    assert "tenant_id=" not in output
    assert "tenant_ref=" not in output
    assert "session_id=" not in output
