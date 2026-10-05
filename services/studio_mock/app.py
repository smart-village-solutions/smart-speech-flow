"""Contract-faithful Studio Runtime Configuration V1 mock."""

import hashlib
import json
from copy import deepcopy
from typing import Any, Literal, get_args

from fastapi import FastAPI, Header, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from services.api_gateway.studio_login_directory_client import StudioLoginDirectory
from services.api_gateway.studio_runtime_client import RuntimeConfiguration
from services.api_gateway.studio_v1 import StudioV1ErrorEnvelope

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

DirectoryErrorCode = Literal[
    "service_authentication_invalid",
    "service_action_forbidden",
    "tenant_not_found",
    "admin_login_directory_unavailable",
]


_ERROR_RESPONSES = {
    401: {
        "model": StudioV1ErrorEnvelope,
        "description": "Service authentication failed.",
    },
    403: {
        "model": StudioV1ErrorEnvelope,
        "description": "Service permission is missing.",
    },
    404: {
        "model": StudioV1ErrorEnvelope,
        "description": "The tenant does not exist or the selector is malformed.",
    },
    409: {
        "model": StudioV1ErrorEnvelope,
        "description": "The tenant or SSF plugin is not ready.",
    },
    503: {
        "model": StudioV1ErrorEnvelope,
        "description": "Runtime configuration is unavailable.",
    },
}

_DIRECTORY_ERROR_RESPONSES = {
    401: {
        "model": StudioV1ErrorEnvelope,
        "description": "Service authentication failed.",
    },
    403: {
        "model": StudioV1ErrorEnvelope,
        "description": "Service permission is missing.",
    },
    404: {"model": StudioV1ErrorEnvelope, "description": "The request is malformed."},
    503: {
        "model": StudioV1ErrorEnvelope,
        "description": "Login directory is unavailable.",
    },
}

TENANT_CONFIGURATION_TEMPLATES: dict[str, dict[str, Any]] = {
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

_LOGIN_DIRECTORY_TENANTS = [
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
]


def _revision(payload: dict[str, Any]) -> str:
    """Return the V1 SHA-256 revision for a canonical JSON payload."""
    canonical_json = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return f"sha256:{hashlib.sha256(canonical_json).hexdigest()}"


def _configuration_for(tenant_id: str) -> dict[str, Any]:
    """Return the effective configuration and its two deterministic revisions."""
    configuration = deepcopy(TENANT_CONFIGURATION_TEMPLATES[tenant_id])
    authorization = {
        "tenantId": tenant_id,
        "permissions": ["ssf.runtime-configuration.read"],
    }
    configuration["authorizationRevision"] = _revision(authorization)
    configuration["configurationRevision"] = _revision(configuration)
    return configuration


def _login_directory() -> dict[str, Any]:
    """Return the deterministic V1 login directory for all ready tenants."""
    directory = {
        "contractVersion": _CONTRACT_VERSION,
        "tenants": deepcopy(_LOGIN_DIRECTORY_TENANTS),
    }
    directory["directoryRevision"] = _revision(directory)
    return directory


def _error_response(
    status_code: int,
    code: RuntimeErrorCode | DirectoryErrorCode,
    correlation_id: str,
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
    response_model=RuntimeConfiguration,
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
            401,
            "service_authentication_invalid",
            x_correlation_id or "unavailable",
            False,
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
    if x_studio_tenant_id not in TENANT_CONFIGURATION_TEMPLATES:
        return _error_response(404, "tenant_not_found", x_correlation_id, False)
    return _configuration_for(x_studio_tenant_id)


@app.get(
    "/internal/plugins/ssf/v1/admin-login-tenants",
    response_model=StudioLoginDirectory,
    responses=_DIRECTORY_ERROR_RESPONSES,
)
def admin_login_tenants(
    request: Request,
    authorization: str | None = Header(default=None),
    x_correlation_id: str | None = Header(default=None),
    x_studio_tenant_id: str | None = Header(default=None, include_in_schema=False),
    x_studio_instance_id: str | None = Header(default=None, include_in_schema=False),
    x_tenant_id: str | None = Header(default=None, include_in_schema=False),
    x_mock_scenario: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Return ready tenants for authorized, tenant-unbound service callers."""
    if authorization not in {_AUTHORIZED_TOKEN, _UNAUTHORIZED_TOKEN}:
        return _error_response(
            401,
            "service_authentication_invalid",
            x_correlation_id or "unavailable",
            False,
        )
    if authorization == _UNAUTHORIZED_TOKEN:
        return _error_response(
            403, "service_action_forbidden", x_correlation_id or "unavailable", False
        )
    if (
        not x_correlation_id
        or x_studio_tenant_id is not None
        or x_studio_instance_id is not None
        or x_tenant_id is not None
        or request.url.query
    ):
        return _error_response(404, "tenant_not_found", x_correlation_id or "unavailable", False)
    if x_mock_scenario == "unavailable":
        return _error_response(503, "admin_login_directory_unavailable", x_correlation_id, True)
    return _login_directory()


def _custom_openapi() -> dict[str, Any]:
    """Document V1-required headers while preserving custom error envelopes."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    required_headers_by_path = {
        "/internal/plugins/ssf/v1/runtime-configuration": {
            "authorization",
            "x-studio-tenant-id",
            "x-correlation-id",
        },
        "/internal/plugins/ssf/v1/admin-login-tenants": {
            "authorization",
            "x-correlation-id",
        },
    }
    for path, header_names in required_headers_by_path.items():
        parameters = schema["paths"][path]["get"]["parameters"]
        for parameter in parameters:
            if parameter["in"] == "header" and parameter["name"] in header_names:
                parameter["required"] = True
                parameter["schema"] = {"type": "string"}
    # The shared envelope types `code` as a string; document what this mock emits.
    emitted_codes = {
        "/internal/plugins/ssf/v1/runtime-configuration": get_args(RuntimeErrorCode),
        "/internal/plugins/ssf/v1/admin-login-tenants": get_args(DirectoryErrorCode),
    }
    for path, codes in emitted_codes.items():
        schema["paths"][path]["get"]["x-error-codes"] = sorted(codes)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi
