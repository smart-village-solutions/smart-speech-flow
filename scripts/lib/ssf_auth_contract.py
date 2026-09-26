"""What the SSF gateway needs from a tenant realm and from its tokens.

Shared by the realm-artifact guard test, the tenant-isolation smoke test and
the read-only tenant audit, so they can never disagree about the contract. It
is standard library only: the scripts run on hosts without the gateway's
dependencies. Production realms are provisioned by Studio; this states the SSF
side of that contract, not how Studio meets it (#363).

The token rules mirror `services/api_gateway/auth.py`; `tests/test_auth.py`
proves the two agree.
"""

import base64
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlsplit

REQUIRED_ELEMENTS = (
    "public-pkce-client",
    "login-redirects",
    "audience-mapper",
    "revision-mapper",
    "ssf-user-role",
    "no-tenant-id-mapper",
    "revision-attribute-admin-only",
)
REVISION_CLAIM = "ssf_authorization_revision"
TENANT_CLAIM = "studio_tenant_id"
REVISION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_USER_PROFILE_PROVIDER = "org.keycloak.userprofile.UserProfileProvider"


def unverified_claims(token: str) -> dict[str, Any] | None:
    """Decode a JWT payload without verifying it, or None if it is not one."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        # binascii.Error and json.JSONDecodeError are both ValueErrors.
        return None
    return claims if isinstance(claims, dict) else None


def revision_state(claims: Mapping[str, Any]) -> str:
    """Return "ok", "missing" (absent or null) or "malformed"."""
    revision = claims.get(REVISION_CLAIM)
    if revision is None:
        return "missing"
    if isinstance(revision, str) and REVISION_PATTERN.fullmatch(revision):
        return "ok"
    return "malformed"


def has_audience(claims: Mapping[str, Any], audience: str) -> bool:
    aud = claims.get("aud")
    return aud == audience or (isinstance(aud, list) and audience in aud)


def has_realm_role(claims: Mapping[str, Any], role: str) -> bool:
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
    return isinstance(roles, list) and role in roles


def tenant_claim_agrees(claims: Mapping[str, Any], tenant_id: str) -> bool:
    """The issuer identifies the tenant; a tenant claim may only agree with it."""
    return TENANT_CLAIM not in claims or claims[TENANT_CLAIM] == tenant_id


def token_flags(
    claims: Mapping[str, Any], *, tenant_id: str, audience: str, role: str
) -> dict[str, bool]:
    """The gateway's acceptance rules for an already verified token, as yes/no."""
    state = revision_state(claims)
    flags = {
        "audience": has_audience(claims, audience),
        "revision_present": state != "missing",
        "revision_well_formed": state == "ok",
        "ssf_user_role": has_realm_role(claims, role),
        "tenant_claim_ok": tenant_claim_agrees(claims, tenant_id),
    }
    flags["would_pass"] = all(flags.values())
    return flags


def is_secure_url(url: str) -> bool:
    """https anywhere; plain http only to this machine, which the local stack uses."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and (host in _LOOPBACK_HOSTS or host.endswith(".localhost"))


def admits_login_callback(uri: str, tenant_id: str) -> bool:
    """Whether a redirect URI admits the frontend's `<origin>/login/<tenant>` callback.

    Keycloak treats a trailing `*` as a prefix wildcard; anything else must
    match exactly.
    """
    if not isinstance(uri, str) or not is_secure_url(uri):
        return False
    path = urlsplit(uri).path
    callback = f"/login/{quote(tenant_id, safe='')}"
    if path.endswith("*"):
        return callback.startswith(path[:-1])
    return path == callback


def login_client_problems(client: Mapping[str, Any] | None, tenant_id: str) -> list[str]:
    """What stops a live `ssf-frontend` client from completing the SPA login.

    Deliberately narrower than `missing_realm_elements`, which states the full
    reviewed contract for the repository artifact: a live realm is judged only
    on what would actually break login for this tenant.
    """
    if not client:
        return ["client-missing"]
    problems = []
    if not (
        client.get("publicClient") is True
        and client.get("standardFlowEnabled") is True
        and client.get("attributes", {}).get("pkce.code.challenge.method") == "S256"
    ):
        problems.append("not-public-pkce")
    if not any(admits_login_callback(uri, tenant_id) for uri in client.get("redirectUris") or []):
        problems.append("no-login-redirect")
    return problems


def _in_access_token(mapper: Mapping[str, Any]) -> bool:
    return str(mapper.get("config", {}).get("access.token.claim", "")).lower() == "true"


def _emits_claim(mappers: list[Mapping[str, Any]], claim: str) -> bool:
    return any(
        mapper.get("config", {}).get("claim.name") == claim and _in_access_token(mapper)
        for mapper in mappers
    )


def _has_audience_mapper(mappers: list[Mapping[str, Any]], audience: str) -> bool:
    return any(
        mapper.get("protocolMapper") == "oidc-audience-mapper"
        and mapper.get("config", {}).get("included.client.audience") == audience
        and _in_access_token(mapper)
        for mapper in mappers
    )


def _is_public_pkce(client: Mapping[str, Any]) -> bool:
    return (
        client.get("publicClient") is True
        and "secret" not in client
        and client.get("standardFlowEnabled") is True
        and client.get("implicitFlowEnabled") is False
        and client.get("directAccessGrantsEnabled") is False
        and client.get("attributes", {}).get("pkce.code.challenge.method") == "S256"
    )


def _has_login_redirects(client: Mapping[str, Any]) -> bool:
    redirects = client.get("redirectUris") or []
    return bool(redirects) and all(
        isinstance(uri, str) and uri.startswith("https://") and uri.endswith("/login/*")
        for uri in redirects
    )


def _revision_attribute_admin_only(realm: Mapping[str, Any]) -> bool:
    """Keycloak 26 silently drops an attribute its user profile does not declare,
    and a user-editable revision would let users authorize themselves."""
    try:
        component = realm["components"][_USER_PROFILE_PROVIDER][0]
        profile = json.loads(component["config"]["kc.user.profile.config"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    attribute = next(
        (entry for entry in profile.get("attributes", []) if entry.get("name") == REVISION_CLAIM),
        None,
    )
    permissions = (attribute or {}).get("permissions") or {}
    return set(permissions.get("edit") or []) == {"admin"} and set(
        permissions.get("view") or []
    ) <= {"admin"}


def missing_realm_elements(
    realm: Mapping[str, Any],
    *,
    client_id: str = "ssf-frontend",
    audience: str = "ssf-frontend",
    role: str = "ssf-user",
) -> list[str]:
    """Return the REQUIRED_ELEMENTS the realm does not satisfy, in order.

    This is the full reviewed contract for the repository's realm artifact. A
    live realm is judged by `login_client_problems` and by its tokens instead,
    because Studio may meet the contract differently (client scopes, extra
    redirect URIs) without breaking anything the gateway needs.
    """
    client = next(
        (client for client in realm.get("clients", []) if client.get("clientId") == client_id),
        {},
    )
    mappers = list(client.get("protocolMappers") or [])
    roles = {entry.get("name") for entry in realm.get("roles", {}).get("realm", [])}
    satisfied = {
        "public-pkce-client": _is_public_pkce(client),
        "login-redirects": _has_login_redirects(client),
        "audience-mapper": _has_audience_mapper(mappers, audience),
        "revision-mapper": _emits_claim(mappers, REVISION_CLAIM),
        "ssf-user-role": role in roles,
        "no-tenant-id-mapper": not _emits_claim(mappers, TENANT_CLAIM),
        "revision-attribute-admin-only": _revision_attribute_admin_only(realm),
    }
    return [element for element in REQUIRED_ELEMENTS if not satisfied[element]]
