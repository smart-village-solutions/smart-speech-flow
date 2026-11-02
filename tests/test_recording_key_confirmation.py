"""The mailed link's service and routes: no login, the tenant from the token (spec §9.9)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.crypto.encoding import b64url
from services.api_gateway.recording.key_confirmation import (
    KeyConfirmationError,
    KeyConfirmations,
)
from services.api_gateway.recording.key_confirmation_repository import LinkDetails
from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.reenrolment_email import token_hash
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.routes.recording_key_confirmation import get_key_confirmations

NOW = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
TOKEN = bytes(range(32))
LINK = b64url(TOKEN)
FINGERPRINT = b"\x05" * 32
DETAILS = LinkDetails(FINGERPRINT, NOW, NOW + timedelta(minutes=30))


class FakeStore:
    def __init__(self, answer=None, tenant="tenant-a", error=None) -> None:
        self.answer, self.tenant, self.error = answer, tenant, error
        self.calls: list[tuple] = []

    async def tenant_of(self, hashed):
        self.calls.append(("tenant_of", hashed))
        if self.error is not None:
            raise self.error
        return self.tenant

    async def sweep(self, tenant_id, now, *, keep=None):
        self.calls.append(("sweep", tenant_id, now, keep))

    async def lookup(self, tenant_id, hashed, now):
        self.calls.append(("lookup", tenant_id, hashed, now))
        return DETAILS if self.answer is None else self.answer

    async def confirm(self, tenant_id, hashed, now):
        self.calls.append(("confirm", tenant_id, hashed, now))
        return FINGERPRINT if self.answer is None else self.answer

    async def decline(self, tenant_id, hashed, now):
        self.calls.append(("decline", tenant_id, hashed, now))
        return self.answer


def _service(store):
    return KeyConfirmations(store=store, clock=lambda: NOW)


async def test_the_tenant_comes_from_the_token_and_the_tenant_is_swept_first():
    store = FakeStore()

    assert await _service(store).confirm(LINK) == FINGERPRINT

    hashed = token_hash(TOKEN)
    assert store.calls == [
        ("tenant_of", hashed),
        ("sweep", "tenant-a", NOW, hashed),
        ("confirm", "tenant-a", hashed, NOW),
    ]


@pytest.mark.parametrize("token", ["", "abc", b64url(bytes(31)), b64url(bytes(33)), "!" * 43])
async def test_a_malformed_token_is_an_invalid_link_without_a_query(token):
    store = FakeStore()
    with pytest.raises(KeyConfirmationError, match="link_invalid"):
        await _service(store).lookup(token)
    assert store.calls == []


async def test_an_unknown_token_is_an_invalid_link():
    store = FakeStore(tenant=None)
    with pytest.raises(KeyConfirmationError, match="link_invalid"):
        await _service(store).decline(LINK)
    assert [call[0] for call in store.calls] == ["tenant_of"]


@pytest.mark.parametrize("code", ["link_invalid", "link_expired", "ceremony_in_progress"])
async def test_a_refusal_passes_through(code):
    with pytest.raises(KeyConfirmationError, match=code):
        await _service(FakeStore(Refused(code))).confirm(LINK)


async def test_a_storage_failure_is_unavailable():
    store = FakeStore(error=RecordingStorageUnavailable("down"))
    with pytest.raises(KeyConfirmationError, match="unavailable"):
        await _service(store).lookup(LINK)


@pytest.fixture
def client():
    services: dict[str, KeyConfirmations] = {}

    def build(store: FakeStore) -> TestClient:
        services["current"] = _service(store)
        app.dependency_overrides[get_key_confirmations] = lambda: services["current"]
        return TestClient(app)

    yield build
    app.dependency_overrides.pop(get_key_confirmations, None)


BASE = "/api/recording/key-confirmation"


def _code(response) -> str:
    return response.json()["detail"]["error_code"]


def test_the_routes_need_no_login(client):
    def refuse():
        raise AssertionError("no login is read")

    app.dependency_overrides[require_ssf_user] = refuse
    try:
        store = FakeStore()
        api = client(store)
        shown = api.post(f"{BASE}/lookup", json={"token": LINK})
        confirmed = api.post(f"{BASE}/confirm", json={"token": LINK})
        declined = api.post(f"{BASE}/decline", json={"token": LINK})
    finally:
        app.dependency_overrides.pop(require_ssf_user, None)

    assert shown.status_code == 200
    assert shown.json() == {
        "fingerprint": b64url(FINGERPRINT),
        "fingerprint_display": shown.json()["fingerprint_display"],
        "requested_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=30)).isoformat(),
    }
    assert len(shown.json()["fingerprint_display"].split()) == 10
    assert confirmed.status_code == 200 and confirmed.json()["fingerprint"] == b64url(FINGERPRINT)
    assert declined.status_code == 204
    assert LINK not in shown.text + confirmed.text


def test_a_named_tenant_is_never_consulted(client):
    store = FakeStore()
    api = client(store)
    answer = api.post(
        f"{BASE}/confirm?tenant_id=tenant-b",
        json={"token": LINK},
        headers={"X-Tenant-Id": "tenant-b"},
    )
    assert answer.status_code == 200
    assert {call[1] for call in store.calls if call[0] != "tenant_of"} == {"tenant-a"}


@pytest.mark.parametrize(
    ("answer", "status", "code"),
    [
        (Refused("link_invalid"), 404, "LINK_INVALID"),
        (Refused("link_expired"), 410, "LINK_EXPIRED"),
        (Refused("ceremony_in_progress"), 409, "CEREMONY_IN_PROGRESS"),
    ],
)
@pytest.mark.parametrize("route", ["lookup", "confirm", "decline"])
def test_each_refusal_has_its_code(client, answer, status, code, route):
    response = client(FakeStore(answer)).post(f"{BASE}/{route}", json={"token": LINK})
    assert (response.status_code, _code(response)) == (status, code)


def test_storage_failure_is_503(client):
    store = FakeStore(error=RecordingStorageUnavailable("down"))
    response = client(store).post(f"{BASE}/lookup", json={"token": LINK})
    assert (response.status_code, _code(response)) == (503, "RECORDING_UNAVAILABLE")


@pytest.mark.parametrize("body", [{}, {"token": LINK, "extra": 1}, {"token": "x" * 44}])
def test_a_bad_body_is_refused_without_echoing_it(client, body):
    response = client(FakeStore()).post(f"{BASE}/confirm", json=body)
    assert response.status_code == 422 and "x" * 44 not in response.text


def test_an_unwired_gateway_answers_503():
    response = TestClient(app).post(f"{BASE}/lookup", json={"token": LINK})
    assert (response.status_code, _code(response)) == (503, "RECORDING_UNAVAILABLE")
