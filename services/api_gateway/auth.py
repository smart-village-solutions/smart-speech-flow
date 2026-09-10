"""Keycloak bearer-token validation for administrative API routes."""

import hmac
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import uuid4

import jwt
import requests
from fastapi import Depends, HTTPException, Request, status
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import InvalidKeyError, InvalidTokenError
from starlette.concurrency import run_in_threadpool

from .studio_login_directory import (
    StudioLoginDirectoryConfigurationError,
    StudioLoginDirectoryService,
    get_studio_login_directory_service,
)
from .studio_login_directory_client import StudioLoginDirectoryClientError
from .studio_runtime_token import StudioTokenError

_AUTHORIZATION_REVISION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class KeycloakSettings:
    base_url: str
    audience: str
    required_role: str

    def issuer_for(self, realm: str) -> str:
        return f"{self.base_url}/realms/{realm}"

    @classmethod
    def from_environment(cls) -> "KeycloakSettings":
        base_url = os.environ.get(
            "KEYCLOAK_BASE_URL", "https://auth.kassel.smartspeechflow.de"
        ).strip()
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in base_url)
        ):
            raise ValueError("KEYCLOAK_BASE_URL must be an origin-only URL")
        # Accessing port also rejects malformed or out-of-range port numbers.
        _ = parsed.port
        return cls(
            base_url=f"{parsed.scheme}://{parsed.netloc.lower()}",
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
        metadata = requests.get(
            f"{issuer}/.well-known/openid-configuration",
            timeout=5,
            allow_redirects=False,
        )
        metadata.raise_for_status()
        if metadata.is_redirect:
            raise ValueError("OIDC discovery redirects are not accepted")
        expected_jwks_uri = f"{issuer}/protocol/openid-connect/certs"
        document = metadata.json()
        if (
            not isinstance(document, dict)
            or document.get("issuer") != issuer
            or document.get("jwks_uri") != expected_jwks_uri
        ):
            raise ValueError("OIDC metadata does not match the admitted issuer")
        key_response = requests.get(expected_jwks_uri, timeout=5, allow_redirects=False)
        key_response.raise_for_status()
        if key_response.is_redirect:
            raise ValueError("OIDC key redirects are not accepted")
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


def get_auth_login_directory_provider() -> Callable[[], StudioLoginDirectoryService]:
    """Defer directory configuration until after the legacy authentication branch."""
    return get_studio_login_directory_service


async def require_ssf_user(
    request: Request,
    directory_provider: Annotated[
        Callable[[], StudioLoginDirectoryService],
        Depends(get_auth_login_directory_provider),
    ],
) -> dict[str, Any]:
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

    try:
        settings = KeycloakSettings.from_environment()
        unverified_claims = jwt.decode(token, options={"verify_signature": False})
        issuer = unverified_claims.get("iss")
        if not isinstance(issuer, str):
            raise _unauthorized()
    except (InvalidTokenError, ValueError):
        raise _unauthorized() from None

    try:
        directory = await directory_provider().get(str(uuid4()))
    except (
        StudioLoginDirectoryClientError,
        StudioLoginDirectoryConfigurationError,
        StudioTokenError,
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The login directory is temporarily unavailable",
        ) from None

    matched_tenant = next(
        (
            tenant
            for tenant in directory.tenants
            if settings.issuer_for(tenant.realm) == issuer
        ),
        None,
    )
    if matched_tenant is None:
        raise _unauthorized()

    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise _unauthorized()
        keys = await run_in_threadpool(_key_cache.keys_for, issuer)
        signing_key = keys[header["kid"]]
        claims = jwt.decode(
            token,
            RSAAlgorithm.from_jwk(json.dumps(signing_key)),
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "aud"]},
        )
    except (
        InvalidKeyError,
        InvalidTokenError,
        KeyError,
        requests.RequestException,
        TypeError,
        ValueError,
    ):
        raise _unauthorized() from None

    revision = claims.get("ssf_authorization_revision")
    if (
        claims.get("studio_tenant_id") != matched_tenant.id
        or not isinstance(revision, str)
        or not _AUTHORIZATION_REVISION_PATTERN.fullmatch(revision)
    ):
        raise _unauthorized()

    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
    if not isinstance(roles, list) or settings.required_role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The bearer token lacks the required role",
        )
    return claims
