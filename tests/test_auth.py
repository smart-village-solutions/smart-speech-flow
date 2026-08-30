import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.api_gateway.app import app
from services.api_gateway.auth import _key_cache

client = TestClient(app)

ISSUER = "https://auth.example.test/realms/ssf"
AUDIENCE = "ssf-frontend"


@pytest.fixture(autouse=True)
def clear_cached_keys():
    _key_cache.entries.clear()


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def access_token(signing_key, *, roles, audience=AUDIENCE, issuer=ISSUER):
    return jwt.encode(
        {
            "sub": "operator-1",
            "iss": issuer,
            "aud": audience,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "realm_access": {"roles": roles},
        },
        signing_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def mock_keycloak(monkeypatch, signing_key):
    jwk = json.loads(RSAAlgorithm.to_jwk(signing_key.public_key()))
    jwk["kid"] = "test-key"

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    def get(url, timeout):
        assert timeout == 5
        if url.endswith("/.well-known/openid-configuration"):
            return Response({"jwks_uri": "https://auth.example.test/jwks"})
        assert url == "https://auth.example.test/jwks"
        return Response({"keys": [jwk]})

    monkeypatch.setattr("requests.get", get)
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("KEYCLOAK_REQUIRED_ROLE", "ssf-user")


def test_admin_endpoints_reject_requests_without_a_bearer_token():
    response = client.get("/api/admin/session/history")

    assert response.status_code == 401


def test_admin_endpoints_reject_valid_tokens_without_the_ssf_user_role(monkeypatch, signing_key):
    mock_keycloak(monkeypatch, signing_key)

    response = client.get(
        "/api/admin/session/history",
        headers={"Authorization": f"Bearer {access_token(signing_key, roles=[])}"},
    )

    assert response.status_code == 403


def test_admin_endpoints_accept_valid_ssf_user_tokens(monkeypatch, signing_key):
    mock_keycloak(monkeypatch, signing_key)

    response = client.get(
        "/api/admin/session/history",
        headers={"Authorization": f"Bearer {access_token(signing_key, roles=['ssf-user'])}"},
    )

    assert response.status_code == 200


def test_admin_endpoints_accept_legacy_access_only_when_transition_is_enabled(
    monkeypatch,
):
    monkeypatch.setenv("SSF_ENABLE_LEGACY_ADMIN_ACCESS", "true")
    monkeypatch.setenv("SSF_LEGACY_ADMIN_ACCESS_CODE", "transition-code")

    response = client.get(
        "/api/admin/session/history",
        headers={"X-SSF-Legacy-Access": "transition-code"},
    )

    assert response.status_code == 200


def test_admin_endpoints_reject_legacy_access_after_transition_is_disabled(monkeypatch):
    monkeypatch.setenv("SSF_ENABLE_LEGACY_ADMIN_ACCESS", "false")
    monkeypatch.setenv("SSF_LEGACY_ADMIN_ACCESS_CODE", "transition-code")

    response = client.get(
        "/api/admin/session/history",
        headers={"X-SSF-Legacy-Access": "transition-code"},
    )

    assert response.status_code == 401
