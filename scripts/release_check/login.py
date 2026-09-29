"""Log an operator in the way the browser does: authorization code with PKCE.

It posts to Keycloak's own login form over plain HTTP. That proves the real
login path without a browser and without enabling the password grant, which
would weaken production login. The form is found by its action path, not by
theme markup, because the production realms use different themes.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from .config import Operator, Settings, Tenant

AUTHENTICATE_ACTION = "/login-actions/authenticate"
REQUIRED_ACTION = "/login-actions/required-action"
LOOPBACK_HOSTS = ("localhost", "127.0.0.1")


class LoginError(RuntimeError):
    """The login failed. The message never carries a credential."""


class _FormActions(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.actions: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "form":
            action = dict(attrs).get("action")
            if action:
                self.actions.append(action)


def _form_action(html: str, page_url: str, kind: str) -> str | None:
    parser = _FormActions()
    parser.feed(html)
    for action in parser.actions:
        if kind in action:
            return urljoin(page_url, action)
    return None


def _loopback_cookies(client: httpx.AsyncClient, url: str) -> dict[str, str]:
    """Send Keycloak's Secure cookies to a loopback host over http, as browsers do.

    Keycloak marks its login cookies Secure even on http, and httpx rightly keeps
    them off plain http. Browsers treat localhost as a secure context and send
    them, which the local Keycloak relies on. Production is https and unaffected.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "http" or not (host in LOOPBACK_HOSTS or host.endswith(".localhost")):
        return {}
    pairs = [
        f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar if cookie.domain == host
    ]
    return {"Cookie": "; ".join(pairs)} if pairs else {}


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _realm_for(client: httpx.AsyncClient, settings: Settings, tenant: Tenant) -> str:
    response = await client.get(f"{settings.api_base}/api/login/tenants")
    if response.status_code != 200:
        raise LoginError(f"login directory answered HTTP {response.status_code}")
    for entry in response.json().get("tenants", []):
        if entry.get("id") == tenant.directory_id:
            return str(entry["realm"])
    raise LoginError(f"tenant {tenant.directory_id} is not in the login directory")


def _code_from(response: httpx.Response, redirect_uri: str, state: str) -> str:
    if response.is_redirect:
        location = response.headers.get("location", "")
        if not location.startswith(redirect_uri):
            raise LoginError("Keycloak redirected somewhere other than the login callback")
        query = parse_qs(urlsplit(location).query)
        if query.get("state") != [state]:
            raise LoginError("Keycloak returned a mismatched state")
        if "code" not in query:
            raise LoginError(f"Keycloak refused the login: {query.get('error', ['unknown'])[0]}")
        return str(query["code"][0])
    if _form_action(response.text, str(response.url), AUTHENTICATE_ACTION):
        raise LoginError("Keycloak rejected the credentials")
    if _form_action(response.text, str(response.url), REQUIRED_ACTION):
        raise LoginError(
            "Keycloak requires an action from this user; "
            "give it a permanent password and no required actions"
        )
    raise LoginError(f"Keycloak answered HTTP {response.status_code} without a login result")


async def access_token(
    settings: Settings,
    tenant: Tenant,
    operator: Operator,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    # A client per login: Keycloak's session cookies must not leak between users.
    async with httpx.AsyncClient(transport=transport, timeout=20, follow_redirects=True) as client:
        realm = await _realm_for(client, settings, tenant)
        endpoint = f"{settings.keycloak_base}/realms/{realm}/protocol/openid-connect"
        redirect_uri = settings.redirect_uri(tenant)
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        page = await client.get(
            f"{endpoint}/auth",
            params={
                "client_id": settings.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        action = (
            _form_action(page.text, str(page.url), AUTHENTICATE_ACTION)
            if page.status_code == 200
            else None
        )
        if action is None:
            raise LoginError(f"Keycloak login page unavailable (HTTP {page.status_code})")
        submitted = await client.post(
            action,
            data={"username": operator.username, "password": operator.password, "credentialId": ""},
            headers=_loopback_cookies(client, action),
            follow_redirects=False,
        )
        code = _code_from(submitted, redirect_uri, state)
        token = await client.post(
            f"{endpoint}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        )
        if token.status_code != 200:
            raise LoginError(f"token exchange answered HTTP {token.status_code}")
        return str(token.json()["access_token"])
