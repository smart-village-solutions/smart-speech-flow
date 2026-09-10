"""Strict consumer for the Studio administrative login-directory V1 contract."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import aiohttp
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from services.api_gateway.studio_runtime_token import StudioRuntimeTokenProvider

DIRECTORY_PATH = "/internal/plugins/ssf/v1/admin-login-tenants"
TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
REALM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REVISION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SUPPORTED_ERROR_STATUSES = {401, 403, 503}
EXPECTED_ERROR_CODES = {
    401: {"service_authentication_invalid"},
    403: {"service_action_forbidden"},
    503: {"admin_login_directory_unavailable"},
}


class StudioLoginTenant(BaseModel):
    """One publicly displayable Studio tenant and its provisioned realm."""

    model_config = ConfigDict(
        extra="ignore", frozen=True, strict=True, populate_by_name=True
    )

    id: str
    display_name: str = Field(alias="displayName", min_length=1, max_length=200)
    realm: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not TENANT_ID_PATTERN.fullmatch(value):
            raise ValueError("id must be a safe Studio tenant identifier")
        return value

    @field_validator("realm")
    @classmethod
    def validate_realm(cls, value: str) -> str:
        if not REALM_PATTERN.fullmatch(value):
            raise ValueError("realm must be a safe Keycloak realm identifier")
        return value


class StudioLoginDirectory(BaseModel):
    """The validated tenant-unbound Studio login directory."""

    model_config = ConfigDict(
        extra="ignore", frozen=True, strict=True, populate_by_name=True
    )

    contract_version: str = Field(alias="contractVersion", pattern=r"^1[.]0$")
    directory_revision: str = Field(alias="directoryRevision")
    tenants: tuple[StudioLoginTenant, ...] = Field(max_length=10_000, strict=False)

    @field_validator("directory_revision")
    @classmethod
    def validate_directory_revision(cls, value: str) -> str:
        if not REVISION_PATTERN.fullmatch(value):
            raise ValueError("directoryRevision must be a lowercase SHA-256 value")
        return value

    @model_validator(mode="after")
    def validate_unique_tenants(self) -> "StudioLoginDirectory":
        ids = [tenant.id for tenant in self.tenants]
        realms = [tenant.realm for tenant in self.tenants]
        if len(ids) != len(set(ids)):
            raise ValueError("tenant IDs must be unique")
        if len(realms) != len(set(realms)):
            raise ValueError("tenant realms must be unique")
        return self


class DirectoryErrorDetails(BaseModel):
    """The stable nested error object in Studio's V1 error envelope."""

    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=200)
    retryable: bool
    correlation_id: str = Field(alias="correlationId", min_length=1, max_length=128)


class DirectoryErrorEnvelope(BaseModel):
    """The stable Studio V1 error response shape."""

    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)

    contract_version: str = Field(alias="contractVersion", pattern=r"^1[.]0$")
    error: DirectoryErrorDetails


class StudioLoginDirectoryClientError(RuntimeError):
    """Safe failure surfaced by the Studio login-directory client."""

    def __init__(
        self, code: str, *, retryable: bool, status: int | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True)
class DirectoryHttpResponse:
    """The response shape shared by the HTTP transport and client."""

    status: int
    payload: Mapping[str, Any]


class DirectoryTransport(Protocol):
    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> DirectoryHttpResponse:
        pass


class AiohttpDirectoryTransport:
    """Default async transport for the Studio login-directory endpoint."""

    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> DirectoryHttpResponse:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                try:
                    payload = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    raise StudioLoginDirectoryClientError(
                        "studio_login_directory_response_invalid",
                        retryable=False,
                        status=response.status,
                    ) from None
                if not isinstance(payload, Mapping):
                    raise StudioLoginDirectoryClientError(
                        "studio_login_directory_response_invalid",
                        retryable=False,
                        status=response.status,
                    )
                return DirectoryHttpResponse(status=response.status, payload=payload)


class StudioLoginDirectoryClient:
    """Fetch and validate the Studio administrative login-directory V1 contract."""

    def __init__(
        self,
        base_url: str,
        token_provider: StudioRuntimeTokenProvider,
        *,
        transport: DirectoryTransport | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        parsed_url = urlsplit(base_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.path not in {"", "/"}
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("base_url must be an HTTP origin")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 0 and 30")
        self._url = f"{base_url.rstrip('/')}{DIRECTORY_PATH}"
        self._token_provider = token_provider
        self._transport = transport or AiohttpDirectoryTransport()
        self._timeout_seconds = timeout_seconds

    async def fetch(self, correlation_id: str) -> StudioLoginDirectory:
        _validate_printable_ascii(correlation_id, "correlation_id")
        token = await self._token_provider.get_token()
        if not _is_printable_ascii(token):
            raise StudioLoginDirectoryClientError(
                "studio_login_directory_token_invalid", retryable=False
            )
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Correlation-Id": correlation_id,
        }
        try:
            response = await self._transport.get(
                self._url, headers, self._timeout_seconds
            )
        except StudioLoginDirectoryClientError:
            raise
        except (TimeoutError, asyncio.TimeoutError, aiohttp.ClientError):
            raise StudioLoginDirectoryClientError(
                "studio_login_directory_network_error", retryable=True
            ) from None

        if response.status == 200:
            try:
                return StudioLoginDirectory.model_validate(response.payload)
            except ValidationError:
                raise StudioLoginDirectoryClientError(
                    "studio_login_directory_response_invalid",
                    retryable=False,
                    status=200,
                ) from None

        if response.status not in SUPPORTED_ERROR_STATUSES:
            raise StudioLoginDirectoryClientError(
                "studio_login_directory_unexpected_status",
                retryable=response.status >= 500,
                status=response.status,
            )
        try:
            envelope = DirectoryErrorEnvelope.model_validate(response.payload)
        except ValidationError:
            raise StudioLoginDirectoryClientError(
                "studio_login_directory_error_invalid",
                retryable=False,
                status=response.status,
            ) from None
        if envelope.error.code not in EXPECTED_ERROR_CODES[response.status]:
            raise StudioLoginDirectoryClientError(
                "studio_login_directory_error_invalid",
                retryable=False,
                status=response.status,
            )
        raise StudioLoginDirectoryClientError(
            envelope.error.code,
            retryable=envelope.error.retryable,
            status=response.status,
        )


def _is_printable_ascii(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and all(32 <= ord(character) <= 126 for character in value)
    )


def _validate_printable_ascii(value: str, name: str) -> None:
    if not _is_printable_ascii(value) or len(value) > 128:
        raise ValueError(f"{name} must be printable ASCII with at most 128 characters")
