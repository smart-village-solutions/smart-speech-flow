import asyncio
import dataclasses
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from services.api_gateway.app import app
from services.api_gateway.auth import (
    AuthenticatedPrincipal,
    _key_cache,
    get_auth_login_directory_provider,
    require_ssf_user,
)
from services.api_gateway.session_pseudonym import tenant_ref
from services.api_gateway.studio_login_directory import (
    StudioLoginDirectoryService,
    _build_studio_login_directory_service,
)
from services.api_gateway.studio_login_directory_client import (
    StudioLoginDirectory,
    StudioLoginDirectoryClientError,
)
from services.api_gateway.tenant_context import StudioTenantContext, require_studio_tenant_context
from tests.script_helpers import load_contract

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
    service = StudioLoginDirectoryService(DirectoryFetcher(), cache_seconds=60)
    app.dependency_overrides[get_auth_login_directory_provider] = lambda: lambda: service
    yield service
    app.dependency_overrides.pop(get_auth_login_directory_provider, None)
    _key_cache.entries.clear()


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


# access_token drops claims set to None; JSON_NULL sends an explicit null.
JSON_NULL = object()


def access_token(signing_key, **overrides):
    """A token shaped like production's: no studio_tenant_id unless a test adds one."""
    claims = {
        "sub": "operator-1",
        "iss": KASSEL_ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "realm_access": {"roles": ["ssf-user"]},
        "ssf_authorization_revision": REVISION,
    }
    claims.update(overrides)
    claims = {
        key: (None if value is JSON_NULL else value)
        for key, value in claims.items()
        if value is not None
    }
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


@pytest.mark.parametrize("issuer", [KASSEL_ISSUER, FULDA_ISSUER])
def test_admin_endpoints_accept_each_allowlisted_realm(monkeypatch, signing_key, issuer):
    calls = mock_keycloak(monkeypatch, signing_key)
    response = request_with_token(access_token(signing_key, iss=issuer))
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
        {"ssf_authorization_revision": None},
        {"ssf_authorization_revision": JSON_NULL},
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

    token = access_token(signing_key, iss=FULDA_ISSUER)
    response = TestClient(tenant_app).get("/tenant", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-fulda", "revision": REVISION}


# An environment file from before #216 may still set the retired variables.
@pytest.mark.parametrize("configured", [False, True])
def test_legacy_access_header_is_ignored_even_when_retired_variables_are_set(
    monkeypatch, configured
):
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


def test_admin_endpoints_ignore_the_legacy_access_header():
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


AUTH_LOGGER = "services.api_gateway.auth_rejections"
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _reasons(caplog):
    return [record.reason for record in caplog.records if record.name == AUTH_LOGGER]


def _expired(key):
    return access_token(key, exp=datetime.now(timezone.utc) - timedelta(minutes=1))


@pytest.mark.parametrize(
    ("token_factory", "keycloak", "reason"),
    [
        (lambda key: None, {}, "missing_bearer"),
        (lambda key: "not-a-jwt", {}, "malformed_token"),
        (lambda key: access_token(key, iss=[KASSEL_ISSUER]), {}, "malformed_token"),
        (lambda key: access_token(key, iss=f"{BASE_URL}/realms/unknown"), {}, "unknown_issuer"),
        (_expired, {}, "token_expired"),
        (lambda key: access_token(key, aud="other-app"), {}, "invalid_audience"),
        (lambda key: access_token(OTHER_KEY), {}, "invalid_signature"),
        (lambda key: access_token(key, exp=None), {}, "missing_required_claim"),
        (
            lambda key: access_token(key),
            {"jwk_override": {"kid": "rotated"}},
            "unknown_signing_key",
        ),
        (lambda key: access_token(key), {"jwk_override": {"kty": "EC"}}, "invalid_signing_key"),
        (
            lambda key: access_token(key),
            {"metadata_override": {"issuer": FULDA_ISSUER}},
            "signing_keys_unavailable",
        ),
        (lambda key: access_token(key), {"redirect_suffix": "certs"}, "signing_keys_unavailable"),
        (lambda key: access_token(key, ssf_authorization_revision=None), {}, "revision_missing"),
        (
            lambda key: access_token(key, ssf_authorization_revision=f"sha256:{'A' * 64}"),
            {},
            "revision_malformed",
        ),
        (
            lambda key: access_token(key, ssf_authorization_revision=[REVISION]),
            {},
            "revision_malformed",
        ),
        (lambda key: access_token(key, realm_access={"roles": []}), {}, "role_missing"),
    ],
)
def test_each_rejection_logs_its_reason_once(
    monkeypatch, signing_key, caplog, token_factory, keycloak, reason
):
    # INFO, not WARNING: a request with no bearer at all logs at INFO.
    caplog.set_level(logging.INFO, logger=AUTH_LOGGER)
    mock_keycloak(monkeypatch, signing_key, **keycloak)
    token = token_factory(signing_key)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.get("/api/admin/session/history", headers=headers)
    assert response.status_code == (403 if reason == "role_missing" else 401)
    assert _reasons(caplog) == [reason]


def test_unsupported_token_header_is_classified(monkeypatch, signing_key, caplog):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    mock_keycloak(monkeypatch, signing_key)
    token = jwt.encode(
        {"iss": KASSEL_ISSUER, "aud": AUDIENCE, "exp": 4102444800},
        "not-a-real-secret-" * 2,
        algorithm="HS256",
    )
    assert request_with_token(token).status_code == 401
    assert _reasons(caplog) == ["unsupported_token_header"]


def test_unavailable_directory_is_classified(monkeypatch, signing_key, caplog):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    fetcher = DirectoryFetcher()
    fetcher.unavailable = True
    service = StudioLoginDirectoryService(fetcher, cache_seconds=60)
    app.dependency_overrides[get_auth_login_directory_provider] = lambda: lambda: service
    mock_keycloak(monkeypatch, signing_key)
    assert request_with_token(access_token(signing_key)).status_code == 503
    assert _reasons(caplog) == ["directory_unavailable"]


def test_an_unconfigured_directory_is_classified_and_counted(monkeypatch, signing_key, caplog):
    """The real provider, not an override: a missing Studio base URL in production."""
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    app.dependency_overrides.pop(get_auth_login_directory_provider)
    monkeypatch.delenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", raising=False)
    _build_studio_login_directory_service.cache_clear()
    mock_keycloak(monkeypatch, signing_key)

    def unconfigured_count():
        return app.state.prometheus_registry.get_sample_value(
            "gateway_auth_rejections_total", {"reason": "directory_unavailable"}
        )

    before = unconfigured_count()
    try:
        response = request_with_token(access_token(signing_key))
    finally:
        _build_studio_login_directory_service.cache_clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "The login directory is temporarily unavailable"}
    assert _reasons(caplog) == ["directory_unavailable"]
    assert unconfigured_count() == before + 1


def test_misconfigured_keycloak_base_url_is_classified(monkeypatch, signing_key, caplog):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    monkeypatch.setenv("KEYCLOAK_BASE_URL", f"{BASE_URL}/auth")
    mock_keycloak(monkeypatch, signing_key)
    assert request_with_token(access_token(signing_key)).status_code == 401
    assert _reasons(caplog) == ["gateway_auth_misconfigured"]


def test_token_without_a_tenant_claim_is_bound_to_its_issuers_tenant(monkeypatch, signing_key):
    """The #363 production shape: no studio_tenant_id at all."""
    mock_keycloak(monkeypatch, signing_key)
    assert request_with_token(access_token(signing_key, iss=FULDA_ISSUER)).status_code == 200


@pytest.mark.parametrize(
    "tenant_claim",
    ["tenant-fulda", "", JSON_NULL, ["tenant-kassel"], {"id": "tenant-kassel"}, 7, True],
)
def test_a_disagreeing_or_malformed_tenant_claim_is_rejected(
    monkeypatch, signing_key, caplog, tenant_claim
):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    mock_keycloak(monkeypatch, signing_key)
    response = request_with_token(access_token(signing_key, studio_tenant_id=tenant_claim))
    assert response.status_code == 401
    assert response.json() == {"detail": "A valid bearer token is required"}
    assert _reasons(caplog) == ["tenant_claim_mismatch"]


def test_an_agreeing_tenant_claim_is_still_accepted(monkeypatch, signing_key):
    mock_keycloak(monkeypatch, signing_key)
    token = access_token(signing_key, studio_tenant_id="tenant-kassel")
    assert request_with_token(token).status_code == 200


def test_a_claim_naming_another_listed_tenant_cannot_switch_tenants(monkeypatch, signing_key):
    """A Kassel-issued token that claims Fulda must not act as Fulda."""
    mock_keycloak(monkeypatch, signing_key)
    token = access_token(signing_key, iss=KASSEL_ISSUER, studio_tenant_id="tenant-fulda")
    assert request_with_token(token).status_code == 401


def _whoami_client(auth_environment):
    probe = FastAPI()
    probe.dependency_overrides[get_auth_login_directory_provider] = lambda: lambda: auth_environment

    @probe.get("/whoami")
    async def whoami(principal: Annotated[AuthenticatedPrincipal, Depends(require_ssf_user)]):
        return {
            "tenant_id": principal.tenant_id,
            "realm": principal.realm,
            "revision": principal.authorization_revision,
            "subject": principal.subject,
            "legacy": principal.carries_legacy_tenant_claim,
        }

    return TestClient(probe)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {"iss": FULDA_ISSUER},
            {
                "tenant_id": "tenant-fulda",
                "realm": "fulda-ssf-2025",
                "subject": "operator-1",
                "legacy": False,
            },
        ),
        (
            {"iss": FULDA_ISSUER, "tenant_id": "tenant-kassel"},
            {
                "tenant_id": "tenant-fulda",
                "realm": "fulda-ssf-2025",
                "subject": "operator-1",
                "legacy": True,
            },
        ),
        (
            {"studio_instance_id": "x", "sub": None},
            {
                "tenant_id": "tenant-kassel",
                "realm": "kassel-ssf-2025",
                "subject": None,
                "legacy": True,
            },
        ),
        (
            {"sub": ""},
            {
                "tenant_id": "tenant-kassel",
                "realm": "kassel-ssf-2025",
                "subject": None,
                "legacy": False,
            },
        ),
    ],
)
def test_principal_carries_the_directory_tenant_not_a_token_value(
    monkeypatch, signing_key, auth_environment, overrides, expected
):
    mock_keycloak(monkeypatch, signing_key)
    token = access_token(signing_key, **overrides)
    response = _whoami_client(auth_environment).get(
        "/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json() == {**expected, "revision": REVISION}


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"studio_tenant_id": "tenant-kassel"},
        {"studio_tenant_id": "tenant-fulda"},
        {"studio_tenant_id": JSON_NULL},
        {"ssf_authorization_revision": None},
        {"ssf_authorization_revision": JSON_NULL},
        {"ssf_authorization_revision": f"sha256:{'A' * 64}"},
        {"realm_access": {"roles": ["system_admin"]}},
        {"realm_access": {"roles": "ssf-user"}},
        {"aud": ["account", AUDIENCE]},
        {"aud": "account"},
    ],
)
def test_the_operator_scripts_contract_agrees_with_the_gateway(monkeypatch, signing_key, overrides):
    """scripts/lib/ssf_auth_contract.py cannot import the gateway, so prove parity."""
    mock_keycloak(monkeypatch, signing_key)
    token = access_token(signing_key, **overrides)
    contract = load_contract()
    flags = contract.token_flags(
        contract.unverified_claims(token),
        tenant_id="tenant-kassel",
        audience=AUDIENCE,
        role="ssf-user",
    )
    assert (request_with_token(token).status_code == 200) is flags["would_pass"]


def test_the_principal_is_immutable():
    principal = AuthenticatedPrincipal("tenant-kassel", "kassel-ssf-2025", REVISION, "s", False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        principal.tenant_id = "tenant-fulda"  # type: ignore[misc]


def test_rejection_logs_never_contain_the_token_or_claims(monkeypatch, signing_key, caplog):
    caplog.set_level(logging.DEBUG)
    mock_keycloak(monkeypatch, signing_key)
    token = access_token(signing_key, ssf_authorization_revision=None, sub="subject-secret")
    assert request_with_token(token).status_code == 401
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "revision_missing" in logged
    for forbidden in (
        token,
        token.split(".")[1],
        "subject-secret",
        "tenant-kassel",
        "kassel-ssf-2025",
        KASSEL_ISSUER,
    ):
        assert forbidden not in logged


def test_rejection_carries_the_callers_correlation_id_to_log_and_directory(
    monkeypatch, signing_key, caplog
):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    seen = []

    class RecordingFetcher(DirectoryFetcher):
        async def fetch(self, correlation_id):
            seen.append(correlation_id)
            return self.directory

    service = StudioLoginDirectoryService(RecordingFetcher(), cache_seconds=60)
    app.dependency_overrides[get_auth_login_directory_provider] = lambda: lambda: service
    mock_keycloak(monkeypatch, signing_key)
    response = client.get(
        "/api/admin/session/history",
        headers={
            "Authorization": f"Bearer {access_token(signing_key, ssf_authorization_revision=None)}",
            "X-Correlation-Id": "corr-363",
        },
    )
    assert response.status_code == 401
    assert seen == ["corr-363"]
    assert [record.correlation_id for record in caplog.records if record.name == AUTH_LOGGER] == [
        "corr-363"
    ]


@pytest.mark.parametrize("correlation_id", [b"", b"x" * 129, b"caf\xe9"])
def test_invalid_correlation_id_does_not_change_the_rejection(
    monkeypatch, signing_key, correlation_id
):
    mock_keycloak(monkeypatch, signing_key)
    response = client.get(
        "/api/admin/session/history",
        headers={"Authorization": "Bearer not-a-jwt", "X-Correlation-Id": correlation_id},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "A valid bearer token is required"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("overrides", "expected_ref"),
    [
        ({"ssf_authorization_revision": None}, tenant_ref("tenant-kassel")),
        ({"iss": FULDA_ISSUER, "realm_access": {"roles": []}}, tenant_ref("tenant-fulda")),
        ({"iss": f"{BASE_URL}/realms/unknown"}, "-"),
    ],
)
def test_a_rejection_is_attributed_to_the_matched_tenant_only(
    monkeypatch, signing_key, caplog, overrides, expected_ref
):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    mock_keycloak(monkeypatch, signing_key)
    request_with_token(access_token(signing_key, **overrides))
    assert [record.tenant_ref for record in caplog.records if record.name == AUTH_LOGGER] == [
        expected_ref
    ]


def test_accepted_token_logs_no_rejection(monkeypatch, signing_key, caplog):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    mock_keycloak(monkeypatch, signing_key)
    assert request_with_token(access_token(signing_key)).status_code == 200
    assert _reasons(caplog) == []


def test_customer_route_with_a_rejected_bearer_is_classified(monkeypatch, signing_key, caplog):
    """optional_ssf_user reaches the same classification as the admin routes."""
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    mock_keycloak(monkeypatch, signing_key)
    response = client.get(
        "/api/customer/session/UNKNOWN1",
        headers={"Authorization": f"Bearer {access_token(signing_key, aud='other-app')}"},
    )
    assert response.status_code == 401
    assert _reasons(caplog) == ["invalid_audience"]
