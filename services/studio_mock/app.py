"""Contract-faithful local implementation of Studio Runtime Configuration V1."""

import hashlib
import json
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="Studio Runtime Configuration Mock")

_SERVICE_TOKEN = "Bearer studio-mock-service-token"
_UNAVAILABLE_MESSAGE = "The requested tenant is unavailable."
_CONTRACT_VERSION = "1.0"


class RuntimeError(BaseModel):
    """The nested error object defined by the Studio V1 contract."""

    code: str
    message: str
    retryable: bool
    correlation_id: str | None = Field(alias="correlationId")

    model_config = ConfigDict(populate_by_name=True)


class RuntimeErrorEnvelope(BaseModel):
    """The Studio V1 error envelope returned for every non-success response."""

    contract_version: str = Field(alias="contractVersion")
    error: RuntimeError

    model_config = ConfigDict(populate_by_name=True)


_ERROR_RESPONSES = {
    401: {
        "model": RuntimeErrorEnvelope,
        "description": "Service authentication is missing.",
    },
    403: {
        "model": RuntimeErrorEnvelope,
        "description": "Service authentication is invalid.",
    },
    404: {
        "model": RuntimeErrorEnvelope,
        "description": "The requested tenant does not exist.",
    },
    409: {
        "model": RuntimeErrorEnvelope,
        "description": "The requested tenant is not ready.",
    },
    503: {
        "model": RuntimeErrorEnvelope,
        "description": "Runtime configuration is unavailable.",
    },
}

_TENANT_CONFIGURATION_TEMPLATES: dict[str, dict[str, Any]] = {
    "tenant-kassel": {
        "contractVersion": _CONTRACT_VERSION,
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
    },
    "tenant-fulda": {
        "contractVersion": _CONTRACT_VERSION,
        "tenant": {
            "id": "tenant-fulda",
            "displayName": "Fulda Test Municipality",
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
                    "conversationContentStorageQuestionHtml": None,
                }
            ],
        },
        "conversationContentStorage": {"mode": "disabled"},
    },
}


def _configuration_for(tenant_id: str) -> dict[str, Any]:
    """Return a configuration with its revision derived from canonical payload JSON."""
    configuration = deepcopy(_TENANT_CONFIGURATION_TEMPLATES[tenant_id])
    canonical_json = json.dumps(
        configuration, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    configuration["configurationRevision"] = (
        f"sha256:{hashlib.sha256(canonical_json).hexdigest()}"
    )
    return configuration


def _error_response(
    status_code: int,
    code: str,
    correlation_id: str | None,
    retryable: bool,
) -> JSONResponse:
    """Return the stable Studio V1 error envelope without tenant content."""
    return JSONResponse(
        status_code=status_code,
        content={
            "contractVersion": _CONTRACT_VERSION,
            "error": {
                "code": code,
                "message": _UNAVAILABLE_MESSAGE,
                "retryable": retryable,
                "correlationId": correlation_id,
            },
        },
    )


@app.get(
    "/internal/plugins/ssf/v1/runtime-configuration",
    response_model=None,
    responses=_ERROR_RESPONSES,
)
def runtime_configuration(
    authorization: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_correlation_id: str | None = Header(default=None),
    x_mock_scenario: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Return deterministic Runtime Configuration V1 data for local integration tests."""
    if authorization is None:
        return _error_response(401, "SERVICE_UNAUTHENTICATED", x_correlation_id, False)
    if authorization != _SERVICE_TOKEN:
        return _error_response(403, "SERVICE_FORBIDDEN", x_correlation_id, False)
    if x_mock_scenario == "not-ready":
        return _error_response(409, "TENANT_NOT_READY", x_correlation_id, False)
    if x_mock_scenario == "unavailable":
        return _error_response(
            503, "RUNTIME_CONFIGURATION_UNAVAILABLE", x_correlation_id, True
        )
    if x_tenant_id not in _TENANT_CONFIGURATION_TEMPLATES:
        return _error_response(404, "TENANT_NOT_FOUND", x_correlation_id, False)
    return _configuration_for(x_tenant_id)
