"""Contract tests for the Studio Runtime Configuration V1 mock."""

import hashlib
import json
import re

from fastapi.testclient import TestClient

from services.studio_mock.app import app

CLIENT = TestClient(app)
PATH = "/internal/plugins/ssf/v1/runtime-configuration"
AUTHORIZED_TOKEN = "Bearer studio-mock-authorized-token"
UNAUTHORIZED_TOKEN = "Bearer studio-mock-unauthorized-token"


def _headers(
    studio_instance_id: str = "tenant-kassel", **additional: str
) -> dict[str, str]:
    return {
        "Authorization": AUTHORIZED_TOKEN,
        "X-Studio-Instance-Id": studio_instance_id,
        "X-Correlation-Id": "test-correlation-id",
        **additional,
    }


def test_returns_v1_configuration_for_authorized_studio_instance() -> None:
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


def test_returns_disabled_policy_for_second_studio_instance() -> None:
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
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "SERVICE_UNAUTHENTICATED"


def test_rejects_service_token_without_runtime_configuration_permission() -> None:
    response = CLIENT.get(PATH, headers=_headers(Authorization=UNAUTHORIZED_TOKEN))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SERVICE_FORBIDDEN"


def test_requires_studio_instance_and_correlation_headers() -> None:
    missing_instance = CLIENT.get(
        PATH,
        headers={"Authorization": AUTHORIZED_TOKEN, "X-Correlation-Id": "test-correlation-id"},
    )
    missing_correlation = CLIENT.get(
        PATH,
        headers={"Authorization": AUTHORIZED_TOKEN, "X-Studio-Instance-Id": "tenant-kassel"},
    )

    assert missing_instance.status_code == 400
    assert missing_instance.json()["error"]["code"] == "STUDIO_INSTANCE_ID_REQUIRED"
    assert missing_correlation.status_code == 400
    assert missing_correlation.json()["error"]["code"] == "CORRELATION_ID_REQUIRED"


def test_does_not_use_browser_tenant_query_parameter_for_identity() -> None:
    response = CLIENT.get(PATH, params={"tenantId": "tenant-kassel"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SERVICE_UNAUTHENTICATED"


def test_returns_not_found_for_unknown_studio_instance() -> None:
    response = CLIENT.get(PATH, headers=_headers("tenant-unknown"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TENANT_NOT_FOUND"


def test_returns_documented_mock_failure_envelopes() -> None:
    for scenario, status_code, code, retryable in [
        ("authorization-pending", 409, "AUTHORIZATION_PROJECTION_PENDING", True),
        ("unavailable", 503, "RUNTIME_CONFIGURATION_UNAVAILABLE", True),
    ]:
        response = CLIENT.get(PATH, headers=_headers(**{"X-Mock-Scenario": scenario}))

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


def test_openapi_documents_every_runtime_configuration_error() -> None:
    responses = CLIENT.get("/openapi.json").json()["paths"][PATH]["get"]["responses"]

    for status_code in ("400", "401", "403", "404", "409", "503"):
        assert responses[status_code]["description"]
        assert responses[status_code]["content"]["application/json"]["schema"]["$ref"].endswith(
            "RuntimeErrorEnvelope"
        )
