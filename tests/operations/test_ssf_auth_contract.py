"""The token half of the shared SSF auth contract used by the operator scripts."""

import base64
import json

import pytest

from tests.script_helpers import load_contract

REVISION = "sha256:" + "a" * 64


def _segment(value) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


def test_unverified_claims_decodes_a_jwt_payload_without_padding():
    contract = load_contract()
    claims = {"sub": "x", "n": 1}
    token = f"{_segment({'alg': 'RS256'})}.{_segment(claims)}.signature"
    assert contract.unverified_claims(token) == claims


@pytest.mark.parametrize(
    "token",
    ["", "opaque", "a.b", "a.b.c.d", "a.!!!.c", f"a.{_segment([1, 2])}.c", "a.bm90IGpzb24.c"],
)
def test_unverified_claims_returns_none_for_anything_but_a_jwt_object(token):
    assert load_contract().unverified_claims(token) is None


@pytest.mark.parametrize(
    ("claims", "state"),
    [
        ({"ssf_authorization_revision": REVISION}, "ok"),
        ({}, "missing"),
        ({"ssf_authorization_revision": None}, "missing"),
        ({"ssf_authorization_revision": "sha256:" + "A" * 64}, "malformed"),
        ({"ssf_authorization_revision": REVISION + "\n"}, "malformed"),
        ({"ssf_authorization_revision": [REVISION]}, "malformed"),
    ],
)
def test_revision_state(claims, state):
    assert load_contract().revision_state(claims) == state


@pytest.mark.parametrize(
    ("aud", "expected"),
    [
        ("ssf-frontend", True),
        (["account", "ssf-frontend"], True),
        ("account", False),
        (None, False),
    ],
)
def test_has_audience(aud, expected):
    claims = {} if aud is None else {"aud": aud}
    assert load_contract().has_audience(claims, "ssf-frontend") is expected


@pytest.mark.parametrize(
    ("realm_access", "expected"),
    [
        ({"roles": ["ssf-user"]}, True),
        ({"roles": ["system_admin"]}, False),
        ({"roles": "ssf-user"}, False),
        (["ssf-user"], False),
        (None, False),
    ],
)
def test_has_realm_role(realm_access, expected):
    claims = {} if realm_access is None else {"realm_access": realm_access}
    assert load_contract().has_realm_role(claims, "ssf-user") is expected


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({}, True),
        ({"studio_tenant_id": "tenant-kassel"}, True),
        ({"studio_tenant_id": "tenant-fulda"}, False),
        ({"studio_tenant_id": None}, False),
        ({"studio_tenant_id": ["tenant-kassel"]}, False),
    ],
)
def test_tenant_claim_agrees(claims, expected):
    assert load_contract().tenant_claim_agrees(claims, "tenant-kassel") is expected


def test_token_flags_compose_the_predicates():
    contract = load_contract()
    flags = contract.token_flags(
        {"aud": "ssf-frontend", "realm_access": {"roles": ["system_admin"]}},
        tenant_id="tenant-kassel",
        audience="ssf-frontend",
        role="ssf-user",
    )
    assert flags == {
        "audience": True,
        "revision_present": False,
        "revision_well_formed": False,
        "ssf_user_role": False,
        "tenant_claim_ok": True,
        "would_pass": False,
    }
