"""The key routes enforce permission, step-up and their coded errors."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.crypto.encoding import b64url
from services.api_gateway.recording.key_confirmation_repository import PendingKey
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
        "email": "alice@example.org",
        "email_verified": True,
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


@pytest.mark.parametrize("session", [{"acr": "pwd"}, {"acr": "mfa", "auth_time": 1}, {}])
def test_enrolment_uses_the_authenticated_session(client_for, session):
    client = client_for({**_claims(fresh=False), **session})
    response = client.post("/api/admin/recording/keys", json=enrolment_body())
    assert response.status_code == 201


def test_enrolment_pins_the_verified_address(client_for):
    repository = FakeRecordingRepository()
    service = KeyEnrolmentService(repository=repository, server_layer=ServerLayer(os.urandom(32)))
    client_for(_claims(), service).post("/api/admin/recording/keys", json=enrolment_body())
    assert repository.keys[(TENANT, "alice")].email == "alice@example.org"


@pytest.mark.parametrize(
    "address",
    [
        {"email_verified": False},
        {"email_verified": "true"},
        {"email_verified": None},
        {"email": ""},
        {"email": "a" * 255},
        {"email": None},
        {"email": ["alice@example.org"]},
    ],
)
def test_enrolment_needs_a_verified_address(client_for, address):
    repository = FakeRecordingRepository()
    service = KeyEnrolmentService(repository=repository, server_layer=ServerLayer(os.urandom(32)))
    claims = _claims() | address
    response = client_for(claims, service).post("/api/admin/recording/keys", json=enrolment_body())
    assert (response.status_code, _code(response)) == (409, "EMAIL_NOT_VERIFIED")
    assert repository.keys == {}


def test_an_address_of_254_characters_is_enough(client_for):
    claims = _claims() | {"email": "a" * 254}
    response = client_for(claims).post("/api/admin/recording/keys", json=enrolment_body())
    assert response.status_code == 201


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
    def __init__(self, error: str | None = None, status: str = "active", waiting=None) -> None:
        self.error, self.status, self.waiting = error, status, waiting
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

    async def pending(self, tenant_id, user_sub):
        if self.error is not None:
            raise ReenrolmentError(self.error)
        return self.waiting


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


def test_reenrolment_uses_the_authenticated_session(reenrolment_client):
    service = FakeReenrolment()
    client = reenrolment_client(_claims(fresh=False), service)
    answer = client.post(REENROL, json={**enrolment_body(), "replaces_version": 1})
    assert answer.status_code == 201
    assert service.calls == [(TENANT, "alice", 1)]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        ("key_not_enrolled", 404, "KEY_NOT_ENROLLED"),
        ("key_changed", 409, "KEY_CHANGED"),
        ("ceremony_in_progress", 409, "CEREMONY_IN_PROGRESS"),
        ("invalid", 422, "INVALID_ENROLMENT"),
        ("email_not_verified", 409, "EMAIL_NOT_VERIFIED"),
        ("mail_unavailable", 503, "MAIL_UNAVAILABLE"),
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
    assert client.get(REENROL).json() == {
        "custodian": True,
        "k": 2,
        "usable_after": 1,
        "pending": None,
    }
    failing = reenrolment_client(_claims(), FakeReenrolment("unavailable"))
    assert failing.get(REENROL).status_code == 503


def test_own_key_names_its_version(client_for):
    client = client_for(_claims())
    client.post("/api/admin/recording/keys", json=enrolment_body())
    assert client.get("/api/admin/recording/keys/me").json()["key_version"] == 1


def test_the_impact_names_a_pending_key(reenrolment_client):
    expires = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
    waiting = PendingKey(b"\x05" * 32, expires)
    client = reenrolment_client(_claims(), FakeReenrolment(waiting=waiting))
    pending = client.get(REENROL).json()["pending"]
    assert pending["fingerprint"] == b64url(b"\x05" * 32)
    assert len(pending["fingerprint_display"].split()) == 10
    assert pending["expires_at"] == expires.isoformat()
    assert reenrolment_client(_claims(), FakeReenrolment()).get(REENROL).json()["pending"] is None


def test_version_catalog_does_not_download_the_blob(client_for):
    client = client_for(_claims())
    body = enrolment_body()
    enrolled = client.post("/api/admin/recording/keys", json=body).json()
    catalog = client.get("/api/admin/recording/v2/keys/me")
    assert catalog.status_code == 200
    assert catalog.json()["activeVersion"] == 1
    version = catalog.json()["versions"][0]
    assert set(version) == {"version", "state", "fingerprint", "encPub", "sigPub", "createdAt"}
    assert (version["state"], version["fingerprint"]) == ("active", enrolled["fingerprint"])
    assert client.get("/api/admin/recording/v2/keys/me/1").json() == {
        **version,
        "blob": body["blob"],
    }
    assert client.get("/api/admin/recording/v2/keys/me/2").status_code == 404


def test_transfer_permission_is_individual_even_for_managers(client_for):
    client = client_for(_claims(permissions=("ssf.configuration.tenant.manage",)))
    response = client.get(
        "/api/admin/recording/v2/access-transfer/candidates", params={"employeeSub": "alice"}
    )
    assert (response.status_code, _code(response)) == (403, "PERMISSION_REQUIRED")


@pytest.mark.parametrize("session", [{"acr": "pwd"}, {"acr": "mfa", "auth_time": 1}, {}])
def test_org_preparation_uses_the_authenticated_session(client_for, monkeypatch, session):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from services.api_gateway.routes import recording_lifecycle_auth
    from tests import recording_crypto_reference as ref

    public = b64url(ref.public_point(1))
    example = {
        "preparationId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "keyId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "version": 1,
        "fingerprint": "f" * 43,
        "expiresAt": "2030-01-01T00:00:00.000000Z",
        "challengeEnvelope": {
            "v": 1,
            "t": "SSF-ORG-POSSESSION-V1",
            "R": public,
            "nonce": "n" * 16,
            "ct": "c" * 64,
        },
    }
    org, transfer = AsyncMock(), AsyncMock()
    org.prepare.return_value = example
    state = SimpleNamespace(recording_organisation_keys=org, recording_access_transfer=transfer)
    monkeypatch.setattr(recording_lifecycle_auth, "optional_container", lambda req: state)
    claims = {
        **_claims(permissions=("ssf.configuration.tenant.manage",), fresh=False),
        "sid": "user-session",
        **session,
    }
    response = client_for(claims).post(
        "/api/admin/recording/v2/organisation-keys/preparations",
        json={"publicKey": public, "expectedActiveKeyId": None},
    )
    assert response.status_code == 200 and response.json() == example
    transfer.authorize.assert_awaited_once_with(TENANT, "alice", "ssf.configuration.tenant.manage")


@pytest.mark.parametrize(
    "body,code",
    [
        ({"publicKey": "sensitive-private-input", "expectedActiveKeyId": None}, "INVALID_KEY"),
        (
            {
                "publicKey": "x" * 87,
                "expectedActiveKeyId": None,
                "secret_extra_name": "sensitive-private-input",
            },
            "INVALID_KEY",
        ),
    ],
)
def test_invalid_org_dto_has_a_value_free_fixed_error(client_for, body, code):
    client = client_for(
        {**_claims(permissions=("ssf.configuration.tenant.manage",)), "sid": "session"}
    )
    response = client.post("/api/admin/recording/v2/organisation-keys/preparations", json=body)
    assert response.status_code == 422 and _code(response) == code
    assert "sensitive-private-input" not in response.text
    assert "secret_extra_name" not in response.text


@pytest.mark.parametrize(
    "invalid",
    [
        {"sid": None},
        {"sid": "session", "preferred_username": "service-account-fixture"},
        {"sid": "session", "gty": "client_credentials"},
        {"sid": "session", "clientId": "client"},
    ],
)
def test_registry_rejects_non_user_tokens_and_untrusted_actor_headers(client_for, invalid):
    claims = {**_claims(permissions=("ssf.configuration.tenant.manage",), fresh=False), **invalid}
    response = client_for(claims).get(
        "/api/admin/recording/v2/organisation-keys",
        headers={"X-Actor": "alice", "X-Tenant": "other", "X-Actor-Acr": "mfa"},
    )
    assert (response.status_code, _code(response)) == (403, "PERMISSION_REQUIRED")
