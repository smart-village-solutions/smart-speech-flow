import base64
import hashlib
from urllib.parse import parse_qs

import httpx
import pytest

from scripts.release_check.config import load_settings
from scripts.release_check.login import LoginError, access_token
from tests.operations.release_check.test_release_check_config import _environment

# Host-relative, as the page's own host is what Keycloak posts back to.
AUTHENTICATE = "/realms/realm-a/login-actions/authenticate?session_code=s&amp;execution=e"
REQUIRED_ACTION = "/realms/realm-a/login-actions/required-action?execution=UPDATE_PASSWORD"


def _page(action: str) -> str:
    return (
        f'<html><form id="kc-form-login" class="themed" action="{action}" method="post">'
        "</form></html>"
    )


class FakeKeycloak:
    """Keycloak's login round trip for one user; `outcome` picks how submit answers."""

    def __init__(
        self,
        outcome: str = "code",
        redirect_state: str | None = None,
        require_cookie: bool = False,
    ) -> None:
        self.outcome = outcome
        self.redirect_state = redirect_state
        self.require_cookie = require_cookie
        self.challenge = ""
        self.state = ""
        self.redirect_uri = ""
        self.submitted: dict[str, list[str]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/login/tenants":
            return httpx.Response(200, json={"tenants": [{"id": "tenant-a", "realm": "realm-a"}]})
        if path.endswith("/openid-connect/auth"):
            query = parse_qs(request.url.query.decode())
            assert query["code_challenge_method"] == ["S256"]
            assert query["client_id"] == ["ssf-frontend"]
            self.challenge = query["code_challenge"][0]
            self.state = query["state"][0]
            self.redirect_uri = query["redirect_uri"][0]
            # Keycloak marks its login cookies Secure even when served over http.
            cookie = "KC_RESTART=restart; Path=/realms/realm-a/; Secure; HttpOnly"
            return httpx.Response(200, text=_page(AUTHENTICATE), headers={"set-cookie": cookie})
        if path.endswith("/login-actions/authenticate"):
            if self.require_cookie and "KC_RESTART=restart" not in request.headers.get("cookie", ""):
                return httpx.Response(400, text="<html><p>We are sorry...</p></html>")
            self.submitted = parse_qs(request.content.decode())
            return self._submit()
        if path.endswith("/openid-connect/token"):
            form = parse_qs(request.content.decode())
            digest = hashlib.sha256(form["code_verifier"][0].encode()).digest()
            assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == self.challenge
            assert form["code"] == ["the-code"]
            assert form["redirect_uri"] == [self.redirect_uri]
            return httpx.Response(200, json={"access_token": "the-access-token"})
        return httpx.Response(404)

    def _submit(self) -> httpx.Response:
        if self.outcome == "rejected":
            return httpx.Response(200, text=_page(AUTHENTICATE))
        if self.outcome == "required-action":
            return httpx.Response(200, text=_page(REQUIRED_ACTION))
        state = self.redirect_state or self.state
        location = f"{self.redirect_uri}?state={state}&code=the-code"
        return httpx.Response(302, headers={"location": location})


def _login(fake: FakeKeycloak, **overrides: str):
    settings = load_settings(_environment(**overrides))
    tenant = settings.tenants[0]
    return access_token(settings, tenant, tenant.operators[0], transport=httpx.MockTransport(fake))


async def test_returns_the_token_after_a_pkce_round_trip():
    fake = FakeKeycloak()

    assert await _login(fake) == "the-access-token"
    assert fake.redirect_uri == "https://app.example/login/tenant-a"
    assert fake.submitted["username"] == ["user-A1"]
    assert fake.submitted["password"] == ["secret-A1"]


async def test_rejected_credentials_fail_without_echoing_them():
    with pytest.raises(LoginError, match="rejected the credentials") as raised:
        await _login(FakeKeycloak("rejected"))

    assert "secret-A1" not in str(raised.value)


async def test_a_pending_required_action_fails_clearly():
    with pytest.raises(LoginError, match="requires an action"):
        await _login(FakeKeycloak("required-action"))


async def test_a_mismatched_state_fails():
    with pytest.raises(LoginError, match="mismatched state"):
        await _login(FakeKeycloak(redirect_state="forged"))


async def test_a_tenant_missing_from_the_directory_fails():
    with pytest.raises(LoginError, match="not in the login directory"):
        await _login(FakeKeycloak(), SSF_RC_TENANT_A_ID="tenant-z")


async def test_an_error_page_reports_its_status_not_a_required_action():
    fake = FakeKeycloak(require_cookie=True)

    with pytest.raises(LoginError, match="answered HTTP 400"):
        await _login(fake, SSF_RC_KEYCLOAK_BASE="http://auth.example")


# Browsers treat localhost as a secure context and send Secure cookies there
# over plain http; the local Keycloak depends on that.
async def test_a_loopback_keycloak_over_http_gets_its_secure_cookies():
    fake = FakeKeycloak(require_cookie=True)

    token = await _login(fake, SSF_RC_KEYCLOAK_BASE="http://auth.localhost:8080")

    assert token == "the-access-token"
