"""Keycloak bearer-token validation for administrative API routes."""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import uuid4

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, HTTPException, status
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import InvalidKeyError, InvalidTokenError
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

from .dependencies import get_login_directory, get_oidc_key_cache
from .origin import parse_origin
from .studio_login_directory import (
    StudioLoginDirectoryConfigurationError,
    StudioLoginDirectoryService,
)
from .studio_login_directory_client import StudioLoginDirectoryClientError
from .studio_runtime_token import StudioTokenError

VERIFIED_TENANT_ID_CLAIM = "_ssf_verified_tenant_id"


@dataclass(frozen=True)
class KeycloakSettings:
    base_url: str
    audience: str
    required_role: str

    def issuer_for(self, realm: str) -> str:
        return f"{self.base_url}/realms/{realm}"

    @classmethod
    def from_environment(cls) -> "KeycloakSettings":
        base_url = parse_origin(
            os.environ.get("KEYCLOAK_BASE_URL", "https://auth.kassel.smartspeechflow.de").strip(),
            keep_default_port=True,
        )
        if base_url is None:
            raise ValueError("KEYCLOAK_BASE_URL must be an origin-only URL")
        return cls(
            base_url=base_url,
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


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid bearer token is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_auth_login_directory_provider(
    directory: Annotated[StudioLoginDirectoryService | None, Depends(get_login_directory)],
) -> Callable[[], StudioLoginDirectoryService]:
    """Defer directory configuration so a request without a bearer token stays a 401."""

    def provide() -> StudioLoginDirectoryService:
        if directory is None:
            raise StudioLoginDirectoryConfigurationError(
                "studio_login_directory_configuration_invalid"
            )
        return directory

    return provide


async def require_ssf_user(
    request: HTTPConnection,
    directory_provider: Annotated[
        Callable[[], StudioLoginDirectoryService],
        Depends(get_auth_login_directory_provider),
    ],
    key_cache: Annotated[OidcKeyCache, Depends(get_oidc_key_cache)],
) -> dict[str, Any]:
    """Validate a tenant user's bearer token and attach the issuer-derived tenant."""
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

    matched_tenants = [
        tenant for tenant in directory.tenants if settings.issuer_for(tenant.realm) == issuer
    ]
    if len(matched_tenants) != 1:
        raise _unauthorized()

    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise _unauthorized()
        keys = await run_in_threadpool(key_cache.keys_for, issuer)
        signing_key = keys[header["kid"]]
        public_key = RSAAlgorithm.from_jwk(json.dumps(signing_key))
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise InvalidKeyError("OIDC signing key must be an RSA public key")
        claims = jwt.decode(
            token,
            public_key,
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

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise _unauthorized()
    # Always overwrite a same-named JWT claim; only the verified issuer and
    # admitted login directory may establish tenant identity.
    claims[VERIFIED_TENANT_ID_CLAIM] = matched_tenants[0].id
    return claims


async def require_ssf_privileged_user(
    claims: Annotated[dict[str, Any], Depends(require_ssf_user)],
) -> dict[str, Any]:
    """Keep operational and feedback-read privileges separate from conversation access."""
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
    if (
        not isinstance(roles, list)
        or KeycloakSettings.from_environment().required_role not in roles
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The bearer token lacks the required role",
        )
    return claims


async def optional_ssf_user(
    request: HTTPConnection,
    directory_provider: Annotated[
        Callable[[], StudioLoginDirectoryService],
        Depends(get_auth_login_directory_provider),
    ],
    key_cache: Annotated[OidcKeyCache, Depends(get_oidc_key_cache)],
) -> dict[str, Any] | None:
    """Authenticate a supplied bearer token while allowing no token at all."""
    if "Authorization" not in request.headers:
        return None
    return await require_ssf_user(request, directory_provider, key_cache)
