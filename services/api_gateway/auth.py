"""Keycloak bearer-token validation for administrative API routes."""

import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import jwt
import requests
from fastapi import HTTPException, Request, status
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import InvalidTokenError


@dataclass(frozen=True)
class KeycloakSettings:
    issuer: str
    audience: str
    required_role: str

    @classmethod
    def from_environment(cls) -> "KeycloakSettings":
        return cls(
            issuer=os.environ.get(
                "KEYCLOAK_ISSUER", "https://auth.kassel.smartspeechflow.de/realms/ssf"
            ).rstrip("/"),
            audience=os.environ.get("KEYCLOAK_AUDIENCE", "ssf-frontend"),
            required_role=os.environ.get("KEYCLOAK_REQUIRED_ROLE", "ssf-user"),
        )


class OidcKeyCache:
    def __init__(self) -> None:
        self.entries: dict[str, tuple[float, dict[str, Any]]] = {}

    def keys_for(self, issuer: str) -> dict[str, Any]:
        cached = self.entries.get(issuer)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        metadata = requests.get(f"{issuer}/.well-known/openid-configuration", timeout=5)
        metadata.raise_for_status()
        key_response = requests.get(metadata.json()["jwks_uri"], timeout=5)
        key_response.raise_for_status()
        keys = {key["kid"]: key for key in key_response.json()["keys"]}
        self.entries[issuer] = (time.monotonic() + 300, keys)
        return keys


_key_cache = OidcKeyCache()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid bearer token is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_ssf_user(request: Request) -> dict[str, Any]:
    """Validate an administrative bearer token and return its claims."""
    legacy_enabled = os.environ.get("SSF_ENABLE_LEGACY_ADMIN_ACCESS", "false") == "true"
    legacy_code = os.environ.get("SSF_LEGACY_ADMIN_ACCESS_CODE", "")
    legacy_header = request.headers.get("X-SSF-Legacy-Access", "")
    if (
        legacy_enabled
        and legacy_code
        and hmac.compare_digest(legacy_header, legacy_code)
    ):
        return {"sub": "legacy-admin", "auth_method": "legacy-transition"}

    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized()

    settings = KeycloakSettings.from_environment()
    try:
        header = jwt.get_unverified_header(token)
        signing_key = _key_cache.keys_for(settings.issuer)[header["kid"]]
        claims = jwt.decode(
            token,
            RSAAlgorithm.from_jwk(json.dumps(signing_key)),
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=settings.issuer,
        )
    except (InvalidTokenError, KeyError, requests.RequestException, ValueError):
        raise _unauthorized() from None

    roles = claims.get("realm_access", {}).get("roles", [])
    if settings.required_role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The bearer token lacks the required role",
        )
    return claims
