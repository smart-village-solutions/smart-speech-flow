import asyncio
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from services.api_gateway.app import app
from services.api_gateway.auth import _key_cache, get_auth_login_directory_provider
from services.api_gateway.studio_login_directory import StudioLoginDirectoryService
from services.api_gateway.studio_login_directory_client import (
    StudioLoginDirectory,
    StudioLoginDirectoryClientError,
)
from services.api_gateway.tenant_context import StudioTenantContext, require_studio_tenant_context

client = TestClient(app)
BASE_URL = "https://auth.example.test"
KASSEL_ISSUER = f"{BASE_URL}/realms/kassel-ssf-2025"
FULDA_ISSUER = f"{BASE_URL}/realms/fulda-ssf-2025"
AUDIENCE = "ssf-frontend"
REVISION = f"sha256:{'a' * 64}"
DIRECTORY = StudioLoginDirectory.model_validate(
    {
        "contractVersion": "1.0",
        "directoryRevision": REVISION,
        "tenants": [
            {
                "id": "tenant-kassel",
                "displayName": "Kassel",
                "realm": "kassel-ssf-2025",
            },
            {"id": "tenant-fulda", "displayName": "Fulda", "realm": "fulda-ssf-2025"},
        ],
    }
)


class DirectoryFetcher:
    unavailable = False
    directory = DIRECTORY

    async def fetch(self, correlation_id):
        if self.unavailable:
            raise StudioLoginDirectoryClientError("unavailable", retryable=True)
        return self.directory


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch):
    _key_cache.entries.clear()
    monkeypatch.setenv("KEYCLOAK_BASE_URL", BASE_URL)
    monkeypatch.setenv("KEYCLOAK_ISSUER", KASSEL_ISSUER)
    monkeypatch.setenv("KEYCLOAK_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("KEYCLOAK_REQUIRED_ROLE", "ssf-user")
    monkeypatch.setenv("SSF_ENABLE_LEGACY_ADMIN_ACCESS", "false")
    service = StudioLoginDirectoryService(DirectoryFetcher(), cache_seconds=60)
    app.dependency_overrides[get_auth_login_directory_provider] = lambda: lambda: service
    yield service
    app.dependency_overrides.pop(get_auth_login_directory_provider, None)
    _key_cache.entries.clear()


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def access_token(signing_key, **overrides):
    claims = {
        "sub": "operator-1",
        "iss": KASSEL_ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "realm_access": {"roles": ["ssf-user"]},
        "studio_tenant_id": "tenant-kassel",
        "ssf_authorization_revision": REVISION,
    }
    claims.update(overrides)
    claims = {key: value for key, value in claims.items() if value is not None}
    if isinstance(claims.get("exp"), datetime):
        claims["exp"] = int(claims["exp"].timestamp())
    return jwt.api_jws.encode(
        json.dumps(claims).encode(),
        signing_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def mock_keycloak(
    monkeypatch,
    signing_key,
    *,
    metadata_override=None,
    jwk_override=None,
    redirect_suffix=None,
):
    jwk = json.loads(RSAAlgorithm.to_jwk(signing_key.public_key()))
    jwk["kid"] = "test-key"
    jwk.update(jwk_override or {})
    calls = []

    class Response:
        is_redirect = False

        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    def get(url, timeout, **kwargs):
        assert timeout == 5
        assert kwargs.get("allow_redirects") is False
        calls.append(url)
        if redirect_suffix and url.endswith(redirect_suffix):
            response = Response({})
            response.is_redirect = True
            return response
        if url.endswith("/.well-known/openid-configuration"):
            issuer = url.removesuffix("/.well-known/openid-configuration")
            metadata = {
                "issuer": issuer,
                "jwks_uri": f"{issuer}/protocol/openid-connect/certs",
            }
            metadata.update(metadata_override or {})
            return Response(metadata)
        return Response({"keys": [jwk]})

    monkeypatch.setattr("requests.get", get)
    return calls


def request_with_token(token):
    return client.get("/api/admin/session/history", headers={"Authorization": f"Bearer {token}"})


def test_admin_endpoints_reject_requests_without_a_bearer_token():
    assert client.get("/api/admin/session/history").status_code == 401


@pytest.mark.parametrize(
    "issuer, tenant_id",
    [
        (KASSEL_ISSUER, "tenant-kassel"),
        (FULDA_ISSUER, "tenant-fulda"),
    ],
)
def test_admin_endpoints_accept_each_allowlisted_realm(monkeypatch, signing_key, issuer, tenant_id):
    calls = mock_keycloak(monkeypatch, signing_key)
    response = request_with_token(access_token(signing_key, iss=issuer, studio_tenant_id=tenant_id))
    assert response.status_code == 200
    assert calls == [
        f"{issuer}/.well-known/openid-configuration",
        f"{issuer}/protocol/openid-connect/certs",
    ]


@pytest.mark.parametrize(
    "issuer",
    [
        f"{BASE_URL}/realms/unknown",
        "https://auth.example.test.evil.test/realms/kassel-ssf-2025",
        f"{BASE_URL}/auth/realms/kassel-ssf-2025",
        f"{KASSEL_ISSUER}/",
        f"{KASSEL_ISSUER}?other=realm",
        None,
        [KASSEL_ISSUER],
    ],
)
def test_unadmitted_issuers_are_rejected_without_oidc_network_access(
    monkeypatch, signing_key, issuer
):
    calls = mock_keycloak(monkeypatch, signing_key)
    response = request_with_token(access_token(signing_key, iss=issuer))
    assert response.status_code == 401
    assert calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"studio_tenant_id": "tenant-fulda"},
        {"studio_tenant_id": None},
        {"studio_tenant_id": ["tenant-kassel"]},
        {"ssf_authorization_revision": None},
        {"ssf_authorization_revision": f"sha256:{'A' * 64}"},
        {"ssf_authorization_revision": f"sha256:{'a' * 64}\n"},
        {"ssf_authorization_revision": [REVISION]},
        {"aud": "other-app"},
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        {"exp": None},
    ],
)
def test_signed_claims_must_be_valid_and_bound_to_the_realm(monkeypatch, signing_key, overrides):
    mock_keycloak(monkeypatch, signing_key)
    assert request_with_token(access_token(signing_key, **overrides)).status_code == 401


def test_invalid_signature_is_rejected(monkeypatch, signing_key):
    mock_keycloak(monkeypatch, signing_key)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert request_with_token(access_token(other_key)).status_code == 401


def test_non_rsa_jwk_fails_closed(monkeypatch, signing_key):
    mock_keycloak(monkeypatch, signing_key, jwk_override={"kty": "EC"})
    assert request_with_token(access_token(signing_key)).status_code == 401


@pytest.mark.parametrize("realm_access", [{"roles": []}, None, [], {"roles": "ssf-user"}])
def test_missing_or_malformed_role_is_rejected(monkeypatch, signing_key, realm_access):
    mock_keycloak(monkeypatch, signing_key)
    assert (
        request_with_token(access_token(signing_key, realm_access=realm_access)).status_code == 403
    )


@pytest.mark.parametrize(
    "metadata_override",
    [
        {"issuer": FULDA_ISSUER},
        {"issuer": None},
        {"jwks_uri": "https://attacker.test/jwks"},
        {"jwks_uri": f"{FULDA_ISSUER}/protocol/openid-connect/certs"},
    ],
)
def test_discovery_must_match_the_admitted_issuer_before_fetching_keys(
    monkeypatch, signing_key, metadata_override
):
    calls = mock_keycloak(monkeypatch, signing_key, metadata_override=metadata_override)
    assert request_with_token(access_token(signing_key)).status_code == 401
    assert calls == [f"{KASSEL_ISSUER}/.well-known/openid-configuration"]


@pytest.mark.parametrize("redirect_suffix", ["openid-configuration", "certs"])
def test_oidc_redirects_are_rejected(monkeypatch, signing_key, redirect_suffix):
    mock_keycloak(monkeypatch, signing_key, redirect_suffix=redirect_suffix)
    assert request_with_token(access_token(signing_key)).status_code == 401


def test_cached_signing_keys_do_not_admit_a_removed_realm(monkeypatch, signing_key):
    now = [0]
    fetcher = DirectoryFetcher()
    service = StudioLoginDirectoryService(fetcher, cache_seconds=60, clock=lambda: now[0])
    app.dependency_overrides[get_auth_login_directory_provider] = lambda: lambda: service
    calls = mock_keycloak(monkeypatch, signing_key)
    token = access_token(signing_key)
    assert request_with_token(token).status_code == 200

    now[0] = 61
    fetcher.directory = DIRECTORY.model_copy(update={"tenants": ()})
    calls.clear()
    assert request_with_token(token).status_code == 401
    assert calls == []


@pytest.mark.parametrize("previously_cached", [False, True])
def test_unavailable_or_expired_directory_fails_closed(monkeypatch, signing_key, previously_cached):
    now = [0]
    fetcher = DirectoryFetcher()
    service = StudioLoginDirectoryService(fetcher, cache_seconds=60, clock=lambda: now[0])
    if previously_cached:
        asyncio.run(service.get("prime-cache"))
        now[0] = 61
    fetcher.unavailable = True
    app.dependency_overrides[get_auth_login_directory_provider] = lambda: lambda: service
    calls = mock_keycloak(monkeypatch, signing_key)
    assert request_with_token(access_token(signing_key)).status_code == 503
    assert calls == []


def test_tenant_dependency_receives_verified_claims_from_async_auth(
    monkeypatch, signing_key, auth_environment
):
    mock_keycloak(monkeypatch, signing_key)
    tenant_app = FastAPI()
    tenant_app.dependency_overrides[get_auth_login_directory_provider] = (
        lambda: lambda: auth_environment
    )

    @tenant_app.get("/tenant")
    async def tenant(
        context: StudioTenantContext = Depends(require_studio_tenant_context),
    ):
        return {
            "tenant_id": context.tenant_id,
            "revision": context.authorization_revision,
        }

    token = access_token(signing_key, iss=FULDA_ISSUER, studio_tenant_id="tenant-fulda")
    response = TestClient(tenant_app).get("/tenant", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-fulda", "revision": REVISION}


@pytest.mark.parametrize("configured", [False, True])
def test_legacy_access_is_rejected_even_when_environment_flag_is_set(monkeypatch, configured):
    monkeypatch.setenv("SSF_ENABLE_LEGACY_ADMIN_ACCESS", "true")
    monkeypatch.setenv("SSF_LEGACY_ADMIN_ACCESS_CODE", "transition-code")
    if configured:
        fetcher = DirectoryFetcher()
        fetcher.unavailable = True
        service = StudioLoginDirectoryService(fetcher, cache_seconds=60)
        app.dependency_overrides[get_auth_login_directory_provider] = lambda: lambda: service
    else:
        app.dependency_overrides.pop(get_auth_login_directory_provider)
        monkeypatch.delenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", raising=False)
    response = client.get(
        "/api/admin/session/history", headers={"X-SSF-Legacy-Access": "transition-code"}
    )
    assert response.status_code == 401


def test_admin_endpoints_reject_legacy_access_after_transition_is_disabled(monkeypatch):
    monkeypatch.setenv("SSF_LEGACY_ADMIN_ACCESS_CODE", "transition-code")
    response = client.get(
        "/api/admin/session/history", headers={"X-SSF-Legacy-Access": "transition-code"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "base_url",
    [
        f"{BASE_URL}/auth",
        f"{BASE_URL}?realm=ssf",
        "https://user:pass@auth.example.test",
    ],
)
def test_non_origin_keycloak_base_url_is_rejected(monkeypatch, signing_key, base_url):
    monkeypatch.setenv("KEYCLOAK_BASE_URL", base_url)
    calls = mock_keycloak(monkeypatch, signing_key)
    assert request_with_token(access_token(signing_key)).status_code == 401
    assert calls == []


def test_base_url_trailing_slash_is_normalized(monkeypatch, signing_key):
    monkeypatch.setenv("KEYCLOAK_BASE_URL", f"{BASE_URL}/")
    monkeypatch.setenv("KEYCLOAK_ISSUER", "https://obsolete.test/realms/ssf")
    mock_keycloak(monkeypatch, signing_key)
    assert request_with_token(access_token(signing_key)).status_code == 200
