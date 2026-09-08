"""Contract tests for the Studio Runtime Configuration V1 mock."""

import hashlib
import json
import re

from fastapi.testclient import TestClient
from httpx import Response

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


def _assert_error(response: Response, status: int, code: str, retryable: bool) -> None:
    assert response.status_code == status
    assert response.json() == {
        "contractVersion": "1.0",
        "error": {
            "code": code,
            "message": "Runtime configuration is unavailable.",
            "retryable": retryable,
            "correlationId": "test-correlation-id",
        },
    }


def test_returns_v1_configuration_for_authorized_tenant() -> None:
    response = CLIENT.get(PATH, headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "contractVersion": "1.0",
        "configurationRevision": payload["configurationRevision"],
        "authorizationRevision": payload["authorizationRevision"],
        "tenant": {
            "id": "tenant-kassel",
            "displayName": "Kassel Test Municipality",
            "timeZone": "Europe/Berlin",
        },
        "branding": {"logo": None, "icon": None},
        "localization": {
            "defaultLocale": "de-DE",
            "locales": [
                {
                    "locale": "de-DE",
                    "authenticatedHomeExplanationHtml": "<p>Test environment</p>",
                    "guestExplanationHtml": "<p>Guest test environment</p>",
                    "conversationContentStorageQuestionHtml": "<p>Store this conversation?</p>",
                }
            ],
        },
        "conversationContentStorage": {"mode": "ask"},
    }
    configuration_revision = payload.pop("configurationRevision")
    authorization_revision = payload["authorizationRevision"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", configuration_revision)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", authorization_revision)
    expected_configuration_revision = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert configuration_revision == f"sha256:{expected_configuration_revision}"


def test_returns_disabled_policy_for_second_tenant() -> None:
    response = CLIENT.get(PATH, headers=_headers("tenant-fulda"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant"]["id"] == "tenant-fulda"
    assert payload["conversationContentStorage"] == {"mode": "disabled"}
    assert payload["localization"]["locales"][0]["conversationContentStorageQuestionHtml"] is None


def test_rejects_missing_or_unknown_service_token() -> None:
    missing_token = CLIENT.get(PATH, headers={"X-Correlation-Id": "test-correlation-id"})
    unknown_token = CLIENT.get(PATH, headers=_headers(Authorization="Bearer unknown"))

    for response in (missing_token, unknown_token):
        _assert_error(response, 401, "service_authentication_invalid", False)


def test_rejects_service_token_without_runtime_configuration_permission() -> None:
    response = CLIENT.get(PATH, headers=_headers(Authorization=UNAUTHORIZED_TOKEN))

    _assert_error(response, 403, "service_action_forbidden", False)


def test_rejects_missing_tenant_and_correlation_headers() -> None:
    missing_tenant = CLIENT.get(
        PATH,
        headers={"Authorization": AUTHORIZED_TOKEN, "X-Correlation-Id": "test-correlation-id"},
    )
    missing_correlation = CLIENT.get(
        PATH,
        headers={"Authorization": AUTHORIZED_TOKEN, "X-Studio-Tenant-Id": "tenant-kassel"},
    )

    assert missing_tenant.status_code == 404
    assert missing_tenant.json()["error"]["code"] == "tenant_not_found"
    assert missing_correlation.status_code == 404
    assert missing_correlation.json() == {
        "contractVersion": "1.0",
        "error": {
            "code": "tenant_not_found",
            "message": "Runtime configuration is unavailable.",
            "retryable": False,
            "correlationId": "unavailable",
        },
    }


def test_rejects_competing_tenant_selectors() -> None:
    responses = [
        CLIENT.get(
            PATH,
            headers={
                "Authorization": AUTHORIZED_TOKEN,
                "X-Studio-Instance-Id": "tenant-kassel",
                "X-Correlation-Id": "test-correlation-id",
            },
        ),
        CLIENT.get(PATH, headers=_headers(**{"X-Studio-Instance-Id": "tenant-kassel"})),
        CLIENT.get(PATH, headers=_headers(**{"X-Tenant-Id": "tenant-kassel"})),
        CLIENT.get(PATH, params={"tenantId": "tenant-kassel"}, headers=_headers()),
    ]

    for response in responses:
        _assert_error(response, 404, "tenant_not_found", False)


def test_returns_not_found_for_unknown_tenant() -> None:
    response = CLIENT.get(PATH, headers=_headers("tenant-unknown"))

    _assert_error(response, 404, "tenant_not_found", False)


def test_returns_documented_mock_failure_envelopes() -> None:
    for scenario, status_code, code, retryable in [
        ("suspended", 409, "tenant_suspended", False),
        ("plugin-inactive", 409, "ssf_plugin_inactive", False),
        ("tenant-not-ready", 409, "ssf_tenant_not_ready", True),
        ("unavailable", 503, "runtime_configuration_unavailable", True),
    ]:
        response = CLIENT.get(PATH, headers=_headers(**{"X-Mock-Scenario": scenario}))

        _assert_error(response, status_code, code, retryable)


def test_openapi_documents_every_runtime_configuration_error() -> None:
    schema = CLIENT.get("/openapi.json").json()
    responses = schema["paths"][PATH]["get"]["responses"]

    for status_code in ("401", "403", "404", "409", "503"):
        assert responses[status_code]["description"]
        assert responses[status_code]["content"]["application/json"]["schema"]["$ref"].endswith(
            "RuntimeErrorEnvelope"
        )
    assert set(schema["components"]["schemas"]["RuntimeError"]["properties"]["code"]["enum"]) == {
        "service_authentication_invalid",
        "service_action_forbidden",
        "tenant_not_found",
        "tenant_suspended",
        "ssf_plugin_inactive",
        "ssf_tenant_not_ready",
        "runtime_configuration_unavailable",
    }


def test_openapi_documents_required_v1_headers_and_success_contract() -> None:
    schema = CLIENT.get("/openapi.json").json()
    operation = schema["paths"][PATH]["get"]
    headers = {
        parameter["name"]: parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "header"
    }

    for header_name in (
        "authorization",
        "x-studio-tenant-id",
        "x-correlation-id",
    ):
        assert headers[header_name]["required"] is True
        assert headers[header_name]["schema"] == {"type": "string"}

    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success_schema["$ref"].endswith("RuntimeConfigurationResponse")
    response_definition = schema["components"]["schemas"]["RuntimeConfigurationResponse"]
    assert {"configurationRevision", "authorizationRevision", "localization"} <= set(
        response_definition["properties"]
    )
    branding_definition = schema["components"]["schemas"]["BrandingResponse"]
    logo_schema = branding_definition["properties"]["logo"]
    assert {item["$ref"] for item in logo_schema["anyOf"] if "$ref" in item} == {
        "#/components/schemas/BrandingAssetResponse"
    }
    asset_definition = schema["components"]["schemas"]["BrandingAssetResponse"]
    assert {"url", "alternativeText"} <= set(asset_definition["properties"])
