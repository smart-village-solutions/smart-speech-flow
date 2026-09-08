"""Contract tests for the local Studio Runtime Configuration V1 mock."""

import hashlib
import json
import re

from fastapi.testclient import TestClient

from services.studio_mock.app import app

CLIENT = TestClient(app)
PATH = "/internal/plugins/ssf/v1/runtime-configuration"


def _headers(tenant_id: str = "tenant-kassel", **additional: str) -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant_id,
        "X-Correlation-Id": "test-correlation-id",
        **additional,
    }


def test_returns_ask_policy_configuration_for_first_test_tenant() -> None:
    response = CLIENT.get(PATH, headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "contractVersion": "1.0",
        "configurationRevision": payload["configurationRevision"],
        "tenant": {
            "id": "tenant-kassel",
            "displayName": "Kassel Test Municipality",
            "timeZone": "Europe/Berlin",
        },
        "branding": {"logo": None, "icon": None},
        "localization": {
            "defaultLanguage": "de-DE",
            "languages": [
                {
                    "language": "de-DE",
                    "authenticatedHomeExplanationHtml": "<p>Test environment</p>",
                    "guestExplanationHtml": "<p>Guest test environment</p>",
                    "conversationContentStorageQuestionHtml": "<p>Store this conversation?</p>",
                }
            ],
        },
        "conversationContentStorage": {"mode": "ask"},
    }
    revision = payload.pop("configurationRevision")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", revision)
    expected_revision = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert revision == f"sha256:{expected_revision}"


def test_returns_disabled_policy_for_second_test_tenant() -> None:
    response = CLIENT.get(PATH, headers=_headers("tenant-fulda"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant"]["id"] == "tenant-fulda"
    assert payload["conversationContentStorage"] == {"mode": "disabled"}
    assert payload["localization"]["languages"][0]["conversationContentStorageQuestionHtml"] is None


def test_returns_configuration_without_authorization() -> None:
    response = CLIENT.get(
        PATH,
        headers={
            "X-Tenant-Id": "tenant-kassel",
            "X-Correlation-Id": "test-correlation-id",
        },
    )

    assert response.status_code == 200
    assert response.json()["tenant"]["id"] == "tenant-kassel"


def test_returns_configuration_for_browser_query_parameter() -> None:
    response = CLIENT.get(PATH, params={"tenantId": "tenant-fulda"})

    assert response.status_code == 200
    assert response.json()["tenant"]["id"] == "tenant-fulda"


def test_rejects_conflicting_header_and_browser_query_tenant_ids() -> None:
    response = CLIENT.get(PATH, headers=_headers(), params={"tenantId": "tenant-fulda"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TENANT_ID_CONFLICT"


def test_rejects_empty_header_that_conflicts_with_browser_query_tenant_id() -> None:
    response = CLIENT.get(
        PATH,
        headers={"X-Tenant-Id": ""},
        params={"tenantId": "tenant-fulda"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TENANT_ID_CONFLICT"


def test_returns_not_found_for_unknown_tenant() -> None:
    response = CLIENT.get(PATH, headers=_headers("tenant-unknown"))

    assert response.status_code == 404
    assert response.json() == {
        "contractVersion": "1.0",
        "error": {
            "code": "TENANT_NOT_FOUND",
            "message": "The requested tenant is unavailable.",
            "retryable": False,
            "correlationId": "test-correlation-id",
        },
    }


def test_returns_documented_mock_failure_envelopes() -> None:
    for scenario, status_code, code, retryable in [
        ("not-ready", 409, "TENANT_NOT_READY", False),
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

    for status_code in ("400", "404", "409", "503"):
        assert responses[status_code]["description"]
        assert responses[status_code]["content"]["application/json"]["schema"]["$ref"].endswith(
            "RuntimeErrorEnvelope"
        )
