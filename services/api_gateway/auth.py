"""Keycloak bearer-token validation for administrative API routes."""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlsplit

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidKeyError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
)
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

from .auth_rejections import (
    AuthRejectionReason,
    auth_correlation_id,
    record_auth_rejection,
    rejection_response,
)
from .studio_login_directory import (
    StudioLoginDirectoryConfigurationError,
    StudioLoginDirectoryService,
    get_studio_login_directory_service,
)
from .studio_login_directory_client import StudioLoginDirectoryClientError, StudioLoginTenant
from .studio_runtime_client import REVISION_PATTERN
from .studio_runtime_token import StudioTokenError

_LEGACY_TENANT_CLAIMS = frozenset({"tenant_id", "studio_instance_id"})

# First match wins, so a subclass must precede its base.
_DECODE_REASONS = (
    (ExpiredSignatureError, AuthRejectionReason.TOKEN_EXPIRED),
    (InvalidAudienceError, AuthRejectionReason.INVALID_AUDIENCE),
    (InvalidIssuerError, AuthRejectionReason.INVALID_ISSUER),
    (InvalidSignatureError, AuthRejectionReason.INVALID_SIGNATURE),
    (MissingRequiredClaimError, AuthRejectionReason.MISSING_REQUIRED_CLAIM),
)


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


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """A validated administrative identity.

    The tenant is the directory entry whose realm issued the token, never a
    value the token asserts, and no raw claims travel further than this module.
    """

    tenant_id: str
    realm: str
    authorization_revision: str
    subject: str | None
    carries_legacy_tenant_claim: bool


class _Rejected(Exception):
    """One classified rejection, raised inside authentication and caught once."""

    def __init__(self, reason: AuthRejectionReason) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.tenant_id: str | None = None


def get_auth_login_directory_provider() -> Callable[[], StudioLoginDirectoryService]:
    """Defer directory configuration so a request without a bearer token stays a 401."""
    return get_studio_login_directory_service


def _bearer_token(request: HTTPConnection) -> str:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _Rejected(AuthRejectionReason.MISSING_BEARER)
    return token


def _settings() -> KeycloakSettings:
    try:
        return KeycloakSettings.from_environment()
    except ValueError:
        raise _Rejected(AuthRejectionReason.GATEWAY_AUTH_MISCONFIGURED) from None


def _unverified_issuer(token: str) -> str:
    try:
        issuer = jwt.decode(token, options={"verify_signature": False}).get("iss")
    except (InvalidTokenError, ValueError):
        raise _Rejected(AuthRejectionReason.MALFORMED_TOKEN) from None
    if not isinstance(issuer, str):
        raise _Rejected(AuthRejectionReason.MALFORMED_TOKEN)
    return issuer


async def _directory_tenant(
    directory_provider: Callable[[], StudioLoginDirectoryService],
    settings: KeycloakSettings,
    issuer: str,
    correlation_id: str,
) -> StudioLoginTenant:
    try:
        directory = await directory_provider().get(correlation_id)
    except (
        StudioLoginDirectoryClientError,
        StudioLoginDirectoryConfigurationError,
        StudioTokenError,
    ):
        raise _Rejected(AuthRejectionReason.DIRECTORY_UNAVAILABLE) from None
    tenant = next(
        (tenant for tenant in directory.tenants if settings.issuer_for(tenant.realm) == issuer),
        None,
    )
    if tenant is None:
        raise _Rejected(AuthRejectionReason.UNKNOWN_ISSUER)
    return tenant


async def _public_key(token: str, issuer: str) -> rsa.RSAPublicKey:
    try:
        header = jwt.get_unverified_header(token)
    except InvalidTokenError:
        raise _Rejected(AuthRejectionReason.MALFORMED_TOKEN) from None
    if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise _Rejected(AuthRejectionReason.UNSUPPORTED_TOKEN_HEADER)
    try:
        keys = await run_in_threadpool(_key_cache.keys_for, issuer)
    except (requests.RequestException, KeyError, TypeError, ValueError):
        raise _Rejected(AuthRejectionReason.SIGNING_KEYS_UNAVAILABLE) from None
    signing_key = keys.get(header["kid"])
    if signing_key is None:
        raise _Rejected(AuthRejectionReason.UNKNOWN_SIGNING_KEY)
    try:
        public_key = RSAAlgorithm.from_jwk(json.dumps(signing_key))
    except (InvalidKeyError, KeyError, TypeError, ValueError):
        raise _Rejected(AuthRejectionReason.INVALID_SIGNING_KEY) from None
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise _Rejected(AuthRejectionReason.INVALID_SIGNING_KEY)
    return public_key


def _verified_claims(
    token: str, public_key: rsa.RSAPublicKey, issuer: str, settings: KeycloakSettings
) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "aud"]},
        )
    except InvalidTokenError as error:
        reason = next(
            (reason for kind, reason in _DECODE_REASONS if isinstance(error, kind)),
            AuthRejectionReason.INVALID_TOKEN,
        )
        raise _Rejected(reason) from None
    except (TypeError, ValueError):
        raise _Rejected(AuthRejectionReason.INVALID_TOKEN) from None


def _principal(
    claims: dict[str, Any], tenant: StudioLoginTenant, settings: KeycloakSettings
) -> AuthenticatedPrincipal:
    # The issuer already identifies the tenant (#363); a claim may only agree.
    if "studio_tenant_id" in claims and claims["studio_tenant_id"] != tenant.id:
        raise _Rejected(AuthRejectionReason.TENANT_CLAIM_MISMATCH)
    revision = claims.get("ssf_authorization_revision")
    if revision is None:
        raise _Rejected(AuthRejectionReason.REVISION_MISSING)
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise _Rejected(AuthRejectionReason.REVISION_MALFORMED)
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
    if not isinstance(roles, list) or settings.required_role not in roles:
        raise _Rejected(AuthRejectionReason.ROLE_MISSING)
    subject = claims.get("sub")
    return AuthenticatedPrincipal(
        tenant_id=tenant.id,
        realm=tenant.realm,
        authorization_revision=revision,
        subject=subject if isinstance(subject, str) and subject else None,
        carries_legacy_tenant_claim=not _LEGACY_TENANT_CLAIMS.isdisjoint(claims),
    )


async def _authenticate(
    request: HTTPConnection,
    directory_provider: Callable[[], StudioLoginDirectoryService],
    correlation_id: str,
) -> AuthenticatedPrincipal:
    token = _bearer_token(request)
    settings = _settings()
    issuer = _unverified_issuer(token)
    tenant = await _directory_tenant(directory_provider, settings, issuer, correlation_id)
    try:
        public_key = await _public_key(token, issuer)
        claims = _verified_claims(token, public_key, issuer, settings)
        return _principal(claims, tenant, settings)
    except _Rejected as rejection:
        rejection.tenant_id = tenant.id
        raise


async def require_ssf_user(
    request: HTTPConnection,
    directory_provider: Annotated[
        Callable[[], StudioLoginDirectoryService],
        Depends(get_auth_login_directory_provider),
    ],
) -> AuthenticatedPrincipal:
    """Validate an administrative bearer token and return its principal."""
    correlation_id = auth_correlation_id(request)
    try:
        return await _authenticate(request, directory_provider, correlation_id)
    except _Rejected as rejection:
        record_auth_rejection(
            request,
            rejection.reason,
            correlation_id=correlation_id,
            tenant_id=rejection.tenant_id,
        )
        raise rejection_response(rejection.reason) from None


async def optional_ssf_user(
    request: HTTPConnection,
    directory_provider: Annotated[
        Callable[[], StudioLoginDirectoryService],
        Depends(get_auth_login_directory_provider),
    ],
) -> AuthenticatedPrincipal | None:
    """Authenticate a supplied bearer token while allowing no token at all."""
    if "Authorization" not in request.headers:
        return None
    return await require_ssf_user(request, directory_provider)
