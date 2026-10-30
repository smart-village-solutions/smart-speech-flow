"""The ceremony routes: permissions, step-up, wire encodings and a whole ceremony over HTTP."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.ceremony import CeremonyService
from services.api_gateway.recording.ceremony_model import (
    CeremonyParticipant,
    CeremonyRecord,
    CeremonySnapshot,
    DealingRecord,
)
from services.api_gateway.recording.crypto.encoding import b64url, from_b64url, scalar_from_bytes
from services.api_gateway.routes.recording_ceremony import get_ceremony
from services.api_gateway.tenant_context import require_studio_tenant_context
from tests.recording_ceremony_actors import (
    ANNA,
    BERND,
    CARLA,
    DEVICE,
    ORG_ADMIN,
    POLYNOMIALS,
    TENANT,
    gateway_secrets,
)
from tests.recording_fakes import FakeCeremonyRepository, FakeCustodianDirectory

BASE = "/api/admin/recording/ceremony"
MANAGE = "ssf.configuration.tenant.manage"
CUSTODIAN = "ssf.recording.recovery.custodian"


class Caller:
    def __init__(self) -> None:
        self.claims: dict = {}

    def be(self, sub: str, permission: str, *, fresh: bool = True) -> None:
        self.claims = {
            "sub": sub,
            "_ssf_verified_tenant_id": TENANT,
            "ssf_permissions": [permission],
        }
        if fresh:
            self.claims |= {"acr": "mfa", "auth_time": int(time.time()) - 5}


@pytest.fixture
def http():
    repository = FakeCeremonyRepository(keys={h.sub: h.key_record() for h in (ANNA, BERND, CARLA)})
    service = CeremonyService(
        repository=repository,
        directory=FakeCustodianDirectory({"anna": "Anna", "bernd": "Bernd", "carla": "Carla"}),
        secrets=gateway_secrets(),
    )
    caller = Caller()
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides[require_ssf_user] = lambda: caller.claims
    app.dependency_overrides[get_ceremony] = lambda: service
    yield TestClient(app), caller, repository
    app.dependency_overrides.pop(get_ceremony, None)
    app.dependency_overrides.pop(require_ssf_user, None)


def _code(response) -> str:
    return response.json()["detail"]["error_code"]


def _start(client, caller, *, paper: bool = True):
    caller.be(ORG_ADMIN, MANAGE)
    body = {"k": 2, "custodians": ["carla", "anna", "bernd"]}
    if paper:
        body["paper_device_pub"] = b64url(DEVICE.enc_pub)
    return client.post(BASE, json=body)


def _snapshot(body: dict) -> CeremonySnapshot:
    """The browser's view, rebuilt into the gateway's record types for the test actors."""
    participants = tuple(
        CeremonyParticipant(
            p["holder_index"],
            p["holder_ref"],
            p["kind"],
            p["display_name"],
            from_b64url(p["enc_pub"]),
            None if p["sig_pub"] is None else from_b64url(p["sig_pub"]),
            from_b64url(p["fingerprint"]),
        )
        for p in body["participants"]
    )
    dealings = tuple(
        DealingRecord(
            d["dealer_index"],
            tuple(from_b64url(c) for c in d["commitments"]),
            scalar_from_bytes(from_b64url(d["c"])),
            scalar_from_bytes(from_b64url(d["s"])),
            from_b64url(d["signature"]),
            None,
            {},
        )
        for d in body["dealings"]
    )
    transcript = body["transcript_hash"]
    ceremony = CeremonyRecord(
        TENANT,
        body["ceremony_id"],
        body["k"],
        body["started_by"],
        None,
        None,
        body["status"],
        (),
        None if transcript is None else from_b64url(transcript),
    )
    return CeremonySnapshot(ceremony, participants, dealings, ())


def _dealing_body(submission) -> dict:
    return {
        "commitments": [b64url(c) for c in submission.commitments],
        "c": b64url(submission.proof_c.to_bytes(32, "big")),
        "s": b64url(submission.proof_s.to_bytes(32, "big")),
        "signature": b64url(submission.signature),
        "subshares": {str(i): sealed for i, sealed in submission.subshares.items()},
    }


def test_a_whole_ceremony_over_http(http):
    client, caller, repository = http
    started = _start(client, caller)
    assert started.status_code == 201
    view = _snapshot(started.json())
    ceremony_id = view.ceremony.ceremony_id

    for holder in (ANNA, BERND, CARLA):
        caller.be(holder.sub, CUSTODIAN)
        dealt = client.post(
            f"{BASE}/{ceremony_id}/dealings",
            json=_dealing_body(holder.deal(view, POLYNOMIALS[holder.sub])),
        )
        assert dealt.status_code == 201
    assert dealt.json() == {"status": "confirming"}

    caller.be("anna", CUSTODIAN)
    view = _snapshot(client.get(BASE).json()["ceremony"])
    for holder in (ANNA, BERND, CARLA):
        caller.be(holder.sub, CUSTODIAN)
        index = view.custodian(holder.sub).holder_index
        received = client.get(f"{BASE}/{ceremony_id}/subshares").json()["subshares"]
        share = holder.share(view, index, {int(j): s for j, s in received[str(index)].items()})
        signature, sealed = holder.confirmation(view, index, share, view.ceremony.transcript_hash)
        confirmed = client.post(
            f"{BASE}/{ceremony_id}/confirmations",
            json={"transcript_signature": b64url(signature), "encrypted_share": sealed},
        )
        assert confirmed.json() == {"status": "confirming"}

    # Paper confirmation works without a fresh MFA login, by design.
    caller.be(ORG_ADMIN, MANAGE, fresh=False)
    paper = client.post(
        f"{BASE}/{ceremony_id}/paper-confirmation",
        json={"transcript_hash": b64url(view.ceremony.transcript_hash)},
    )
    assert paper.json() == {"status": "active"}
    state = client.get(BASE).json()
    assert state["ceremony"] is None
    assert (state["recovery_key"]["k"], state["recovery_key"]["n"]) == (2, 5)
    assert len(state["recovery_key"]["transcript_display"].split()) == 10
    assert state["usable_shares"] == 0  # the fake's count: served as the store answers it


def test_custodians_are_ordered_by_subject_not_by_request(http):
    client, caller, _ = http
    started = _start(client, caller, paper=False).json()
    assert [p["holder_ref"] for p in started["participants"]] == ["anna", "bernd", "carla"]


@pytest.mark.parametrize(
    ("method", "path", "permission"),
    [
        ("post", "", CUSTODIAN),
        ("get", "/candidates", CUSTODIAN),
        # A resharing's dealer is checked by identity, but still needs to be staff (§9.7).
        ("post", "/00000000-0000-4000-8000-000000000000/dealings", "ssf.analytics.view"),
        ("post", "/00000000-0000-4000-8000-000000000000/paper-confirmation", CUSTODIAN),
        ("get", "", "ssf.analytics.view"),
        ("post", "/resharing", CUSTODIAN),
        ("post", "/00000000-0000-4000-8000-000000000000/paper-dealings", CUSTODIAN),
        ("get", "/00000000-0000-4000-8000-000000000000/dealer", "ssf.analytics.view"),
        # Only a resharing's dealer may act without the custodian permission (§9.7).
        ("get", "/00000000-0000-4000-8000-000000000000/subshares", "ssf.recording.request"),
        ("post", "/00000000-0000-4000-8000-000000000000/confirmations", "ssf.recording.request"),
    ],
)
def test_each_route_requires_its_permission(http, method, path, permission):
    client, caller, _ = http
    caller.be("someone", permission)
    url = f"{BASE}{path}"
    response = client.get(url) if method == "get" else client.post(url, json={})
    assert response.status_code == 403
    assert _code(response) == "PERMISSION_REQUIRED"


def test_starting_dealing_and_confirming_need_a_fresh_mfa_login(http):
    client, caller, _ = http
    caller.be(ORG_ADMIN, MANAGE, fresh=False)
    body = {"k": 2, "custodians": ["anna", "bernd", "carla"]}
    assert _code(client.post(BASE, json=body)) == "STEP_UP_REQUIRED"
    caller.be("anna", CUSTODIAN, fresh=False)
    some_id = "00000000-0000-4000-8000-000000000000"
    assert _code(client.post(f"{BASE}/{some_id}/dealings", json={})) == "STEP_UP_REQUIRED"
    assert _code(client.post(f"{BASE}/{some_id}/confirmations", json={})) == "STEP_UP_REQUIRED"


def test_a_custodian_can_abort_without_a_fresh_login(http):
    client, caller, _ = http
    ceremony_id = _start(client, caller).json()["ceremony_id"]
    caller.be("bernd", CUSTODIAN, fresh=False)
    response = client.post(f"{BASE}/{ceremony_id}/abort", json={"reason": "subshare_invalid"})
    assert response.status_code == 204
    state = client.get(BASE).json()
    assert state["ceremony"] is None
    assert state["last_failed"]["ceremony_id"] == ceremony_id
    assert state["last_failed"]["reason"] == "subshare_invalid"


def test_ceremony_errors_keep_their_codes(http):
    client, caller, _ = http
    _start(client, caller)
    assert _code(_start(client, caller)) == "CEREMONY_IN_PROGRESS"
    caller.be(ORG_ADMIN, MANAGE)
    bad_device = client.post(
        BASE, json={"k": 2, "custodians": ["a", "b", "c"], "paper_device_pub": "*" * 87}
    )
    assert bad_device.status_code == 422


def test_without_a_recording_database_the_routes_answer_503(http):
    client, caller, _ = http
    app.dependency_overrides.pop(get_ceremony)
    caller.be(ORG_ADMIN, MANAGE)
    response = client.get(BASE)
    assert response.status_code == 503
    assert _code(response) == "RECORDING_UNAVAILABLE"
