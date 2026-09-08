"""Contract-faithful Studio Runtime Configuration V1 mock."""

import hashlib
import json
from copy import deepcopy
from typing import Any, Literal

from fastapi import FastAPI, Header, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="Studio Runtime Configuration Mock")

_CONTRACT_VERSION = "1.0"
_AUTHORIZED_TOKEN = "Bearer studio-mock-authorized-token"
_UNAUTHORIZED_TOKEN = "Bearer studio-mock-unauthorized-token"
_UNAVAILABLE_MESSAGE = "Runtime configuration is unavailable."


RuntimeErrorCode = Literal[
    "service_authentication_invalid",
    "service_action_forbidden",
    "tenant_not_found",
    "tenant_suspended",
    "ssf_plugin_inactive",
    "ssf_tenant_not_ready",
    "runtime_configuration_unavailable",
]


class RuntimeError(BaseModel):
    """The nested error object defined by the Studio V1 contract."""

    code: RuntimeErrorCode
    message: str
    retryable: bool
    correlation_id: str | None = Field(alias="correlationId")

    model_config = ConfigDict(populate_by_name=True)


class RuntimeErrorEnvelope(BaseModel):
    """The Studio V1 error envelope returned for every non-success response."""

    contract_version: str = Field(alias="contractVersion")
    error: RuntimeError

    model_config = ConfigDict(populate_by_name=True)


class TenantResponse(BaseModel):
    """The tenant section of a V1 runtime configuration."""

    id: str
    display_name: str = Field(alias="displayName")
    time_zone: str = Field(alias="timeZone")

    model_config = ConfigDict(populate_by_name=True)


class BrandingAssetResponse(BaseModel):
    """An optional logo or icon asset in a V1 runtime configuration."""

    url: str
    alternative_text: str = Field(alias="alternativeText")

    model_config = ConfigDict(populate_by_name=True)


class BrandingResponse(BaseModel):
    """The branding section of a V1 runtime configuration."""

    logo: BrandingAssetResponse | None
    icon: BrandingAssetResponse | None


class LocaleResponse(BaseModel):
    """A localized V1 runtime configuration entry."""

    locale: str
    authenticated_home_explanation_html: str = Field(alias="authenticatedHomeExplanationHtml")
    guest_explanation_html: str = Field(alias="guestExplanationHtml")
    conversation_content_storage_question_html: str | None = Field(
        alias="conversationContentStorageQuestionHtml"
    )

    model_config = ConfigDict(populate_by_name=True)


class LocalizationResponse(BaseModel):
    """The localization section of a V1 runtime configuration."""

    default_locale: str = Field(alias="defaultLocale")
    locales: list[LocaleResponse]

    model_config = ConfigDict(populate_by_name=True)


class ConversationContentStorageResponse(BaseModel):
    """The conversation-content storage policy section."""

    mode: str


class RuntimeConfigurationResponse(BaseModel):
    """The successful Studio Runtime Configuration V1 response."""

    contract_version: str = Field(alias="contractVersion")
    configuration_revision: str = Field(alias="configurationRevision")
    authorization_revision: str = Field(alias="authorizationRevision")
    tenant: TenantResponse
    branding: BrandingResponse
    localization: LocalizationResponse
    conversation_content_storage: ConversationContentStorageResponse = Field(
        alias="conversationContentStorage"
    )

    model_config = ConfigDict(populate_by_name=True)


_ERROR_RESPONSES = {
    401: {
        "model": RuntimeErrorEnvelope,
        "description": "Service authentication failed.",
    },
    403: {
        "model": RuntimeErrorEnvelope,
        "description": "Service permission is missing.",
    },
    404: {
        "model": RuntimeErrorEnvelope,
        "description": "The tenant does not exist or the selector is malformed.",
    },
    409: {
        "model": RuntimeErrorEnvelope,
        "description": "The tenant or SSF plugin is not ready.",
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
            "defaultLocale": "de-DE",
            "locales": [
                {
                    "locale": "de-DE",
                    "authenticatedHomeExplanationHtml": "<p>Test environment</p>",
                    "guestExplanationHtml": "<p>Guest test environment</p>",
                    "conversationContentStorageQuestionHtml": None,
                }
            ],
        },
        "conversationContentStorage": {"mode": "disabled"},
    },
}


def _revision(payload: dict[str, Any]) -> str:
    """Return the V1 SHA-256 revision for a canonical JSON payload."""
    canonical_json = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return f"sha256:{hashlib.sha256(canonical_json).hexdigest()}"


def _configuration_for(tenant_id: str) -> dict[str, Any]:
    """Return the effective configuration and its two deterministic revisions."""
    configuration = deepcopy(_TENANT_CONFIGURATION_TEMPLATES[tenant_id])
    authorization = {
        "tenantId": tenant_id,
        "permissions": ["ssf.runtime-configuration.read"],
    }
    configuration["authorizationRevision"] = _revision(authorization)
    configuration["configurationRevision"] = _revision(configuration)
    return configuration


def _error_response(
    status_code: int,
    code: RuntimeErrorCode,
    correlation_id: str | None,
    retryable: bool,
    message: str = _UNAVAILABLE_MESSAGE,
) -> JSONResponse:
    """Return the stable Studio V1 error envelope without tenant content."""
    return JSONResponse(
        status_code=status_code,
        content={
            "contractVersion": _CONTRACT_VERSION,
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "correlationId": correlation_id,
            },
        },
    )


@app.get(
    "/internal/plugins/ssf/v1/runtime-configuration",
    response_model=RuntimeConfigurationResponse,
    responses=_ERROR_RESPONSES,
)
def runtime_configuration(
    request: Request,
    authorization: str | None = Header(default=None),
    x_studio_tenant_id: str | None = Header(default=None),
    x_correlation_id: str | None = Header(default=None),
    x_studio_instance_id: str | None = Header(default=None, include_in_schema=False),
    x_tenant_id: str | None = Header(default=None, include_in_schema=False),
    x_mock_scenario: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Return deterministic V1 data for authorized Studio service callers."""
    if authorization not in {_AUTHORIZED_TOKEN, _UNAUTHORIZED_TOKEN}:
        return _error_response(
            401, "service_authentication_invalid", x_correlation_id or "unavailable", False
        )
    if authorization == _UNAUTHORIZED_TOKEN:
        return _error_response(
            403, "service_action_forbidden", x_correlation_id or "unavailable", False
        )
    if (
        not x_studio_tenant_id
        or not x_correlation_id
        or x_studio_instance_id is not None
        or x_tenant_id is not None
        or request.url.query
    ):
        return _error_response(404, "tenant_not_found", x_correlation_id or "unavailable", False)
    scenario_errors: dict[str, tuple[int, RuntimeErrorCode, bool]] = {
        "suspended": (409, "tenant_suspended", False),
        "plugin-inactive": (409, "ssf_plugin_inactive", False),
        "tenant-not-ready": (409, "ssf_tenant_not_ready", True),
    }
    if x_mock_scenario in scenario_errors:
        status_code, code, retryable = scenario_errors[x_mock_scenario]
        return _error_response(status_code, code, x_correlation_id, retryable)
    if x_mock_scenario == "unavailable":
        return _error_response(503, "runtime_configuration_unavailable", x_correlation_id, True)
    if x_studio_tenant_id not in _TENANT_CONFIGURATION_TEMPLATES:
        return _error_response(404, "tenant_not_found", x_correlation_id, False)
    return _configuration_for(x_studio_tenant_id)


def _custom_openapi() -> dict[str, Any]:
    """Document V1-required headers while preserving custom error envelopes."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    parameters = schema["paths"]["/internal/plugins/ssf/v1/runtime-configuration"]["get"][
        "parameters"
    ]
    for parameter in parameters:
        if parameter["in"] == "header" and parameter["name"] in {
            "authorization",
            "x-studio-tenant-id",
            "x-correlation-id",
        }:
            parameter["required"] = True
            parameter["schema"] = {"type": "string"}
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi
