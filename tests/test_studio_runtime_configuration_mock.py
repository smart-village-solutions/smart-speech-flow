"""Contract tests for the Studio mock: runtime configuration V1 and v2, installation content."""

import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from services.studio_mock import fixtures
from services.studio_mock.app import app

CLIENT = TestClient(app)
PATH = "/internal/plugins/ssf/v1/runtime-configuration"
DIRECTORY_PATH = "/internal/plugins/ssf/v1/admin-login-tenants"
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
        headers={
            "Authorization": AUTHORIZED_TOKEN,
            "X-Correlation-Id": "test-correlation-id",
        },
    )
    missing_correlation = CLIENT.get(
        PATH,
        headers={
            "Authorization": AUTHORIZED_TOKEN,
            "X-Studio-Tenant-Id": "tenant-kassel",
        },
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
            "StudioV1ErrorEnvelope"
        )
    assert set(schema["paths"][PATH]["get"]["x-error-codes"]) == {
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
    assert success_schema["$ref"].endswith("/RuntimeConfiguration")
    response_definition = schema["components"]["schemas"]["RuntimeConfiguration"]
    assert {"configurationRevision", "authorizationRevision", "localization"} <= set(
        response_definition["properties"]
    )
    branding_definition = schema["components"]["schemas"]["Branding"]
    logo_schema = branding_definition["properties"]["logo"]
    assert {item["$ref"] for item in logo_schema["anyOf"] if "$ref" in item} == {
        "#/components/schemas/MediaAsset"
    }
    asset_definition = schema["components"]["schemas"]["MediaAsset"]
    assert {"url", "alternativeText"} <= set(asset_definition["properties"])


def _directory_headers(**additional: str) -> dict[str, str]:
    return {
        "Authorization": AUTHORIZED_TOKEN,
        "X-Correlation-Id": "test-correlation-id",
        **additional,
    }


def test_returns_deterministic_v1_login_directory_for_authorized_service() -> None:
    first = CLIENT.get(DIRECTORY_PATH, headers=_directory_headers())
    second = CLIENT.get(DIRECTORY_PATH, headers=_directory_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    payload = first.json()
    assert payload == {
        "contractVersion": "1.0",
        "directoryRevision": payload["directoryRevision"],
        "tenants": [
            {
                "id": "tenant-kassel",
                "displayName": "Stadt Kassel",
                "realm": "kassel-ssf-2025",
                "studioUrl": "https://smartcity.dialog.kassel.de/",
            },
            {
                "id": "tenant-fulda",
                "displayName": "Stadt Fulda",
                "realm": "fulda-ssf-2025",
                "studioUrl": "https://fulda.dialog.kassel.de/",
            },
        ],
    }
    revision = payload.pop("directoryRevision")
    expected_revision = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert revision == f"sha256:{expected_revision}"


def test_login_directory_requires_authorization_and_correlation_id() -> None:
    missing_token = CLIENT.get(DIRECTORY_PATH, headers={"X-Correlation-Id": "test-correlation-id"})
    missing_correlation = CLIENT.get(DIRECTORY_PATH, headers={"Authorization": AUTHORIZED_TOKEN})

    assert missing_token.status_code == 401
    assert missing_token.json()["error"]["code"] == "service_authentication_invalid"
    assert missing_correlation.status_code != 200


def test_login_directory_rejects_tenant_selectors_and_supports_service_scenarios() -> None:
    selector_responses = [
        CLIENT.get(
            DIRECTORY_PATH,
            headers=_directory_headers(**{"X-Studio-Tenant-Id": "tenant-kassel"}),
        ),
        CLIENT.get(
            DIRECTORY_PATH,
            headers=_directory_headers(**{"X-Studio-Instance-Id": "tenant-kassel"}),
        ),
        CLIENT.get(
            DIRECTORY_PATH,
            headers=_directory_headers(**{"X-Tenant-Id": "tenant-kassel"}),
        ),
        CLIENT.get(
            DIRECTORY_PATH,
            params={"tenantId": "tenant-kassel"},
            headers=_directory_headers(),
        ),
    ]
    forbidden = CLIENT.get(
        DIRECTORY_PATH, headers=_directory_headers(Authorization=UNAUTHORIZED_TOKEN)
    )
    unavailable = CLIENT.get(
        DIRECTORY_PATH, headers=_directory_headers(**{"X-Mock-Scenario": "unavailable"})
    )

    assert all(response.status_code != 200 for response in selector_responses)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "service_action_forbidden"
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "admin_login_directory_unavailable"


def test_openapi_documents_login_directory_contract_and_required_headers() -> None:
    schema = CLIENT.get("/openapi.json").json()
    operation = schema["paths"][DIRECTORY_PATH]["get"]
    headers = {
        parameter["name"]: parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "header"
    }

    for header_name in ("authorization", "x-correlation-id"):
        assert headers[header_name]["required"] is True
        assert headers[header_name]["schema"] == {"type": "string"}
    assert "x-studio-tenant-id" not in headers
    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success_schema["$ref"].endswith("/StudioLoginDirectory")
    response_definition = schema["components"]["schemas"]["StudioLoginDirectory"]
    assert {"contractVersion", "directoryRevision", "tenants"} <= set(
        response_definition["properties"]
    )


V2_PATH = "/internal/plugins/ssf/v2/runtime-configuration"
INSTALLATION_PATH = "/internal/plugins/ssf/v2/installation-content"
RUNTIME_MESSAGE = "Runtime configuration is unavailable."
INSTALLATION_MESSAGE = "Installation content is unavailable."


def _v2_error(
    code: str, retryable: bool, message: str, correlation: str = "test-correlation-id"
) -> dict:
    return {
        "contractVersion": "2.0",
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "correlationId": correlation,
        },
    }


@pytest.mark.parametrize("tenant_id", fixtures.RUNTIME_V2_TENANTS)
def test_v2_runtime_serves_each_fixture_with_its_revision(tenant_id: str) -> None:
    response = CLIENT.get(V2_PATH, headers=_headers(tenant_id))

    assert response.status_code == 200
    assert response.json() == fixtures.runtime_configuration_v2(tenant_id, None)
    assert response.json()["contractVersion"] == "2.0"
    assert "authorizationRevision" not in response.json()


def test_v2_runtime_applies_the_scenario_per_request() -> None:
    disabled = CLIENT.get(V2_PATH, headers=_headers(**{"X-Mock-Scenario": "storage-disabled"}))
    plain = CLIENT.get(V2_PATH, headers=_headers())
    invalid = CLIENT.get(V2_PATH, headers=_headers(**{"X-Mock-Scenario": "invalid-content"}))

    assert disabled.json() == fixtures.runtime_configuration_v2("tenant-kassel", "storage-disabled")
    assert disabled.json()["conversationContentStorage"] == {
        "mode": "disabled",
        "retentionHours": None,
    }
    assert plain.json()["conversationContentStorage"] == {"mode": "ask", "retentionHours": 4320}
    assert invalid.json() == fixtures.runtime_configuration_v2("tenant-kassel", "invalid-content")


@pytest.mark.parametrize(
    ("headers", "status", "code", "retryable"),
    [
        (_headers(Authorization="Bearer unknown"), 401, "service_authentication_invalid", False),
        (_headers(Authorization=UNAUTHORIZED_TOKEN), 403, "service_action_forbidden", False),
        (_headers("tenant-unknown"), 404, "tenant_not_found", False),
        (_headers(**{"X-Tenant-Id": "tenant-kassel"}), 404, "tenant_not_found", False),
        (_headers(**{"X-Studio-Instance-Id": "tenant-kassel"}), 404, "tenant_not_found", False),
        (_headers(**{"X-Mock-Scenario": "suspended"}), 409, "tenant_suspended", False),
        (_headers(**{"X-Mock-Scenario": "plugin-inactive"}), 409, "ssf_plugin_inactive", False),
        (_headers(**{"X-Mock-Scenario": "tenant-not-ready"}), 409, "ssf_tenant_not_ready", True),
        (
            _headers(**{"X-Mock-Scenario": "unavailable"}),
            503,
            "runtime_configuration_unavailable",
            True,
        ),
    ],
)
def test_v2_runtime_errors_use_the_v2_envelope(
    headers: dict[str, str], status: int, code: str, retryable: bool
) -> None:
    response = CLIENT.get(V2_PATH, headers=headers)

    assert response.status_code == status
    assert response.json() == _v2_error(code, retryable, RUNTIME_MESSAGE)


def test_v2_runtime_rejects_missing_correlation_and_query_selectors() -> None:
    missing_correlation = CLIENT.get(
        V2_PATH,
        headers={"Authorization": AUTHORIZED_TOKEN, "X-Studio-Tenant-Id": "tenant-kassel"},
    )
    query = CLIENT.get(V2_PATH, params={"tenantId": "tenant-kassel"}, headers=_headers())

    assert missing_correlation.status_code == 404
    assert missing_correlation.json() == _v2_error(
        "tenant_not_found", False, RUNTIME_MESSAGE, "unavailable"
    )
    assert query.json() == _v2_error("tenant_not_found", False, RUNTIME_MESSAGE)


@pytest.mark.parametrize("tenant_id", fixtures.RUNTIME_V2_TENANTS)
@pytest.mark.parametrize("scenario", ["storage-disabled", "invalid-content"])
def test_v2_content_scenarios_serve_every_tenant(tenant_id: str, scenario: str) -> None:
    response = CLIENT.get(V2_PATH, headers=_headers(tenant_id, **{"X-Mock-Scenario": scenario}))

    assert response.status_code == 200
    assert response.json() == fixtures.runtime_configuration_v2(tenant_id, scenario)


def test_v1_runtime_still_answers_with_v1_envelopes() -> None:
    response = CLIENT.get(PATH, headers=_headers(**{"X-Mock-Scenario": "suspended"}))

    _assert_error(response, 409, "tenant_suspended", False)


def _installation_headers(**additional: str) -> dict[str, str]:
    return {
        "Authorization": AUTHORIZED_TOKEN,
        "X-Correlation-Id": "test-correlation-id",
        **additional,
    }


def test_installation_content_serves_the_fixture_with_its_revision() -> None:
    plain = CLIENT.get(INSTALLATION_PATH, headers=_installation_headers())
    invalid = CLIENT.get(
        INSTALLATION_PATH, headers=_installation_headers(**{"X-Mock-Scenario": "invalid-content"})
    )

    assert plain.status_code == 200
    assert plain.json() == fixtures.installation_content_v2(None)
    assert invalid.json() == fixtures.installation_content_v2("invalid-content")


@pytest.mark.parametrize(
    ("headers", "status", "code", "retryable"),
    [
        (
            _installation_headers(Authorization="Bearer unknown"),
            401,
            "service_authentication_invalid",
            False,
        ),
        (
            _installation_headers(Authorization=UNAUTHORIZED_TOKEN),
            403,
            "service_action_forbidden",
            False,
        ),
        (
            _installation_headers(**{"X-Studio-Tenant-Id": "tenant-kassel"}),
            400,
            "malformed_request",
            False,
        ),
        (
            _installation_headers(**{"X-Studio-Instance-Id": "tenant-kassel"}),
            400,
            "malformed_request",
            False,
        ),
        (
            _installation_headers(**{"X-Tenant-Id": "tenant-kassel"}),
            400,
            "malformed_request",
            False,
        ),
        (
            _installation_headers(**{"X-Mock-Scenario": "unavailable"}),
            503,
            "installation_content_unavailable",
            True,
        ),
    ],
)
def test_installation_content_errors_use_the_v2_envelope(
    headers: dict[str, str], status: int, code: str, retryable: bool
) -> None:
    response = CLIENT.get(INSTALLATION_PATH, headers=headers)

    assert response.status_code == status
    assert response.json() == _v2_error(code, retryable, INSTALLATION_MESSAGE)


def test_installation_content_rejects_missing_correlation_and_query_selectors() -> None:
    missing_correlation = CLIENT.get(INSTALLATION_PATH, headers={"Authorization": AUTHORIZED_TOKEN})
    query = CLIENT.get(
        INSTALLATION_PATH, params={"tenantId": "tenant-kassel"}, headers=_installation_headers()
    )

    assert missing_correlation.status_code == 400
    assert missing_correlation.json() == _v2_error(
        "malformed_request", False, INSTALLATION_MESSAGE, "unavailable"
    )
    assert query.status_code == 400
    assert query.json() == _v2_error("malformed_request", False, INSTALLATION_MESSAGE)


def test_openapi_documents_the_v2_endpoints() -> None:
    schema = CLIENT.get("/openapi.json").json()
    expected = {
        V2_PATH: (
            {"authorization", "x-studio-tenant-id", "x-correlation-id"},
            ("401", "403", "404", "409", "503"),
        ),
        INSTALLATION_PATH: (
            {"authorization", "x-correlation-id"},
            ("400", "401", "403", "503"),
        ),
    }

    for path, (required, statuses) in expected.items():
        operation = schema["paths"][path]["get"]
        headers = {p["name"]: p for p in operation["parameters"] if p["in"] == "header"}
        assert {name for name, p in headers.items() if p.get("required")} == required
        for name in required:
            assert headers[name]["schema"] == {"type": "string"}
        for status in statuses:
            content = operation["responses"][status]["content"]["application/json"]
            assert content["schema"]["$ref"].endswith("StudioV1ErrorEnvelope")
        assert operation["x-error-codes"]
    installation_headers = {
        p["name"] for p in schema["paths"][INSTALLATION_PATH]["get"]["parameters"]
    }
    assert "x-studio-tenant-id" not in installation_headers
    assert set(schema["paths"][INSTALLATION_PATH]["get"]["x-error-codes"]) == {
        "service_authentication_invalid",
        "service_action_forbidden",
        "malformed_request",
        "installation_content_unavailable",
    }
