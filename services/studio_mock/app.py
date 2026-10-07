"""Contract-faithful Studio mock: runtime configuration v2 and installation content v2.

The login directory stays on contract v1, because Studio has no v2 directory.
"""

from dataclasses import dataclass
from typing import Any, Literal, get_args

from fastapi import Depends, FastAPI, Header, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from services.api_gateway.studio_login_directory_client import StudioLoginDirectory
from services.api_gateway.studio_v1 import StudioV1ErrorEnvelope
from services.studio_mock import contract_fixtures

app = FastAPI(title="Studio Runtime Configuration Mock")

_CONTRACT_VERSION = "1.0"
_CONTRACT_VERSION_V2 = "2.0"
RUNTIME_V2_PATH = "/internal/plugins/ssf/v2/runtime-configuration"
INSTALLATION_PATH = "/internal/plugins/ssf/v2/installation-content"
DIRECTORY_PATH = "/internal/plugins/ssf/v1/admin-login-tenants"
_AUTHORIZED_TOKEN = "Bearer studio-mock-authorized-token"
_UNAUTHORIZED_TOKEN = "Bearer studio-mock-unauthorized-token"
_UNAVAILABLE_MESSAGE = "Runtime configuration is unavailable."
_INSTALLATION_UNAVAILABLE_MESSAGE = "Installation content is unavailable."


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

InstallationErrorCode = Literal[
    "service_authentication_invalid",
    "service_action_forbidden",
    "malformed_request",
    "installation_content_unavailable",
]


_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
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

_DIRECTORY_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
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

_INSTALLATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": StudioV1ErrorEnvelope,
        "description": "The request is malformed or names a tenant.",
    },
    401: {
        "model": StudioV1ErrorEnvelope,
        "description": "Service authentication failed.",
    },
    403: {
        "model": StudioV1ErrorEnvelope,
        "description": "Service permission is missing.",
    },
    503: {
        "model": StudioV1ErrorEnvelope,
        "description": "Installation content is unavailable.",
    },
}


def _login_directory() -> dict[str, Any]:
    """Return the deterministic V1 login directory for all ready tenants."""
    directory = {
        "contractVersion": _CONTRACT_VERSION,
        "tenants": contract_fixtures.login_directory_tenants(),
    }
    directory["directoryRevision"] = contract_fixtures.revision(directory)
    return directory


def _error_response(
    status_code: int,
    code: RuntimeErrorCode | DirectoryErrorCode | InstallationErrorCode,
    correlation_id: str,
    retryable: bool,
    message: str = _UNAVAILABLE_MESSAGE,
    contract_version: str = _CONTRACT_VERSION,
) -> JSONResponse:
    """Return the stable Studio error envelope without tenant content."""
    return JSONResponse(
        status_code=status_code,
        content={
            "contractVersion": contract_version,
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "correlationId": correlation_id,
            },
        },
    )


def _service_auth_error(
    authorization: str | None,
    correlation_id: str | None,
    contract_version: str = _CONTRACT_VERSION,
    message: str = _UNAVAILABLE_MESSAGE,
) -> JSONResponse | None:
    """Return the 401 or 403 envelope for a token the mock does not authorize."""
    if authorization == _AUTHORIZED_TOKEN:
        return None
    correlation = correlation_id or "unavailable"
    if authorization == _UNAUTHORIZED_TOKEN:
        return _error_response(
            403, "service_action_forbidden", correlation, False, message, contract_version
        )
    return _error_response(
        401, "service_authentication_invalid", correlation, False, message, contract_version
    )


@dataclass(frozen=True, kw_only=True)
class _RuntimeRequest:
    authorization: str | None
    tenant_id: str | None
    correlation_id: str | None
    instance_id: str | None
    legacy_tenant_id: str | None
    scenario: str | None
    has_query: bool


def _runtime_request(
    request: Request,
    authorization: str | None = Header(default=None),
    x_studio_tenant_id: str | None = Header(default=None),
    x_correlation_id: str | None = Header(default=None),
    x_studio_instance_id: str | None = Header(default=None, include_in_schema=False),
    x_tenant_id: str | None = Header(default=None, include_in_schema=False),
    x_mock_scenario: str | None = Header(default=None),
) -> _RuntimeRequest:
    """Collect the runtime contract's headers for the v2 runtime route."""
    return _RuntimeRequest(
        authorization=authorization,
        tenant_id=x_studio_tenant_id,
        correlation_id=x_correlation_id,
        instance_id=x_studio_instance_id,
        legacy_tenant_id=x_tenant_id,
        scenario=x_mock_scenario,
        has_query=bool(request.url.query),
    )


_RUNTIME_SCENARIO_ERRORS: dict[str, tuple[int, RuntimeErrorCode, bool]] = {
    "suspended": (409, "tenant_suspended", False),
    "plugin-inactive": (409, "ssf_plugin_inactive", False),
    "tenant-not-ready": (409, "ssf_tenant_not_ready", True),
    "unavailable": (503, "runtime_configuration_unavailable", True),
}


def _checked_tenant(runtime_request: _RuntimeRequest) -> str | JSONResponse:
    """Return the selected tenant, or the v2 envelope for the first check it fails."""
    contract_version = _CONTRACT_VERSION_V2
    auth_error = _service_auth_error(
        runtime_request.authorization, runtime_request.correlation_id, contract_version
    )
    if auth_error is not None:
        return auth_error
    tenant_id = runtime_request.tenant_id
    correlation_id = runtime_request.correlation_id
    if (
        not tenant_id
        or not correlation_id
        or runtime_request.instance_id is not None
        or runtime_request.legacy_tenant_id is not None
        or runtime_request.has_query
    ):
        return _error_response(
            404,
            "tenant_not_found",
            correlation_id or "unavailable",
            False,
            contract_version=contract_version,
        )
    if runtime_request.scenario in _RUNTIME_SCENARIO_ERRORS:
        status_code, code, retryable = _RUNTIME_SCENARIO_ERRORS[runtime_request.scenario]
        return _error_response(
            status_code, code, correlation_id, retryable, contract_version=contract_version
        )
    if tenant_id not in contract_fixtures.RUNTIME_V2_TENANTS:
        return _error_response(
            404, "tenant_not_found", correlation_id, False, contract_version=contract_version
        )
    return tenant_id


@app.get(RUNTIME_V2_PATH, response_model=None, responses=_ERROR_RESPONSES)
def runtime_configuration_v2(
    runtime_request: _RuntimeRequest = Depends(_runtime_request),
) -> dict[str, Any] | JSONResponse:
    """Return a tenant's v2 body; scenarios may flip its storage mode or break its content."""
    tenant = _checked_tenant(runtime_request)
    if isinstance(tenant, JSONResponse):
        return tenant
    return contract_fixtures.runtime_configuration_v2(tenant, runtime_request.scenario)


@app.get(INSTALLATION_PATH, response_model=None, responses=_INSTALLATION_ERROR_RESPONSES)
def installation_content(
    request: Request,
    authorization: str | None = Header(default=None),
    x_correlation_id: str | None = Header(default=None),
    x_studio_tenant_id: str | None = Header(default=None, include_in_schema=False),
    x_studio_instance_id: str | None = Header(default=None, include_in_schema=False),
    x_tenant_id: str | None = Header(default=None, include_in_schema=False),
    x_mock_scenario: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Return the installation content v2 body, which belongs to no tenant."""

    def error(
        status_code: int, code: InstallationErrorCode, retryable: bool = False
    ) -> JSONResponse:
        return _error_response(
            status_code,
            code,
            x_correlation_id or "unavailable",
            retryable,
            _INSTALLATION_UNAVAILABLE_MESSAGE,
            _CONTRACT_VERSION_V2,
        )

    auth_error = _service_auth_error(
        authorization, x_correlation_id, _CONTRACT_VERSION_V2, _INSTALLATION_UNAVAILABLE_MESSAGE
    )
    if auth_error is not None:
        return auth_error
    if (
        not x_correlation_id
        or x_studio_tenant_id is not None
        or x_studio_instance_id is not None
        or x_tenant_id is not None
        or request.url.query
    ):
        return error(400, "malformed_request")
    if x_mock_scenario == "unavailable":
        return error(503, "installation_content_unavailable", retryable=True)
    return contract_fixtures.installation_content_v2(x_mock_scenario)


@app.get(
    DIRECTORY_PATH,
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
    auth_error = _service_auth_error(authorization, x_correlation_id)
    if auth_error is not None:
        return auth_error
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
    """Document required headers while preserving custom error envelopes."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    runtime_headers = {"authorization", "x-studio-tenant-id", "x-correlation-id"}
    service_headers = {"authorization", "x-correlation-id"}
    required_headers_by_path = {
        RUNTIME_V2_PATH: runtime_headers,
        INSTALLATION_PATH: service_headers,
        DIRECTORY_PATH: service_headers,
    }
    for path, header_names in required_headers_by_path.items():
        parameters = schema["paths"][path]["get"]["parameters"]
        for parameter in parameters:
            if parameter["in"] == "header" and parameter["name"] in header_names:
                parameter["required"] = True
                parameter["schema"] = {"type": "string"}
    # The shared envelope types `code` as a string; document what this mock emits.
    emitted_codes = {
        RUNTIME_V2_PATH: get_args(RuntimeErrorCode),
        INSTALLATION_PATH: get_args(InstallationErrorCode),
        DIRECTORY_PATH: get_args(DirectoryErrorCode),
    }
    for path, codes in emitted_codes.items():
        schema["paths"][path]["get"]["x-error-codes"] = sorted(codes)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi
