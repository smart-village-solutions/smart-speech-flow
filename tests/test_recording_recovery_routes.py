"""The exceptional-access routes: permissions, step-up, answers and bodies (spec §9.5)."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.crypto.encoding import b64url
from services.api_gateway.recording.recovery_requests import (
    ApprovalView,
    ApproverKey,
    RecoveryRequestError,
)
from services.api_gateway.recording.recovery_requests_model import (
    DecisionRow,
    Progress,
    RequestRow,
    ScopeKey,
    ServedApproval,
    ServedPartials,
    ServedWrap,
)
from services.api_gateway.routes.recording_recovery import _ANSWERS, get_recovery_requests
from services.api_gateway.tenant_context import require_studio_tenant_context

TENANT = "tenant-test"
BASE = "/api/admin/recording/recovery"
REQUEST = str(uuid.uuid4())
CONVERSATION, KEY = str(uuid.uuid4()), str(uuid.uuid4())
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
SUPERVISE = "ssf.recording.supervise"
CUSTODIAN = "ssf.recording.recovery.custodian"
SIGNATURE = b64url(bytes(64))


def _row(status: str = "open") -> RequestRow:
    return RequestRow(REQUEST, "access", "sam", 1, KEY, "why", bytes(64), status, NOW, NOW, None)


class FakeService:
    """Answers every route; `fail` makes each raise that refusal code."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.fail: str | None = None

    def _call(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if self.fail:
            raise RecoveryRequestError(self.fail)

    async def employees(self, tenant_id, correlation_id):
        self._call("employees")
        return [("alice", "Alice"), ("bob", None)]

    async def candidates(self, tenant_id, sub, employee, start, end):
        self._call("candidates", employee)
        return []

    async def file(self, tenant_id, sub, request_id, reason, conversation_ids, signature):
        self._call("file", conversation_ids, signature)
        return (ScopeKey(CONVERSATION, KEY),)

    async def own_requests(self, tenant_id, sub):
        self._call("own_requests")
        return [(_row(), 2)]

    async def approvals(self, tenant_id, sub):
        self._call("approvals")
        return [(_row(), 1)]

    async def approval(self, tenant_id, sub, request_id, correlation_id):
        self._call("approval", request_id)
        key = ApproverKey(
            CONVERSATION, KEY, "alice", None, NOW, NOW, b"\x04" * 65, "gw-1", bytes(64)
        )
        return ApprovalView(
            _row(),
            "Sam",
            b"\x04" * 65,
            b"\x04" * 65,
            (ScopeKey(CONVERSATION, KEY),),
            (key,),
            2,
            1,
            '{"v":1}',
        )

    async def approve(self, tenant_id, sub, request_id, partials, signature):
        self._call("approve", partials, signature)

    async def decline(self, tenant_id, sub, request_id, reason):
        self._call("decline", reason)

    async def progress(self, tenant_id, sub, request_id, correlation_id):
        self._call("progress")
        decision = DecisionRow(1, 1, "carol", "approved", None, (), bytes(64), NOW, True)
        return Progress(_row(), 2, (decision,), (ScopeKey(CONVERSATION, KEY),)), {"carol": "C"}

    async def partials(self, tenant_id, sub, request_id):
        self._call("partials")
        return ServedPartials(
            (ServedWrap(CONVERSATION, KEY, "{}", "gw-1", bytes(64)),),
            (ServedApproval(1, 1, ((KEY, bytes(32)),), bytes(64), {KEY: "{p}"}),),
        )

    async def reject(self, tenant_id, sub, request_id, holder, fault):
        self._call("reject", holder, fault)

    async def report(self, tenant_id, sub, request_id, stage):
        self._call("report", stage)

    async def store(self, tenant_id, sub, request_id, wraps):
        self._call("store", wraps)
        return (KEY,)

    async def cancel(self, tenant_id, sub, request_id):
        self._call("cancel")


def _claims(*permissions: str, stepped_up: bool = True) -> dict:
    claims: dict[str, Any] = {
        "sub": "sam",
        "_ssf_verified_tenant_id": TENANT,
        "ssf_permissions": list(permissions),
    }
    if stepped_up:
        claims |= {"acr": "mfa", "auth_time": int(time.time()) - 5}
    return claims


@pytest.fixture
def client_for():
    def build(claims, service) -> TestClient:
        app.dependency_overrides.pop(require_studio_tenant_context, None)
        app.dependency_overrides[require_ssf_user] = lambda: claims
        app.dependency_overrides[get_recovery_requests] = lambda: service
        return TestClient(app)

    yield build
    for dependency in (get_recovery_requests, require_ssf_user):
        app.dependency_overrides.pop(dependency, None)


def _code(response) -> str:
    return response.json()["detail"]["error_code"]


def _file_body(**changes: Any) -> dict:
    return {
        "request_id": REQUEST,
        "reason": "Employee left.",
        "conversation_ids": [CONVERSATION],
        "signature": SIGNATURE,
    } | changes


REQUESTER_ROUTES = [
    ("get", "/employees", None),
    ("get", f"/candidates?employee=alice&from={NOW.isoformat()}&to={NOW.isoformat()}", None),
    ("post", "/requests", _file_body()),
    ("get", "/requests", None),
    ("get", f"/requests/{REQUEST}", None),
    ("get", f"/requests/{REQUEST}/partials", None),
    (
        "post",
        f"/requests/{REQUEST}/rejections",
        {"holder_index": 1, "attempt": 1, "fault": "proof_invalid"},
    ),
    ("post", f"/requests/{REQUEST}/integrity-failures", {"stage": "trust"}),
    (
        "post",
        f"/requests/{REQUEST}/wraps",
        {
            "wraps": [
                {
                    "conversation_id": CONVERSATION,
                    "key_id": KEY,
                    "blob": "{}",
                    "signature": SIGNATURE,
                }
            ]
        },
    ),
    ("post", f"/requests/{REQUEST}/cancel", None),
]
APPROVER_ROUTES = [
    ("get", "/approvals", None),
    ("get", f"/approvals/{REQUEST}", None),
    ("post", f"/approvals/{REQUEST}", {"partials": {KEY: "{}"}, "signature": SIGNATURE}),
    ("post", f"/approvals/{REQUEST}/decline", {"reason": "No."}),
]


def _send(client: TestClient, method: str, path: str, body: dict | None):
    if method == "get":
        return client.get(BASE + path)
    return client.post(BASE + path, json=body)


@pytest.mark.parametrize(("method", "path", "body"), REQUESTER_ROUTES)
def test_requester_routes_need_supervise(client_for, method, path, body):
    client = client_for(_claims(CUSTODIAN), FakeService())
    assert _send(client, method, path, body).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), APPROVER_ROUTES)
def test_approver_routes_need_the_custodian_permission(client_for, method, path, body):
    client = client_for(_claims(SUPERVISE), FakeService())
    assert _send(client, method, path, body).status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "body", "permission"),
    [
        ("post", "/requests", _file_body(), SUPERVISE),
        (*APPROVER_ROUTES[2], CUSTODIAN),
        (*APPROVER_ROUTES[3], CUSTODIAN),
    ],
)
def test_filing_approving_and_declining_need_a_fresh_step_up(
    client_for, method, path, body, permission
):
    service = FakeService()
    client = client_for(_claims(permission, stepped_up=False), service)
    response = _send(client, method, path, body)
    assert (response.status_code, _code(response)) == (403, "STEP_UP_REQUIRED")
    assert service.calls == []


@pytest.mark.parametrize(("method", "path", "body"), REQUESTER_ROUTES[5:])
def test_storing_cancelling_and_reporting_need_no_step_up(client_for, method, path, body):
    client = client_for(_claims(SUPERVISE, stepped_up=False), FakeService())
    assert _send(client, method, path, body).status_code in {200, 204}


def test_duplicate_conversations_are_refused(client_for):
    client = client_for(_claims(SUPERVISE), FakeService())
    body = _file_body(conversation_ids=[CONVERSATION, CONVERSATION])
    assert client.post(BASE + "/requests", json=body).status_code == 422


def test_filing_answers_with_its_scope(client_for):
    service = FakeService()
    response = client_for(_claims(SUPERVISE), service).post(BASE + "/requests", json=_file_body())
    assert response.status_code == 201
    assert response.json()["scope"] == [{"conversation_id": CONVERSATION, "key_id": KEY}]
    assert service.calls[0][1] == ((CONVERSATION,), bytes(64))


def test_a_bad_signature_encoding_is_refused_as_a_signature(client_for):
    body = _file_body(signature="!" * 86)
    response = client_for(_claims(SUPERVISE), FakeService()).post(BASE + "/requests", json=body)
    assert (response.status_code, _code(response)) == (422, "SIGNATURE_INVALID")


def test_not_found_at_filing_means_conversations_elsewhere_the_request(client_for):
    service = FakeService()
    service.fail = "not_found"
    client = client_for(_claims(SUPERVISE), service)
    filed = client.post(BASE + "/requests", json=_file_body())
    progress = client.get(f"{BASE}/requests/{REQUEST}")
    assert (filed.status_code, _code(filed)) == (404, "CONVERSATION_NOT_FOUND")
    assert (progress.status_code, _code(progress)) == (404, "REQUEST_NOT_FOUND")


@pytest.mark.parametrize(("code", "answer"), sorted(_ANSWERS.items()))
def test_each_refusal_maps_to_its_answer(client_for, code, answer):
    service = FakeService()
    service.fail = code
    response = client_for(_claims(CUSTODIAN), service).post(
        f"{BASE}/approvals/{REQUEST}/decline", json={"reason": "No."}
    )
    assert (response.status_code, _code(response)) == answer


def _keys_anywhere(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for item in value.values() for k in _keys_anywhere(item)}
    if isinstance(value, list):
        return {k for item in value for k in _keys_anywhere(item)}
    return set()


def test_an_approval_detail_carries_r_and_never_a_wraps_ciphertext(client_for):
    body = client_for(_claims(CUSTODIAN), FakeService()).get(f"{BASE}/approvals/{REQUEST}").json()
    assert not {"blob", "ct", "nonce"} & _keys_anywhere(body)
    [key] = body["keys"]
    assert key["ephemeral"] == b64url(b"\x04" * 65)
    assert key["signer_key_id"] == "gw-1"
    assert body["requester_name"] == "Sam"
    assert body["holder_index"] == 2


def test_progress_and_partials_bodies(client_for):
    client = client_for(_claims(SUPERVISE), FakeService())
    progress = client.get(f"{BASE}/requests/{REQUEST}").json()
    partials = client.get(f"{BASE}/requests/{REQUEST}/partials").json()
    assert progress["k"] == 2
    assert progress["decisions"][0] | {"decided_at": None} == {
        "holder_index": 1,
        "attempt": 1,
        "custodian_sub": "carol",
        "custodian_name": "C",
        "decision": "approved",
        "reason": None,
        "decided_at": None,
        "rejected": True,
    }
    assert partials["approvals"][0]["partials"] == {KEY: "{p}"}
    assert partials["approvals"][0]["signed_partials"] == [
        {"key_id": KEY, "hash": b64url(bytes(32))}
    ]
    assert partials["wraps"][0]["creator_ref"] == "gw-1"


def test_lists_and_wraps(client_for):
    service = FakeService()
    client = client_for(_claims(SUPERVISE, CUSTODIAN), service)
    assert client.get(BASE + "/requests").json()["requests"][0]["conversations"] == 2
    assert client.get(BASE + "/approvals").json()["requests"][0]["requester_sub"] == "sam"
    assert client.get(BASE + "/employees").json()["employees"][1] == {
        "sub": "bob",
        "display_name": None,
    }
    stored = client.post(f"{BASE}/requests/{REQUEST}/wraps", json=REQUESTER_ROUTES[8][2])
    assert stored.json() == {"dropped": [KEY]}


def test_without_the_service_recovery_is_unavailable(client_for):
    client = client_for(_claims(SUPERVISE), FakeService())
    app.dependency_overrides.pop(get_recovery_requests, None)
    response = client.get(BASE + "/requests")
    assert (response.status_code, _code(response)) == (503, "RECORDING_UNAVAILABLE")
