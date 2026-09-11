"""Tenant-bound conversation identity and configuration snapshot tests."""

from hashlib import sha256

import pytest

from services.api_gateway.session_manager import Session
from services.api_gateway.studio_runtime_client import RuntimeConfiguration
from services.api_gateway.tenant_session import (
    RuntimeConfigurationSnapshot,
    TenantSessionKey,
)

REVISION = f"sha256:{'a' * 64}"


def runtime_configuration(tenant_id: str = "tenant-a") -> RuntimeConfiguration:
    return RuntimeConfiguration.model_validate(
        {
            "contractVersion": "1.0",
            "configurationRevision": REVISION,
            "authorizationRevision": REVISION,
            "tenant": {
                "id": tenant_id,
                "displayName": "Tenant A",
                "timeZone": "Europe/Berlin",
            },
            "branding": {"logo": None, "icon": None},
            "localization": {
                "defaultLocale": "de-DE",
                "locales": [
                    {
                        "locale": "de-DE",
                        "authenticatedHomeExplanationHtml": "<p>Admin</p>",
                        "guestExplanationHtml": "<p>Guest</p>",
                        "conversationContentStorageQuestionHtml": "<p>Store?</p>",
                    }
                ],
            },
            "conversationContentStorage": {"mode": "ask"},
        }
    )


def test_tenant_session_key_uses_unpadded_urlsafe_redis_component() -> None:
    key = TenantSessionKey("stadt:kassel/ä", "ABC12345")

    assert key.redis_tenant_component == "c3RhZHQ6a2Fzc2VsL8Ok"
    assert key.tenant_ref == sha256("stadt:kassel/ä".encode()).hexdigest()[:12]


@pytest.mark.parametrize(
    ("tenant_id", "session_id"),
    [("", "ABC12345"), ("x" * 129, "ABC12345"), ("tenant-a", "../escape")],
)
def test_tenant_session_key_rejects_invalid_identifiers(tenant_id: str, session_id: str) -> None:
    with pytest.raises(ValueError):
        TenantSessionKey(tenant_id, session_id)


def test_runtime_configuration_snapshot_is_canonical_and_round_trips() -> None:
    configuration = runtime_configuration()

    snapshot = RuntimeConfigurationSnapshot.from_configuration(configuration)

    assert snapshot.configuration_revision == REVISION
    assert snapshot.authorization_revision == REVISION
    assert snapshot.to_configuration() == configuration
    assert '": "' not in snapshot.canonical_json
    assert '", "' not in snapshot.canonical_json


def test_session_round_trip_preserves_tenant_and_runtime_configuration() -> None:
    configuration = runtime_configuration()
    snapshot = RuntimeConfigurationSnapshot.from_configuration(configuration)
    session = Session(
        id="ABC12345",
        tenant_id="tenant-a",
        runtime_configuration=snapshot,
    )

    restored = Session.from_dict(session.to_dict(include_messages=True))

    assert restored.key == TenantSessionKey("tenant-a", "ABC12345")
    assert restored.runtime_configuration == snapshot
    assert restored.runtime_configuration.to_configuration() == configuration


def test_session_payload_without_tenant_scope_is_rejected() -> None:
    configuration = runtime_configuration()
    session = Session(
        id="ABC12345",
        tenant_id="tenant-a",
        runtime_configuration=RuntimeConfigurationSnapshot.from_configuration(configuration),
    )
    payload = session.to_dict(include_messages=True)
    del payload["tenant_id"]

    with pytest.raises((KeyError, TypeError, ValueError)):
        Session.from_dict(payload)
