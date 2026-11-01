"""The key routes enforce permission, step-up and their coded errors."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.keys import KeyEnrolmentService
from services.api_gateway.recording.reenrolment import Reenrolled, ReenrolmentError
from services.api_gateway.recording.reenrolment_repository import ReenrolmentImpact
from services.api_gateway.recording.secrets import ServerLayer
from services.api_gateway.routes.recording import get_key_enrolment, get_reenrolment
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


def test_a_blob_the_server_layer_cannot_open_is_a_coded_error(client_for):
    repository = FakeRecordingRepository()
    enrolled_with = KeyEnrolmentService(
        repository=repository, server_layer=ServerLayer(os.urandom(32))
    )
    assert (
        client_for(_claims(), enrolled_with)
        .post("/api/admin/recording/keys", json=enrolment_body())
        .status_code
        == 201
    )
    # A replaced blob key, or a damaged row, leaves the stored blob unopenable.
    rotated = KeyEnrolmentService(repository=repository, server_layer=ServerLayer(os.urandom(32)))
    response = client_for(_claims(), rotated).get("/api/admin/recording/keys/me")
    assert response.status_code == 500
    assert _code(response) == "KEY_UNREADABLE"
    assert [event.event_type for event in repository.audit] == ["key_enrolled"]


class FakeReenrolment:
    def __init__(self, error: str | None = None, status: str = "active") -> None:
        self.error, self.status = error, status
        self.calls: list[tuple] = []

    async def reenrol(self, tenant_id, user_sub, enrolment, replaces_version):
        self.calls.append((tenant_id, user_sub, replaces_version))
        if self.error is not None:
            raise ReenrolmentError(self.error)
        return Reenrolled(self.status, bytes(32))

    async def impact(self, tenant_id, user_sub):
        if self.error is not None:
            raise ReenrolmentError(self.error)
        return ReenrolmentImpact(True, 2, 1)


@pytest.fixture
def reenrolment_client():
    def build(claims: dict, service: FakeReenrolment) -> TestClient:
        app.dependency_overrides.pop(require_studio_tenant_context, None)
        app.dependency_overrides[require_ssf_user] = lambda: claims
        app.dependency_overrides[get_reenrolment] = lambda: service
        return TestClient(app)

    yield build
    app.dependency_overrides.pop(get_reenrolment, None)
    app.dependency_overrides.pop(require_ssf_user, None)


REENROL = "/api/admin/recording/keys/reenrolment"


@pytest.mark.parametrize("status", ["active", "pending_confirmation"])
def test_a_re_enrolment_answers_its_status_and_the_new_fingerprint(reenrolment_client, status):
    service = FakeReenrolment(status=status)
    client = reenrolment_client(_claims(), service)

    answer = client.post(REENROL, json={**enrolment_body(), "replaces_version": 3})

    assert answer.status_code == 201
    assert answer.json()["status"] == status
    assert len(answer.json()["fingerprint_display"].split()) == 10
    assert service.calls == [(TENANT, "alice", 3)]


def test_a_re_enrolment_without_a_fresh_mfa_login_asks_for_step_up(reenrolment_client):
    service = FakeReenrolment()
    client = reenrolment_client(_claims(fresh=False), service)
    answer = client.post(REENROL, json={**enrolment_body(), "replaces_version": 1})
    assert (answer.status_code, _code(answer)) == (403, "STEP_UP_REQUIRED")
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        ("key_not_enrolled", 404, "KEY_NOT_ENROLLED"),
        ("key_changed", 409, "KEY_CHANGED"),
        ("ceremony_in_progress", 409, "CEREMONY_IN_PROGRESS"),
        ("invalid", 422, "INVALID_ENROLMENT"),
        ("unavailable", 503, "RECORDING_UNAVAILABLE"),
    ],
)
def test_each_refusal_has_its_code(reenrolment_client, error, status, code):
    client = reenrolment_client(_claims(), FakeReenrolment(error))
    answer = client.post(REENROL, json={**enrolment_body(), "replaces_version": 1})
    assert (answer.status_code, _code(answer)) == (status, code)


def test_a_re_enrolment_needs_the_version_it_replaces(reenrolment_client):
    client = reenrolment_client(_claims(), FakeReenrolment())
    assert client.post(REENROL, json=enrolment_body()).status_code == 422


def test_the_impact_tells_a_custodian_the_shares_left(reenrolment_client):
    client = reenrolment_client(_claims(), FakeReenrolment())
    assert client.get(REENROL).json() == {"custodian": True, "k": 2, "usable_after": 1}
    failing = reenrolment_client(_claims(), FakeReenrolment("unavailable"))
    assert failing.get(REENROL).status_code == 503


def test_own_key_names_its_version(client_for):
    client = client_for(_claims())
    client.post("/api/admin/recording/keys", json=enrolment_body())
    assert client.get("/api/admin/recording/keys/me").json()["key_version"] == 1
