"""The read-only tenant authentication audit (#363)."""

import base64
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from services.api_gateway.session_pseudonym import tenant_ref
from tests.script_helpers import load_script

REVISION = "sha256:" + "a" * 64
REALM = json.loads(Path("deploy/production/keycloak/ssf-realm.json").read_text())
REALM_CLIENT = REALM["clients"][0]
DIRECTORY = {"tenants": [{"id": "tenant-kassel", "displayName": "Kassel", "realm": "smartcity"}]}


def _load():
    return load_script("scripts/tenant-auth-audit.py", "tenant_auth_audit")


class _Response:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeKeycloak:
    """Answers the audit's GETs from fixed data and records every request."""

    def __init__(self, tokens, *, client=None, directory=DIRECTORY, page_size=None):
        self.tokens = tokens
        self.client = client if client is not None else {**REALM_CLIENT, "id": "client-uuid"}
        self.directory = directory
        self.page_size = page_size
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request.get_method(), request.full_url))
        url = urllib.parse.urlsplit(request.full_url)
        query = urllib.parse.parse_qs(url.query)
        if url.path.endswith("/api/login/tenants"):
            return _Response(self.directory)
        if url.path.endswith("/clients"):
            return _Response([self.client] if self.client else [])
        if url.path.endswith("/roles"):
            return _Response([{"name": "ssf-user"}, {"name": "default-roles-smartcity"}])
        if url.path.endswith("/users"):
            first, size = int(query["first"][0]), int(query["max"][0])
            size = min(size, self.page_size or size)
            ids = list(self.tokens)[first : first + size]
            return _Response(
                [{"id": user_id, "username": f"{user_id}@example.org"} for user_id in ids]
            )
        if url.path.endswith("/generate-example-access-token"):
            return _Response(self.tokens[query["userId"][0]])
        raise AssertionError(request.full_url)


def _claims(**overrides):
    claims = {
        "aud": ["ssf-frontend", "account"],
        "realm_access": {"roles": ["ssf-user"]},
        "ssf_authorization_revision": REVISION,
    }
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not None}


def _run(tokens, **kwargs):
    audit = _load()
    fake = FakeKeycloak(tokens, **kwargs)
    reports = audit.audit(
        audit.ReadOnlyHttp(fake),
        ssf_base_url="https://ssf.example/",
        keycloak_base_url="https://auth.example/",
        admin_token="admin-secret",
    )
    return audit, fake, reports


def test_the_363_production_shape_is_reported_as_failing():
    audit, _, reports = _run(
        {"u1": _claims(ssf_authorization_revision=None, realm_access={"roles": ["system_admin"]})}
    )
    [tenant] = reports
    assert (tenant.realm, tenant.realm_missing, tenant.error) == ("smartcity", [], None)
    [user] = tenant.users
    assert user.flags == {
        "audience": True,
        "revision_present": False,
        "revision_well_formed": False,
        "ssf_user_role": False,
        "tenant_claim_ok": True,
        "would_pass": False,
    }
    assert audit.exit_code(reports) == 1


def test_a_token_without_a_tenant_claim_passes_after_the_fix():
    audit, _, reports = _run({"u1": _claims()})
    assert reports[0].users[0].flags["would_pass"] is True
    assert audit.exit_code(reports) == 0


def test_a_disagreeing_tenant_claim_fails():
    audit, _, reports = _run({"u1": _claims(studio_tenant_id="tenant-fulda")})
    assert reports[0].users[0].flags["tenant_claim_ok"] is False
    assert audit.exit_code(reports) == 1


def test_one_failing_user_fails_the_tenant():
    audit, _, reports = _run({"u1": _claims(), "u2": _claims(realm_access={"roles": []})})
    assert [user.flags["would_pass"] for user in reports[0].users] == [True, False]
    assert audit.exit_code(reports) == 1


def test_realm_contract_gaps_are_reported():
    client = {
        **REALM_CLIENT,
        "id": "client-uuid",
        "protocolMappers": REALM_CLIENT["protocolMappers"][:1],
    }
    audit, _, reports = _run({"u1": _claims()}, client=client)
    assert reports[0].realm_missing == ["revision-mapper"]
    assert audit.exit_code(reports) == 1


def test_a_realm_without_the_client_is_reported_without_reading_users():
    audit, fake, reports = _run({"u1": _claims()}, client={})
    assert reports[0].realm_missing == ["client"]
    assert not any("/users" in url for _, url in fake.requests)
    assert audit.exit_code(reports) == 1


def test_users_are_read_page_by_page():
    tokens = {f"u{index}": _claims() for index in range(5)}
    _, fake, reports = _run(tokens, page_size=2)
    assert len(reports[0].users) == 5
    firsts = [
        urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["first"][0]
        for _, url in fake.requests
        if urllib.parse.urlsplit(url).path.endswith("/users")
    ]
    assert firsts[:3] == ["0", "2", "4"]


def test_no_published_tenant_is_not_a_pass():
    audit, _, reports = _run({}, directory={"tenants": []})
    assert reports == []
    assert audit.exit_code(reports) == 1


def test_every_request_is_a_get_and_nothing_else_is_possible():
    audit, fake, _ = _run({"u1": _claims()})
    assert {method for method, _ in fake.requests} == {"GET"}
    http = audit.ReadOnlyHttp(fake)
    before = len(fake.requests)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        request = urllib.request.Request("https://auth.example/x", data=b"{}", method=method)
        with pytest.raises(audit.AuditError, match="^refusing non-GET request$"):
            http._open(request)
    assert len(fake.requests) == before


def test_the_admin_token_goes_only_to_keycloak():
    audit = _load()
    seen = []

    def opener(request, timeout):
        seen.append(
            (urllib.parse.urlsplit(request.full_url).netloc, request.get_header("Authorization"))
        )
        return FakeKeycloak({"u1": _claims()})(request, timeout)

    audit.audit(
        audit.ReadOnlyHttp(opener),
        ssf_base_url="https://ssf.example",
        keycloak_base_url="https://auth.example",
        admin_token="admin-secret",
    )
    assert ("ssf.example", None) in seen
    assert {auth for netloc, auth in seen if netloc == "ssf.example"} == {None}
    assert {auth for netloc, auth in seen if netloc == "auth.example"} == {"Bearer admin-secret"}


def test_output_names_no_user_and_no_token_values():
    audit, _, reports = _run({"u1": _claims(sub="subject-secret", email="person@example.org")})
    rendered = audit.render(reports)
    for forbidden in (
        "u1@example.org",
        "person@example.org",
        "subject-secret",
        REVISION,
        "admin-secret",
        "tenant-kassel",
    ):
        assert forbidden not in rendered
    assert hashlib.sha256(b"u1").hexdigest()[:10] in rendered
    assert "realm=smartcity" in rendered
    assert "revision freshness: not checked" in rendered


def test_the_tenant_reference_matches_the_gateway_logs():
    _, _, reports = _run({"u1": _claims()})
    assert reports[0].tenant_ref == tenant_ref("tenant-kassel")


def test_a_jwt_string_example_token_is_decoded_too():
    payload = base64.urlsafe_b64encode(json.dumps(_claims()).encode()).rstrip(b"=").decode()
    _, _, reports = _run({"u1": {"access_token": f"e30.{payload}.sig"}})
    assert reports[0].users[0].flags["would_pass"] is True


def test_a_keycloak_error_is_reported_per_tenant_without_the_url():
    audit = _load()

    def opener(request, timeout):
        if "/admin/" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
        return _Response(DIRECTORY)

    reports = audit.audit(
        audit.ReadOnlyHttp(opener),
        ssf_base_url="https://ssf.example",
        keycloak_base_url="https://auth.example",
        admin_token="admin-secret",
    )
    assert reports[0].error == "GET failed: HTTP 403"
    assert audit.exit_code(reports) == 1


def test_main_requires_its_configuration(monkeypatch, capsys):
    audit = _load()
    for name in ("SSF_AUDIT_BASE_URL", "KEYCLOAK_AUDIT_BASE_URL", "KEYCLOAK_AUDIT_ADMIN_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert audit.main() == 2
    assert "KEYCLOAK_AUDIT_ADMIN_TOKEN" in capsys.readouterr().err
