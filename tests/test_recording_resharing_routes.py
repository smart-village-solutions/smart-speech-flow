"""The resharing over HTTP: permissions, step-up, wire encodings, and the state it serves."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.recording.crypto.encoding import b64url, scalar_to_bytes
from services.api_gateway.routes.recording_ceremony import get_ceremony
from services.api_gateway.routes.recording_resharing import get_resharing
from services.api_gateway.tenant_context import require_studio_tenant_context
from tests.recording_ceremony_actors import (
    ANNA,
    BERND,
    DORA,
    EMIL,
    ORG_ADMIN,
    TENANT,
    reshare_dealing,
    share_proof,
)
from tests.test_recording_ceremony_routes import CUSTODIAN, MANAGE, Caller
from tests.test_recording_resharing import (
    FIRST_ID,
    RESHARING_ID,
    World,
    world,
)  # noqa: F401 - fixture

BASE = "/api/admin/recording/ceremony"
HOLDERS = {h.sub: h for h in (BERND, DORA, EMIL)}


@pytest.fixture
def http(world):  # noqa: F811 - the fixture imported above
    caller = Caller()
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides[require_ssf_user] = lambda: caller.claims
    app.dependency_overrides[get_ceremony] = lambda: world.ceremonies
    app.dependency_overrides[get_resharing] = lambda: world.resharing
    yield TestClient(app), caller, world
    for dependency in (get_ceremony, get_resharing, require_ssf_user):
        app.dependency_overrides.pop(dependency, None)


def _code(response) -> str:
    return response.json()["detail"]["error_code"]


def _dealing_body(dealing) -> dict:
    body = {
        "commitments": [b64url(c) for c in dealing.commitments],
        "c": b64url(scalar_to_bytes(dealing.proof_c)),
        "s": b64url(scalar_to_bytes(dealing.proof_s)),
        "subshares": {str(i): sealed for i, sealed in dealing.subshares.items()},
    }
    if dealing.signature is not None:
        body["signature"] = b64url(dealing.signature)
    return body


def _start(client, caller, **overrides):
    caller.be(ORG_ADMIN, MANAGE)
    body = {
        "k": 2,
        "custodians": ["emil", "dora", "bernd"],
        "dealers": [1, 4],
        "holders_ceremony_id": FIRST_ID,
        **overrides,
    }
    return client.post(f"{BASE}/resharing", json=body)


async def _snapshot(world: World):
    return (await world.ceremonies.state(TENANT)).ceremony


async def test_a_whole_resharing_over_http(http):
    client, caller, world = http
    started = _start(client, caller)
    assert started.status_code == 201
    body = started.json()
    assert (body["kind"], body["recovery_key_id"]) == (
        "resharing",
        world.repository.recovery_key.key_id,
    )
    assert [(d["dealer_index"], d["kind"]) for d in body["dealers"]] == [
        (1, "custodian"),
        (4, "paper"),
    ]
    admin_view = client.get(BASE).json()
    assert [g["ceremony_id"] for g in admin_view["chain"]] == [world.repository.recovery_key.key_id]
    assert {h["holder_ref"]: h["state"] for h in admin_view["holders"]}["paper-1"] == "paper"

    snapshot = await _snapshot(world)
    caller.be("anna", CUSTODIAN)
    assert client.get(BASE).json()["holders"] == []
    dealt = client.post(
        f"{BASE}/{RESHARING_ID}/dealings",
        json=_dealing_body(reshare_dealing(snapshot, 1, world.shares[1], [61], ANNA)),
    )
    assert dealt.json() == {"status": "dealing"}
    # The device has no fresh login: a redirect would wipe the typed sheet.
    caller.be(ORG_ADMIN, MANAGE, fresh=False)
    sheet = reshare_dealing(snapshot, 4, world.shares[4], [71], None)
    paper = client.post(
        f"{BASE}/{RESHARING_ID}/paper-dealings", json={"dealer_index": 4, **_dealing_body(sheet)}
    )
    assert (paper.status_code, paper.json()) == (201, {"status": "confirming"})

    snapshot = await _snapshot(world)
    key_id = world.repository.recovery_key.key_id
    status = None
    for participant in snapshot.custodians:
        holder = HOLDERS[participant.holder_ref]
        index = participant.holder_index
        caller.be(holder.sub, CUSTODIAN)
        received = client.get(f"{BASE}/{RESHARING_ID}/subshares").json()["subshares"][str(index)]
        share = holder.share(snapshot, index, {int(d): t for d, t in received.items()})
        signature, sealed = holder.confirmation(
            snapshot, index, share, snapshot.ceremony.transcript_hash, key_id
        )
        c, s = share_proof(snapshot, index, share)
        status = client.post(
            f"{BASE}/{RESHARING_ID}/confirmations",
            json={
                "transcript_signature": b64url(signature),
                "encrypted_share": sealed,
                "share_proof_c": b64url(scalar_to_bytes(c)),
                "share_proof_s": b64url(scalar_to_bytes(s)),
            },
        ).json()["status"]
    assert status == "active"
    caller.be(ORG_ADMIN, MANAGE)
    after = client.get(BASE).json()
    assert after["recovery_key"]["holders_ceremony_id"] == RESHARING_ID
    # The chain is served while a resharing runs; afterwards only the old sheets matter.
    assert after["chain"] == []
    assert after["previous_had_paper"] is True


def test_starting_needs_a_fresh_login(http):
    client, caller, _ = http
    caller.be(ORG_ADMIN, MANAGE, fresh=False)
    response = client.post(
        f"{BASE}/resharing",
        json={
            "k": 2,
            "custodians": ["bernd", "dora", "emil"],
            "dealers": [1, 4],
            "holders_ceremony_id": FIRST_ID,
        },
    )
    assert (response.status_code, _code(response)) == (403, "STEP_UP_REQUIRED")


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"dealers": [1]}, 422, "INVALID_DEALERS"),
        ({"custodians": ["dora", "emil", "zoe"]}, 422, "NOT_A_CUSTODIAN"),
        ({"paper_device_pub": "A" * 87}, 422, "INVALID_CEREMONY"),
    ],
)
def test_a_refused_start_answers_its_code(http, overrides, status, code):
    client, caller, _ = http
    response = _start(client, caller, **overrides)
    assert (response.status_code, _code(response)) == (status, code)


def test_a_dealer_gets_its_share_and_key_and_nobody_else_does(http):
    client, caller, world = http
    _start(client, caller)
    caller.be("anna", CUSTODIAN)
    body = client.get(f"{BASE}/{RESHARING_ID}/dealer").json()
    assert (body["dealer_index"], body["key"]["key_version"], body["key"]["blob"]) == (
        1,
        1,
        '{"blob": 1}',
    )
    assert len(body["key"]["fingerprint_display"].split()) == 10
    caller.be("dora", CUSTODIAN)
    refused = client.get(f"{BASE}/{RESHARING_ID}/dealer")
    assert (refused.status_code, _code(refused)) == (403, "NOT_A_PARTICIPANT")


def test_an_unreadable_dealer_key_is_a_server_error(http):
    client, caller, world = http
    world.repository.keys["anna"] = replace(world.repository.keys["anna"], encrypted_private=b"x")
    _start(client, caller)
    caller.be("anna", CUSTODIAN)
    response = client.get(f"{BASE}/{RESHARING_ID}/dealer")
    assert (response.status_code, _code(response)) == (500, "KEY_UNREADABLE")


async def test_a_confirmation_without_its_share_proof_is_refused(http):
    client, caller, world = http
    _start(client, caller)
    snapshot = await _snapshot(world)
    caller.be("anna", CUSTODIAN)
    client.post(
        f"{BASE}/{RESHARING_ID}/dealings",
        json=_dealing_body(reshare_dealing(snapshot, 1, world.shares[1], [61], ANNA)),
    )
    caller.be(ORG_ADMIN, MANAGE)
    sheet = reshare_dealing(snapshot, 4, world.shares[4], [71], None)
    client.post(
        f"{BASE}/{RESHARING_ID}/paper-dealings", json={"dealer_index": 4, **_dealing_body(sheet)}
    )
    caller.be("bernd", CUSTODIAN)
    response = client.post(
        f"{BASE}/{RESHARING_ID}/confirmations",
        json={"transcript_signature": b64url(bytes(64)), "encrypted_share": "{}"},
    )
    assert response.status_code == 422


def test_an_abort_reason_from_the_gateway_is_not_a_browsers_to_give(http):
    client, caller, _ = http
    _start(client, caller)
    caller.be("anna", CUSTODIAN)
    response = client.post(f"{BASE}/{RESHARING_ID}/abort", json={"reason": "canary_failed"})
    assert (response.status_code, _code(response)) == (422, "INVALID_REASON")
    assert (
        client.post(f"{BASE}/{RESHARING_ID}/abort", json={"reason": "chain_invalid"}).status_code
        == 204
    )


def test_a_point_that_is_not_base64url_is_refused(http):
    client, caller, _ = http
    response = _start(client, caller, paper_device_pub="!" * 87)
    assert (response.status_code, _code(response)) == (422, "INVALID_CEREMONY")


def test_a_recording_user_who_deals_nothing_sees_no_ceremony(http):
    client, caller, _ = http
    _start(client, caller)
    caller.be("someone", "ssf.recording.request")
    response = client.get(BASE)
    assert (response.status_code, _code(response)) == (403, "PERMISSION_REQUIRED")


def test_a_dealer_without_the_custodian_permission_sees_only_its_resharing(http):
    client, caller, _ = http
    _start(client, caller)
    caller.be("anna", "ssf.recording.request")
    body = client.get(BASE).json()
    assert body["ceremony"]["ceremony_id"] == RESHARING_ID
    assert (body["usable_shares"], body["holders"], body["previous_had_paper"]) == (None, [], False)
    assert client.get(f"{BASE}/{RESHARING_ID}/dealer").status_code == 200
    refused = client.get(f"{BASE}/{RESHARING_ID}/subshares")
    assert (refused.status_code, _code(refused)) == (403, "PERMISSION_REQUIRED")


def test_a_custodian_sees_no_holder_list(http):
    client, caller, _ = http
    caller.be("bernd", CUSTODIAN)
    body = client.get(BASE).json()
    assert body["holders"] == []
    assert body["usable_shares"] is not None
