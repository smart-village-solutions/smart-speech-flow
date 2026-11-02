"""The verification routes: permissions, step-up, bodies and every answer (spec §10.7)."""

from __future__ import annotations

import base64
import uuid

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.verification import VerificationError, Verifications
from services.api_gateway.routes.recording_verifications import ANSWERS, get_verifications
from services.api_gateway.tenant_context import require_studio_tenant_context
from tests.test_recording_ceremony_routes import TENANT as CALLER_TENANT
from tests.test_recording_ceremony_routes import Caller
from tests.test_recording_verification_service import (
    ALICE,
    CONVERSATION,
    KEY_1,
    KEY_2,
    RITA,
    FakeAccess,
    FakeDirectory,
    FakeStore,
    REVIEWER,
    SWORN,
)
from tests.recording_verification_world import NOW, directory, grant

BASE = f"/api/admin/recording/archive/{CONVERSATION}"
REQUEST = "ssf.recording.request"


def _service(store=None, access=None, studio=None) -> Verifications:
    return Verifications(
        store=store or FakeStore(),
        directory=studio or FakeDirectory(directory(("rita", SWORN), ("ralf", REVIEWER))),
        access=access or FakeAccess(),
        clock=lambda: NOW,
    )


@pytest.fixture
def http():
    store = FakeStore()
    holder = {"service": _service(store)}
    caller = Caller()
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides[require_ssf_user] = lambda: caller.claims
    app.dependency_overrides[get_verifications] = lambda: holder["service"]
    yield TestClient(app), caller, store, holder
    for dependency in (get_verifications, require_ssf_user):
        app.dependency_overrides.pop(dependency, None)


def _code(response) -> str:
    return response.json()["detail"]["error_code"]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _body(**changes) -> dict:
    body = {
        "key_version": 1,
        "reviewer_sub": "rita",
        "reviewer_key_version": 1,
        "wraps": [
            {"key_id": w.key_id, "blob": w.blob, "signature": _b64(w.signature)}
            for w in (
                grant(CONVERSATION, key, ALICE, RITA, tenant_id=CALLER_TENANT)
                for key in (KEY_1, KEY_2)
            )
        ],
    }
    body.update(changes)
    return body


def test_reviewers_over_http(http):
    client, caller, _, _ = http
    caller.be("alice", REQUEST, fresh=False)
    response = client.get(f"{BASE}/reviewers")
    assert response.status_code == 200
    [ralf, rita] = response.json()["reviewers"]
    assert (ralf["sub"], rita["sub"], rita["sworn"], ralf["sworn"]) == ("ralf", "rita", True, False)
    assert (
        rita["fingerprint_display"]
        and rita["key_version"] == 1
        and rita["languages"] == ["de", "tr"]
    )


def test_assigning_needs_a_recording_permission_and_step_up(http):
    client, caller, store, _ = http
    caller.be("alice", "ssf.configuration.tenant.manage")
    assert _code(client.post(f"{BASE}/verifications", json=_body())) == "PERMISSION_REQUIRED"
    caller.be("alice", REQUEST, fresh=False)
    assert _code(client.post(f"{BASE}/verifications", json=_body())) == "STEP_UP_REQUIRED"
    assert store.assignments == []
    caller.be("alice", REQUEST)
    response = client.post(f"{BASE}/verifications", json=_body())
    assert response.status_code == 201
    record = response.json()
    assert (record["status"], record["reviewer_sub"], record["requested_by"]) == (
        "awaiting",
        "rita",
        "alice",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewer_sub": "-bad"},
        {"key_version": 0},
        {"wraps": []},
        {"wraps": [{"key_id": "nope", "blob": "{}", "signature": "A" * 86}]},
        {"wraps": [{"key_id": KEY_1, "blob": "{}", "signature": "A" * 85}]},
        {"extra": 1},
    ],
)
def test_malformed_bodies_never_reach_the_service(http, changes):
    client, caller, store, _ = http
    caller.be("alice", REQUEST)
    assert client.post(f"{BASE}/verifications", json=_body(**changes)).status_code == 422
    assert store.assignments == []


def test_a_signature_that_is_not_base64_is_invalid(http):
    client, caller, store, _ = http
    caller.be("alice", REQUEST)
    body = _body(wraps=[{"key_id": KEY_1, "blob": "{}", "signature": "*" * 86}])
    assert _code(client.post(f"{BASE}/verifications", json=body)) == "SIGNATURE_INVALID"


@pytest.mark.parametrize(("code", "answer"), sorted(ANSWERS.items()))
def test_every_refusal_has_its_answer(http, code, answer):
    client, caller, _, holder = http
    caller.be("alice", REQUEST)

    class Refusing(Verifications):
        async def assign(self, *args, **kwargs):
            raise VerificationError(code)

    holder["service"] = Refusing(
        store=FakeStore(), directory=FakeDirectory(None), access=FakeAccess()
    )
    response = client.post(f"{BASE}/verifications", json=_body())
    assert (response.status_code, _code(response)) == answer


def test_an_unknown_refusal_is_unavailable(http):
    client, caller, _, holder = http
    caller.be("alice", REQUEST, fresh=False)

    class Refusing(Verifications):
        async def candidates(self, *args, **kwargs):
            raise VerificationError("something_new")

    holder["service"] = Refusing(
        store=FakeStore(), directory=FakeDirectory(None), access=FakeAccess()
    )
    response = client.get(f"{BASE}/reviewers")
    assert (response.status_code, _code(response)) == (503, "RECORDING_UNAVAILABLE")


def test_the_wired_service_answers_and_without_it_503():
    caller = Caller()
    caller.be("alice", REQUEST, fresh=False)
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides[require_ssf_user] = lambda: caller.claims
    container = app.state.dependencies
    previous = container.recording_verifications
    try:
        client = TestClient(app)
        container.recording_verifications = None
        missing = client.get(f"{BASE}/reviewers")
        container.recording_verifications = _service()
        wired = client.get(f"{BASE}/reviewers")
    finally:
        container.recording_verifications = previous
        app.dependency_overrides.pop(require_ssf_user, None)
    assert (missing.status_code, _code(missing)) == (503, "RECORDING_UNAVAILABLE")
    assert wired.status_code == 200


def test_unused_ids_are_uuids(http):
    client, caller, _, _ = http
    caller.be("alice", REQUEST, fresh=False)
    assert client.get("/api/admin/recording/archive/not-a-uuid/reviewers").status_code == 422
    assert uuid.UUID(CONVERSATION)


def test_the_review_routes_need_the_review_permission(http):
    client, caller, store, _ = http
    caller.be("rita", REQUEST, fresh=False)
    assert _code(client.get("/api/admin/recording/reviews")) == "PERMISSION_REQUIRED"
    caller.be("rita", "ssf.recording.review", fresh=False)
    [row] = client.get("/api/admin/recording/reviews").json()["reviews"]
    assert row == {
        "verification_id": "v-1",
        "status": "awaiting",
        "requested_at": NOW.isoformat(),
        "requested_by": "alice",
        "started_at": NOW.isoformat(),
        "ended_at": None,
        "messages": 2,
        "openable": True,
        "requested_by_name": "Alice Employee",
    }


def test_a_review_opens_over_http_with_its_draft_and_requester(http):
    from tests.test_recording_verification_service import opened_review

    client, caller, store, _ = http
    caller.be("rita", "ssf.recording.review", fresh=False)
    store.opened = opened_review()
    response = client.get(f"/api/admin/recording/reviews/{uuid.uuid4()}")
    assert response.status_code == 200
    review = response.json()["review"]
    assert review["record"]["status"] == "in_review"
    assert review["draft"] == {"overall": "AWRyYWZ0", "notes": []}
    assert review["requester"]["sub"] == "alice" and review["requester_name"] == "Alice Employee"
    assert response.json()["conversation"]["conversation_id"] == CONVERSATION
    store.opened = None
    missing = client.get(f"/api/admin/recording/reviews/{uuid.uuid4()}")
    assert (missing.status_code, _code(missing)) == (404, "VERIFICATION_NOT_FOUND")


REVIEWS = "/api/admin/recording/reviews"


def test_start_draft_and_decline_over_http(http):
    client, caller, store, _ = http
    caller.be("rita", "ssf.recording.review", fresh=False)
    vid = uuid.uuid4()
    started = client.post(f"{REVIEWS}/{vid}/start", json={"expected_head_seq": 3})
    note = {
        "entry_id": str(uuid.uuid4()),
        "key_id": str(uuid.uuid4()),
        "ciphertext": _b64(b"\x01" + bytes(40)),
    }
    drafted = client.put(f"{REVIEWS}/{vid}/draft", json={"overall": None, "notes": [note]})
    declined = client.post(f"{REVIEWS}/{vid}/decline")
    assert (started.status_code, started.json()["status"]) == (200, "in_review")
    assert (drafted.status_code, declined.status_code) == (204, 204)
    assert [call[0] for call in store.review_calls] == ["start", "draft", "decline"]


@pytest.mark.parametrize(
    "body",
    [
        {"overall": "", "notes": []},
        {"notes": [{"entry_id": "x", "key_id": str(uuid.uuid4()), "ciphertext": "AQ"}]},
        {"notes": [], "extra": 1},
    ],
)
def test_a_malformed_draft_is_refused_before_the_service(http, body):
    client, caller, store, _ = http
    caller.be("rita", "ssf.recording.review", fresh=False)
    assert client.put(f"{REVIEWS}/{uuid.uuid4()}/draft", json=body).status_code == 422
    assert store.review_calls == []


def test_a_draft_that_is_not_base64_is_bad_notes(http):
    client, caller, store, _ = http
    caller.be("rita", "ssf.recording.review", fresh=False)
    response = client.put(
        f"{REVIEWS}/{uuid.uuid4()}/draft", json={"overall": "*" * 40, "notes": []}
    )
    assert (response.status_code, _code(response)) == (422, "BAD_NOTES")
    assert (
        client.post(f"{REVIEWS}/{uuid.uuid4()}/start", json={"expected_head_seq": 0}).status_code
        == 422
    )


def test_review_refusals_are_answered(http):
    client, caller, store, _ = http
    caller.be("rita", "ssf.recording.review", fresh=False)
    store.answer = Refused("verification_closed")
    response = client.post(f"{REVIEWS}/{uuid.uuid4()}/decline")
    assert (response.status_code, _code(response)) == (409, "VERIFICATION_CLOSED")
    store.answer = Refused("not_started")
    response = client.put(f"{REVIEWS}/{uuid.uuid4()}/draft", json={"notes": []})
    assert (response.status_code, _code(response)) == (409, "NOT_STARTED")


def test_a_decision_over_http(http):
    from tests.recording_verification_world import decision_signature
    from tests.test_recording_verification_service import HEAD, _in_review

    client, caller, store, _ = http
    caller.be("rita", "ssf.recording.review", fresh=False)
    store.record = _in_review()
    vid = str(uuid.uuid4())
    signature, _ = decision_signature(
        RITA, CONVERSATION, vid, HEAD, "approved", None, [], SWORN, tenant_id=CALLER_TENANT
    )
    body = {"outcome": "approved", "overall": None, "notes": [], "signature": _b64(signature)}
    response = client.post(f"{REVIEWS}/{vid}/decision", json=body)
    assert (response.status_code, response.json()["outcome"]) == (200, "approved")
    bad = client.post(f"{REVIEWS}/{uuid.uuid4()}/decision", json=body | {"signature": "*" * 86})
    assert (bad.status_code, _code(bad)) == (422, "SIGNATURE_INVALID")
    assert (
        client.post(
            f"{REVIEWS}/{uuid.uuid4()}/decision", json=body | {"outcome": "maybe"}
        ).status_code
        == 422
    )
    assert len(store.decisions) == 1
