"""Contract tests for the Studio mock: runtime configuration v2, installation content, login directory."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from services.studio_mock import contract_fixtures
from services.studio_mock.app import app

CLIENT = TestClient(app)
V1_RUNTIME_PATH = "/internal/plugins/ssf/v1/runtime-configuration"
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


@pytest.mark.parametrize("tenant_id", contract_fixtures.RUNTIME_V2_TENANTS)
def test_v2_runtime_serves_each_fixture_with_its_revision(tenant_id: str) -> None:
    response = CLIENT.get(V2_PATH, headers=_headers(tenant_id))

    assert response.status_code == 200
    assert response.json() == contract_fixtures.runtime_configuration_v2(tenant_id, None)
    assert response.json()["contractVersion"] == "2.0"
    assert "authorizationRevision" not in response.json()


def test_v2_runtime_applies_the_scenario_per_request() -> None:
    disabled = CLIENT.get(V2_PATH, headers=_headers(**{"X-Mock-Scenario": "storage-disabled"}))
    plain = CLIENT.get(V2_PATH, headers=_headers())
    invalid = CLIENT.get(V2_PATH, headers=_headers(**{"X-Mock-Scenario": "invalid-content"}))

    assert disabled.json() == contract_fixtures.runtime_configuration_v2(
        "tenant-kassel", "storage-disabled"
    )
    assert disabled.json()["conversationContentStorage"] == {
        "mode": "disabled",
        "retentionHours": None,
    }
    assert plain.json()["conversationContentStorage"] == {"mode": "ask", "retentionHours": 4320}
    assert invalid.json() == contract_fixtures.runtime_configuration_v2(
        "tenant-kassel", "invalid-content"
    )


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


@pytest.mark.parametrize("tenant_id", contract_fixtures.RUNTIME_V2_TENANTS)
@pytest.mark.parametrize("scenario", ["storage-disabled", "invalid-content"])
def test_v2_content_scenarios_serve_every_tenant(tenant_id: str, scenario: str) -> None:
    response = CLIENT.get(V2_PATH, headers=_headers(tenant_id, **{"X-Mock-Scenario": scenario}))

    assert response.status_code == 200
    assert response.json() == contract_fixtures.runtime_configuration_v2(tenant_id, scenario)


def test_the_v1_runtime_endpoint_is_gone() -> None:
    response = CLIENT.get(V1_RUNTIME_PATH, headers=_headers())

    assert response.status_code == 404
    assert V1_RUNTIME_PATH not in CLIENT.get("/openapi.json").json()["paths"]


def test_v2_runtime_rejects_a_missing_tenant_header() -> None:
    response = CLIENT.get(
        V2_PATH,
        headers={"Authorization": AUTHORIZED_TOKEN, "X-Correlation-Id": "test-correlation-id"},
    )

    assert response.status_code == 404
    assert response.json() == _v2_error("tenant_not_found", False, RUNTIME_MESSAGE)


def test_openapi_lists_every_runtime_error_code() -> None:
    schema = CLIENT.get("/openapi.json").json()

    assert set(schema["paths"][V2_PATH]["get"]["x-error-codes"]) == {
        "service_authentication_invalid",
        "service_action_forbidden",
        "tenant_not_found",
        "tenant_suspended",
        "ssf_plugin_inactive",
        "ssf_tenant_not_ready",
        "runtime_configuration_unavailable",
    }


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
    assert plain.json() == contract_fixtures.installation_content_v2(None)
    assert invalid.json() == contract_fixtures.installation_content_v2("invalid-content")


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
