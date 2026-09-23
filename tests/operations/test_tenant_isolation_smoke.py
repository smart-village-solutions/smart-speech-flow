import base64
import json

import httpx
import pytest

from tests.script_helpers import load_script

REVISION = "sha256:" + "a" * 64


def _load_script():
    return load_script("scripts/tenant-isolation-smoke.py", "tenant_isolation_smoke")


def _jwt(**claims) -> str:
    """An unsigned JWT-shaped token; the smoke test never verifies signatures."""

    def segment(value) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    body = {"realm_access": {"roles": ["ssf-user"]}, "ssf_authorization_revision": REVISION}
    body.update(claims)
    body = {key: value for key, value in body.items() if value is not None}
    return f"{segment({'alg': 'RS256', 'kid': 'k'})}.{segment(body)}.signature"


TOKEN_A = _jwt(sub="secret-subject-a")
TOKEN_B = _jwt(sub="secret-subject-b")


def _settings(smoke, token_a=TOKEN_A, token_b=TOKEN_B):
    return smoke.SmokeSettings(
        base_url="https://dialog.example", tenant_a_token=token_a, tenant_b_token=token_b
    )


def _assert_no_secret(text: str) -> None:
    for secret in (TOKEN_A, TOKEN_B, "secret-subject", REVISION):
        assert secret not in text


def test_smoke_proves_both_positive_and_cross_tenant_paths_without_leaking_tokens(capsys):
    smoke = _load_script()
    terminated: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("Authorization")
        if request.method == "POST" and request.url.path == "/api/admin/session/create":
            session_id = "AAAA0001" if authorization == f"Bearer {TOKEN_A}" else "BBBB0001"
            return httpx.Response(201, json={"session_id": session_id})
        if request.method == "GET" and request.url.path.startswith("/api/admin/session/"):
            own = (authorization == f"Bearer {TOKEN_A}" and "AAAA0001" in request.url.path) or (
                authorization == f"Bearer {TOKEN_B}" and "BBBB0001" in request.url.path
            )
            return httpx.Response(
                200 if own else 404,
                json={"status": "pending"} if own else {"detail": "Session not found"},
            )
        if request.method == "GET" and request.url.path.startswith("/api/customer/session/"):
            return httpx.Response(200, json={"status": "pending"})
        if request.method == "DELETE":
            terminated.append(request.url.path)
            return httpx.Response(200, json={"status": "terminated"})
        return httpx.Response(500)

    smoke.run_smoke(_settings(smoke), transport=httpx.MockTransport(handler))

    captured = capsys.readouterr()
    assert captured.out.strip() == "Tenant isolation smoke passed"
    _assert_no_secret(captured.out + captured.err)
    assert terminated == [
        "/api/admin/session/AAAA0001/terminate",
        "/api/admin/session/BBBB0001/terminate",
    ]


def test_smoke_requires_all_credentials_without_echoing_them(monkeypatch, capsys):
    smoke = _load_script()
    monkeypatch.setenv("SSF_TENANT_A_TOKEN", "only-token")
    monkeypatch.delenv("SSF_TENANT_B_TOKEN", raising=False)
    monkeypatch.setenv("SSF_SMOKE_BASE_URL", "https://dialog.example")

    with pytest.raises(ValueError, match="Missing required smoke configuration"):
        smoke.SmokeSettings.from_environment()

    assert "only-token" not in capsys.readouterr().err


def test_smoke_cleans_up_a_partial_run_without_leaking_credentials(capsys):
    smoke = _load_script()
    requests: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("Authorization")
        requests.append((request.method, request.url.path, authorization))
        if request.method == "POST" and authorization == f"Bearer {TOKEN_A}":
            return httpx.Response(201, json={"session_id": "AAAA0001"})
        if request.method == "POST":
            return httpx.Response(503)
        if request.method == "DELETE":
            return httpx.Response(200, json={"status": "terminated"})
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    with pytest.raises(
        smoke.SmokeFailure, match="^Tenant B session creation failed with HTTP 503$"
    ):
        smoke.run_smoke(_settings(smoke), transport=transport)

    assert ("DELETE", "/api/admin/session/AAAA0001/terminate", f"Bearer {TOKEN_A}") in requests
    captured = capsys.readouterr()
    _assert_no_secret(captured.out + captured.err)


@pytest.mark.parametrize(
    ("claims", "message"),
    [
        ({"ssf_authorization_revision": None}, "Tenant A token lacks ssf_authorization_revision"),
        (
            {"ssf_authorization_revision": "sha256:UPPER"},
            "Tenant A token has a malformed ssf_authorization_revision",
        ),
        ({"realm_access": {"roles": []}}, "Tenant A token lacks the ssf-user realm role"),
        ({"realm_access": None}, "Tenant A token lacks the ssf-user realm role"),
    ],
)
def test_token_preconditions_fail_before_any_request(claims, message):
    smoke = _load_script()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    with pytest.raises(smoke.SmokeFailure, match=f"^{message}$"):
        smoke.run_smoke(
            _settings(smoke, token_a=_jwt(**claims)), transport=httpx.MockTransport(handler)
        )
    assert requests == []


def test_tenant_b_is_checked_too():
    smoke = _load_script()
    with pytest.raises(smoke.SmokeFailure, match="^Tenant B token lacks the ssf-user realm role$"):
        smoke.run_smoke(
            _settings(smoke, token_b=_jwt(realm_access={"roles": ["system_admin"]})),
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        )


@pytest.mark.parametrize("token", ["opaque", "a.b", "a.bm90IGpzb24.c"])
def test_a_token_that_is_not_a_jwt_is_named(token):
    smoke = _load_script()
    assert smoke.token_precondition_failure("Tenant B", token) == "Tenant B token is not a JWT"


def test_a_valid_token_has_no_precondition_failure():
    assert _load_script().token_precondition_failure("Tenant A", TOKEN_A) is None


def test_a_stale_revision_is_named():
    smoke = _load_script()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"detail": "studio_runtime_authorization_mismatch"})

    with pytest.raises(
        smoke.SmokeFailure,
        match="^Tenant A token carries a stale ssf_authorization_revision$",
    ):
        smoke.run_smoke(_settings(smoke), transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"detail": "A valid bearer token is required"}),
        httpx.Response(502, text="<html>bad gateway</html>"),
    ],
)
def test_any_other_creation_failure_reports_its_status(response):
    smoke = _load_script()
    with pytest.raises(
        smoke.SmokeFailure,
        match=f"^Tenant A session creation failed with HTTP {response.status_code}$",
    ):
        smoke.run_smoke(_settings(smoke), transport=httpx.MockTransport(lambda request: response))


def test_main_prints_the_specific_failure_without_claim_values(monkeypatch, capsys):
    smoke = _load_script()
    monkeypatch.setenv("SSF_SMOKE_BASE_URL", "https://dialog.example")
    monkeypatch.setenv(
        "SSF_TENANT_A_TOKEN", _jwt(ssf_authorization_revision=None, sub="secret-subject-a")
    )
    monkeypatch.setenv("SSF_TENANT_B_TOKEN", TOKEN_B)

    assert smoke.main() == 1

    captured = capsys.readouterr()
    assert captured.err.strip() == (
        "Tenant isolation smoke failed: Tenant A token lacks ssf_authorization_revision"
    )
    _assert_no_secret(captured.out + captured.err)


def test_main_keeps_configuration_errors_generic(monkeypatch, capsys):
    smoke = _load_script()
    monkeypatch.delenv("SSF_SMOKE_BASE_URL", raising=False)

    assert smoke.main() == 1

    assert capsys.readouterr().err.strip() == "Tenant isolation smoke failed"
