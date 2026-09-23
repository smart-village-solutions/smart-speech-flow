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

REQUIRED_ELEMENTS = (
    "public-pkce-client",
    "login-redirects",
    "audience-mapper",
    "revision-mapper",
    "ssf-user-role",
    "no-tenant-id-mapper",
)
REVISION_CLAIM = "ssf_authorization_revision"
TENANT_CLAIM = "studio_tenant_id"
REVISION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def missing_realm_elements(
    realm: Mapping[str, Any],
    *,
    client_id: str = "ssf-frontend",
    audience: str = "ssf-frontend",
    role: str = "ssf-user",
) -> list[str]:
    """Return the REQUIRED_ELEMENTS the realm does not satisfy, in order.

    Accepts a realm export or the audit's `{"clients": [...], "roles":
    {"realm": [...]}}` assembled from the Admin REST API.
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
    }
    return [element for element in REQUIRED_ELEMENTS if not satisfied[element]]
