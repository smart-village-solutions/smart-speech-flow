"""The key routes enforce permission, step-up and their coded errors."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.keys import KeyEnrolmentService
from services.api_gateway.recording.secrets import ServerLayer
from services.api_gateway.routes.recording import get_key_enrolment
from services.api_gateway.tenant_context import require_studio_tenant_context
from tests.recording_fakes import FakeRecordingRepository, enrolment_body

TENANT = "tenant-test"


def _claims(*, permissions=("ssf.recording.request",), fresh=True) -> dict:
    claims = {
        "sub": "alice",
        "_ssf_verified_tenant_id": TENANT,
        "ssf_permissions": list(permissions),
    }
    if fresh:
        claims |= {"acr": "mfa", "auth_time": int(time.time()) - 5}
    return claims


@pytest.fixture
def client_for():
    def build(claims: dict, service: object | None = "fake") -> TestClient:
        app.dependency_overrides.pop(require_studio_tenant_context, None)
        app.dependency_overrides[require_ssf_user] = lambda: claims
        if service == "fake":
            service = KeyEnrolmentService(
                repository=FakeRecordingRepository(), server_layer=ServerLayer(os.urandom(32))
            )
        if service is not None:
            app.dependency_overrides[get_key_enrolment] = lambda: service
        return TestClient(app)

    yield build
    app.dependency_overrides.pop(get_key_enrolment, None)
    app.dependency_overrides.pop(require_ssf_user, None)


def _code(response) -> str:
    return response.json()["detail"]["error_code"]


def test_enrolment_then_retrieval(client_for):
    client = client_for(_claims())
    enrolled = client.post("/api/admin/recording/keys", json=enrolment_body())
    assert enrolled.status_code == 201
    assert len(enrolled.json()["fingerprint_display"].split()) == 10
    own = client.get("/api/admin/recording/keys/me")
    assert own.status_code == 200
    assert own.json()["fingerprint"] == enrolled.json()["fingerprint"]


def test_a_caller_without_a_recording_permission_is_refused(client_for):
    client = client_for(_claims(permissions=("ssf.configuration.tenant.manage",)))
    response = client.get("/api/admin/recording/keys/me")
    assert response.status_code == 403
    assert _code(response) == "PERMISSION_REQUIRED"


def test_enrolment_without_a_fresh_mfa_login_asks_for_step_up(client_for):
    client = client_for(_claims(fresh=False))
    response = client.post("/api/admin/recording/keys", json=enrolment_body())
    assert response.status_code == 403
    assert _code(response) == "STEP_UP_REQUIRED"


def test_a_second_enrolment_conflicts(client_for):
    client = client_for(_claims())
    assert client.post("/api/admin/recording/keys", json=enrolment_body()).status_code == 201
    response = client.post("/api/admin/recording/keys", json=enrolment_body())
    assert response.status_code == 409
    assert _code(response) == "KEY_ALREADY_ENROLLED"


def test_an_invalid_upload_is_refused_without_echoing_it(client_for):
    client = client_for(_claims())
    body = enrolment_body() | {"blob": '{"v":1}'}
    response = client.post("/api/admin/recording/keys", json=body)
    assert response.status_code == 422
    assert _code(response) == "INVALID_ENROLMENT"
    assert '{"v":1}' not in response.text


def test_no_key_is_a_coded_404(client_for):
    response = client_for(_claims()).get("/api/admin/recording/keys/me")
    assert response.status_code == 404
    assert _code(response) == "KEY_NOT_ENROLLED"


def test_an_unwired_gateway_answers_503(client_for):
    response = client_for(_claims(), service=None).get("/api/admin/recording/keys/me")
    assert response.status_code == 503
    assert _code(response) == "RECORDING_UNAVAILABLE"
