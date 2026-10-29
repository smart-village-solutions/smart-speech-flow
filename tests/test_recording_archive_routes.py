"""The employee's archive routes: permission, opening rule, objects, amendments (§10.6)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.archive_access import ArchiveAccessError
from services.api_gateway.recording.archive_access_repository import (
    OpenedConversation,
    OwnConversation,
)
from services.api_gateway.recording.ceremony_model import (
    CeremonyParticipant,
    CeremonyRecord,
    CeremonySnapshot,
    ConfirmationRecord,
    DealingRecord,
)
from services.api_gateway.recording.crypto.encoding import b64url
from services.api_gateway.routes.recording_archive import (
    get_archive_access,
    get_trust_source,
    trust_body,
)
from services.api_gateway.tenant_context import require_studio_tenant_context
from tests.recording_archive_fakes import recovery_record

TENANT = "tenant-test"
BASE = "/api/admin/recording/archive"
CONVERSATION = str(uuid.uuid4())
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail: str | None = None
        self.created = True

    def _maybe_fail(self):
        if self.fail:
            raise ArchiveAccessError(self.fail)

    async def conversations(self, tenant_id, sub, *, limit, started_before, before_id):
        self.calls.append(("list", sub, limit, started_before, before_id))
        return [OwnConversation(CONVERSATION, NOW, NOW, NOW, False, True, 3, 1)]

    async def open(self, tenant_id, sub, conversation_id):
        self._maybe_fail()
        self.calls.append(("open", sub, conversation_id))
        return OpenedConversation(
            conversation_id, sub, "consent", NOW, NOW, NOW, False, False, (), (), {}, (), ()
        )

    async def object(self, tenant_id, sub, conversation_id, entry_id, object_type):
        self._maybe_fail()
        return b"\x01cipher"

    async def amend(self, tenant_id, sub, conversation_id, entry_id, key_id, ciphertext):
        self._maybe_fail()
        self.calls.append(("amend", entry_id, key_id, ciphertext))
        return SimpleNamespace(entry_id=entry_id, seq=4), self.created

    async def report(self, tenant_id, sub, conversation_id, stage):
        self._maybe_fail()
        self.calls.append(("report", stage))


def _claims(permissions=("ssf.recording.request",)) -> dict:
    return {
        "sub": "alice",
        "_ssf_verified_tenant_id": TENANT,
        "ssf_permissions": list(permissions),
    }


@pytest.fixture
def client_for():
    def build(claims, service) -> TestClient:
        app.dependency_overrides.pop(require_studio_tenant_context, None)
        app.dependency_overrides[require_ssf_user] = lambda: claims
        app.dependency_overrides[get_archive_access] = lambda: service
        return TestClient(app)

    yield build
    for dependency in (get_archive_access, get_trust_source, require_ssf_user):
        app.dependency_overrides.pop(dependency, None)


def _code(response) -> str:
    return response.json()["detail"]["error_code"]


def _amendment_body() -> dict:
    return {
        "entry_id": str(uuid.uuid4()),
        "key_id": str(uuid.uuid4()),
        "ciphertext": b64url(b"\x01" * 40),
    }


def test_every_route_needs_a_recording_permission(client_for):
    client = client_for(_claims(permissions=("ssf.configuration.tenant.manage",)), FakeService())
    entry = str(uuid.uuid4())
    for method, path, body in [
        ("GET", BASE, None),
        ("GET", f"{BASE}/trust", None),
        ("GET", f"{BASE}/{CONVERSATION}", None),
        ("GET", f"{BASE}/{CONVERSATION}/objects/{entry}/record.json", None),
        ("POST", f"{BASE}/{CONVERSATION}/amendments", _amendment_body()),
        ("POST", f"{BASE}/{CONVERSATION}/integrity-failures", {"stage": "chain"}),
    ]:
        response = client.request(method, path, json=body)
        assert response.status_code == 403, path
        assert _code(response) == "PERMISSION_REQUIRED"


def test_the_list_and_an_open_serve_the_callers_view(client_for):
    service = FakeService()
    client = client_for(_claims(), service)
    listed = client.get(BASE, params={"limit": 10}).json()["conversations"]
    assert listed[0]["verification"] == "not_verified"
    assert listed[0]["amendments"] == 1
    assert service.calls[0] == ("list", "alice", 10, None, None)
    assert client.get(BASE, params={"limit": 51}).status_code == 422
    body = client.get(f"{BASE}/{CONVERSATION}").json()
    assert body["conversation"]["conversation_id"] == CONVERSATION
    assert body["conversation"]["legal_basis"] == "consent"
    assert ("open", "alice", CONVERSATION) in service.calls


def test_a_refused_open_is_a_404(client_for):
    service = FakeService()
    service.fail = "not_found"
    response = client_for(_claims(), service).get(f"{BASE}/{CONVERSATION}")
    assert (response.status_code, _code(response)) == (404, "CONVERSATION_NOT_FOUND")


def test_an_object_is_ciphertext_never_cached(client_for):
    client = client_for(_claims(), FakeService())
    response = client.get(f"{BASE}/{CONVERSATION}/objects/{uuid.uuid4()}/record.json")
    assert response.content == b"\x01cipher"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "application/octet-stream"
    unknown = client.get(f"{BASE}/{CONVERSATION}/objects/{uuid.uuid4()}/secrets.txt")
    assert (unknown.status_code, _code(unknown)) == (404, "CONVERSATION_NOT_FOUND")


@pytest.mark.parametrize(
    ("code", "status", "error_code"),
    [
        ("not_found", 404, "CONVERSATION_NOT_FOUND"),
        ("not_stored", 404, "OBJECT_NOT_STORED"),
        ("key_not_usable", 409, "KEY_NOT_USABLE"),
        ("entry_exists", 409, "ENTRY_EXISTS"),
        ("bad_ciphertext", 422, "BAD_CIPHERTEXT"),
        ("write_failed", 503, "ARCHIVE_WRITE_FAILED"),
        ("unavailable", 503, "RECORDING_UNAVAILABLE"),
    ],
)
def test_service_refusals_map_to_coded_answers(client_for, code, status, error_code):
    service = FakeService()
    service.fail = code
    response = client_for(_claims(), service).post(
        f"{BASE}/{CONVERSATION}/amendments", json=_amendment_body()
    )
    assert (response.status_code, _code(response)) == (status, error_code)
    assert response.json()["detail"].get("committed", False) is (code == "write_failed")


def test_an_amendment_passes_its_bytes_and_answers_its_entry(client_for):
    service = FakeService()
    body = _amendment_body()
    response = client_for(_claims(), service).post(f"{BASE}/{CONVERSATION}/amendments", json=body)
    assert response.status_code == 201
    assert response.json() == {"entry_id": body["entry_id"], "seq": 4}
    assert ("amend", body["entry_id"], body["key_id"], b"\x01" * 40) in service.calls


def test_a_re_post_of_an_amendment_answers_200(client_for):
    service = FakeService()
    service.created = False
    body = _amendment_body()
    response = client_for(_claims(), service).post(f"{BASE}/{CONVERSATION}/amendments", json=body)
    assert (response.status_code, response.json()["entry_id"]) == (200, body["entry_id"])


def test_a_malformed_amendment_is_refused_before_the_service(client_for):
    service = FakeService()
    client = client_for(_claims(), service)
    for body in (
        _amendment_body() | {"ciphertext": "not base64!"},
        _amendment_body() | {"entry_id": "nope"},
        _amendment_body() | {"extra": 1},
    ):
        assert client.post(f"{BASE}/{CONVERSATION}/amendments", json=body).status_code == 422
    assert service.calls == []


def test_an_integrity_report_names_one_of_the_stages(client_for):
    service = FakeService()
    client = client_for(_claims(), service)
    url = f"{BASE}/{CONVERSATION}/integrity-failures"
    assert client.post(url, json={"stage": "chain"}).status_code == 204
    assert client.post(url, json={"stage": "secret"}).status_code == 422
    assert service.calls == [("report", "chain")]


def _snapshot(encrypted_share: str) -> CeremonySnapshot:
    record = CeremonyRecord(
        tenant_id=TENANT,
        ceremony_id=str(uuid.uuid4()),
        k=2,
        started_by="admin",
        started_at=NOW,
        expires_at=NOW,
        status="active",
        gateway_keys=(("gk-1", b"\x04" + bytes(64)),),
        transcript_hash=b"\x31" * 32,
    )
    participants = tuple(
        CeremonyParticipant(index, f"holder-{index}", kind, "Anna", b"\x04" * 65, sig, b"\x07" * 32)
        for index, kind, sig in ((1, "custodian", b"\x04" * 65), (2, "paper", None))
    )
    dealing = DealingRecord(1, (b"\x04" * 65,), 5, 6, b"\x09" * 64, NOW, {2: "SUBSHARE"})
    confirmation = ConfirmationRecord(1, b"\x08" * 64, encrypted_share, NOW)
    return CeremonySnapshot(record, participants, (dealing,), (confirmation,))


def test_the_trust_body_names_only_public_fields():
    snapshot = _snapshot("SECRET-SHARE")
    body = trust_body(recovery_record(TENANT), snapshot)
    text = str(body)
    assert "SECRET-SHARE" not in text
    assert "SUBSHARE" not in text
    assert body["ceremony"]["transcript_signatures"] == [
        {"holder_index": 1, "signature": b64url(b"\x08" * 64)}
    ]
    assert [p["sig_pub"] for p in body["ceremony"]["participants"]] == [b64url(b"\x04" * 65), None]
    assert {p["display_name"] for p in body["ceremony"]["participants"]} == {None}


def test_trust_without_an_active_key_is_a_404(client_for):
    class NoKey:
        async def active_recovery_key(self, tenant_id):
            return None

    client = client_for(_claims(), FakeService())
    app.dependency_overrides[get_trust_source] = lambda: NoKey()
    response = client.get(f"{BASE}/trust")
    assert (response.status_code, _code(response)) == (404, "RECOVERY_KEY_MISSING")
