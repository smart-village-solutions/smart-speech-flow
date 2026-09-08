"""Contract tests for the Studio Runtime Configuration V1 mock."""

import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient

from services.studio_mock.app import app

CLIENT = TestClient(app)
PATH = "/internal/plugins/ssf/v1/runtime-configuration"
AUTHORIZED_TOKEN = "Bearer studio-mock-authorized-token"
UNAUTHORIZED_TOKEN = "Bearer studio-mock-unauthorized-token"


def _headers(tenant_id: str = "tenant-kassel", **additional: str) -> dict[str, str]:
    return {
        "Authorization": AUTHORIZED_TOKEN,
        "X-Studio-Tenant-Id": tenant_id,
        "X-Correlation-Id": "test-correlation-id",
        **additional,
    }


def test_returns_v1_configuration_for_authorized_studio_tenant() -> None:
    response = CLIENT.get(PATH, headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant"]["id"] == "tenant-kassel"
    assert payload["localization"]["defaultLocale"] == "de-DE"
    assert payload["localization"]["locales"][0]["locale"] == "de-DE"
    assert payload["conversationContentStorage"] == {"mode": "ask"}


def test_response_tenant_identity_exactly_matches_studio_tenant_header() -> None:
    tenant_id = "tenant-fulda"

    response = CLIENT.get(PATH, headers=_headers(tenant_id))

    assert response.status_code == 200
    assert response.json()["tenant"]["id"] == tenant_id
    assert response.json()["conversationContentStorage"] == {"mode": "disabled"}


@pytest.mark.parametrize("legacy_header", ["X-Studio-Instance-Id", "X-Tenant-Id"])
def test_rejects_legacy_tenant_headers_without_the_canonical_header(
    legacy_header: str,
) -> None:
    response = CLIENT.get(
        PATH,
        headers={
            "Authorization": AUTHORIZED_TOKEN,
            legacy_header: "tenant-kassel",
            "X-Correlation-Id": "test-correlation-id",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "tenant_not_found",
        "message": "The requested tenant is unavailable.",
        "retryable": False,
        "correlationId": "test-correlation-id",
    }


@pytest.mark.parametrize(
    ("headers", "status_code", "code", "retryable"),
    [
        ({"X-Correlation-Id": "test-correlation-id"}, 401, "service_authentication_invalid", False),
        (
            {"Authorization": UNAUTHORIZED_TOKEN, "X-Correlation-Id": "test-correlation-id"},
            403,
            "service_action_forbidden",
            False,
        ),
        (_headers("tenant-unknown"), 404, "tenant_not_found", False),
        (
            _headers(**{"X-Mock-Scenario": "tenant-suspended"}),
            409,
            "tenant_suspended",
            False,
        ),
        (
            _headers(**{"X-Mock-Scenario": "plugin-inactive"}),
            409,
            "ssf_plugin_inactive",
            False,
        ),
        (
            _headers(**{"X-Mock-Scenario": "tenant-not-ready"}),
            409,
            "ssf_tenant_not_ready",
            True,
        ),
        (
            _headers(**{"X-Mock-Scenario": "unavailable"}),
            503,
            "runtime_configuration_unavailable",
            True,
        ),
    ],
)
def test_returns_only_documented_stable_error_codes(
    headers: dict[str, str], status_code: int, code: str, retryable: bool
) -> None:
    response = CLIENT.get(PATH, headers=headers)

    assert response.status_code == status_code
    assert response.json() == {
        "contractVersion": "1.0",
        "error": {
            "code": code,
            "message": "The requested tenant is unavailable.",
            "retryable": retryable,
            "correlationId": "test-correlation-id",
        },
    }


@pytest.mark.parametrize(
    "scenario", ["tenant-suspended", "plugin-inactive", "tenant-not-ready", "unavailable"]
)
def test_each_documented_mock_scenario_is_selectable(scenario: str) -> None:
    response = CLIENT.get(PATH, headers=_headers(**{"X-Mock-Scenario": scenario}))

    assert response.status_code in {409, 503}


def test_authorization_pending_is_not_a_mock_scenario_alias() -> None:
    response = CLIENT.get(
        PATH, headers=_headers(**{"X-Mock-Scenario": "authorization-pending"})
    )

    assert response.status_code == 200


def test_missing_or_invalid_required_selection_headers_use_tenant_not_found() -> None:
    missing_correlation = CLIENT.get(
        PATH,
        headers={"Authorization": AUTHORIZED_TOKEN, "X-Studio-Tenant-Id": "tenant-kassel"},
    )
    empty_tenant = CLIENT.get(PATH, headers=_headers(""))

    for response in (missing_correlation, empty_tenant):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "tenant_not_found"


def test_revisions_are_deterministic_and_canonically_hashed() -> None:
    first_payload = CLIENT.get(PATH, headers=_headers()).json()
    second_payload = CLIENT.get(PATH, headers=_headers()).json()

    assert first_payload["configurationRevision"] == second_payload["configurationRevision"]
    assert first_payload["authorizationRevision"] == second_payload["authorizationRevision"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", first_payload["configurationRevision"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", first_payload["authorizationRevision"])

    authorization = {
        "tenant_id": "tenant-kassel",
        "permissions": ["ssf.runtime-configuration.read"],
    }
    expected_authorization_revision = hashlib.sha256(
        json.dumps(authorization, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert first_payload["authorizationRevision"] == f"sha256:{expected_authorization_revision}"

    configuration = dict(first_payload)
    configuration.pop("configurationRevision")
    expected_configuration_revision = hashlib.sha256(
        json.dumps(configuration, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert first_payload["configurationRevision"] == f"sha256:{expected_configuration_revision}"


def test_openapi_documents_only_the_canonical_tenant_header_and_v1_contract() -> None:
    schema = CLIENT.get("/openapi.json").json()
    operation = schema["paths"][PATH]["get"]
    headers = {
        parameter["name"]: parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "header"
    }

    assert set(headers) == {"authorization", "x-studio-tenant-id", "x-correlation-id", "x-mock-scenario"}
    for header_name in ("authorization", "x-studio-tenant-id", "x-correlation-id"):
        assert headers[header_name]["required"] is True
        assert headers[header_name]["schema"] == {"type": "string"}
    assert headers["x-mock-scenario"]["required"] is False
    assert set(headers["x-mock-scenario"]["schema"]["enum"]) == {
        "tenant-suspended",
        "plugin-inactive",
        "tenant-not-ready",
        "unavailable",
    }
    assert "x-studio-instance-id" not in headers
    assert "x-tenant-id" not in headers

    error_code_schema = schema["components"]["schemas"]["RuntimeError"]["properties"][
        "code"
    ]
    assert set(error_code_schema["enum"]) == {
        "service_authentication_invalid",
        "service_action_forbidden",
        "tenant_not_found",
        "tenant_suspended",
        "ssf_plugin_inactive",
        "ssf_tenant_not_ready",
        "runtime_configuration_unavailable",
    }

    responses = operation["responses"]
    assert set(responses) >= {"200", "401", "403", "404", "409", "503"}
    assert "400" not in responses
