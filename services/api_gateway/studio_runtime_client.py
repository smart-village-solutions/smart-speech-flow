"""Strict consumer for the Studio Runtime Configuration V1 contract."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
    model_validator,
)

RUNTIME_PATH = "/internal/plugins/ssf/v1/runtime-configuration"
REVISION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
LOCALE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$")
SUPPORTED_ERROR_STATUSES = {400, 401, 403, 404, 409, 503}
EXPECTED_ERROR_CODES = {
    401: {"service_authentication_invalid"},
    403: {"service_action_forbidden"},
    404: {"tenant_not_found"},
    409: {"tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"},
    503: {"runtime_configuration_unavailable"},
}


class ContractModel(BaseModel):
    """Validate known fields while accepting optional V1 extensions."""

    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)


class MediaAsset(ContractModel):
    url: HttpUrl
    alternative_text: str = Field(alias="alternativeText", max_length=500)


class Branding(ContractModel):
    logo: MediaAsset | None
    icon: MediaAsset | None


class Tenant(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(alias="displayName", min_length=1, max_length=200)
    time_zone: str = Field(alias="timeZone", min_length=1, max_length=100)

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timeZone must be an IANA time zone") from error
        return value


class LocaleConfiguration(ContractModel):
    locale: str = Field(min_length=1, max_length=35)
    authenticated_home_explanation_html: str = Field(alias="authenticatedHomeExplanationHtml")
    guest_explanation_html: str = Field(alias="guestExplanationHtml")
    conversation_content_storage_question_html: str | None = Field(
        alias="conversationContentStorageQuestionHtml"
    )

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str) -> str:
        if not LOCALE_PATTERN.fullmatch(value):
            raise ValueError("locale must be a BCP-47 language tag")
        return value

    @field_validator(
        "authenticated_home_explanation_html",
        "guest_explanation_html",
        "conversation_content_storage_question_html",
    )
    @classmethod
    def validate_html_size(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > 65_536:
            raise ValueError("HTML exceeds the V1 byte limit")
        return value


class Localization(ContractModel):
    default_locale: str = Field(alias="defaultLocale", min_length=1, max_length=35)
    locales: list[LocaleConfiguration] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_active_locales(self) -> "Localization":
        locale_names = [entry.locale for entry in self.locales]
        if len(locale_names) != len(set(locale_names)):
            raise ValueError("locales must be unique")
        if self.default_locale not in locale_names:
            raise ValueError("defaultLocale must be active")
        return self


class ConversationContentStorage(ContractModel):
    mode: str = Field(pattern="^(ask|disabled)$")


class RuntimeConfiguration(ContractModel):
    contract_version: str = Field(alias="contractVersion", pattern="^1[.]0$")
    configuration_revision: str = Field(alias="configurationRevision")
    authorization_revision: str = Field(alias="authorizationRevision")
    tenant: Tenant
    branding: Branding
    localization: Localization
    conversation_content_storage: ConversationContentStorage = Field(
        alias="conversationContentStorage"
    )

    @field_validator("configuration_revision", "authorization_revision")
    @classmethod
    def validate_revision(cls, value: str) -> str:
        if not REVISION_PATTERN.fullmatch(value):
            raise ValueError("revision must be a lowercase SHA-256 value")
        return value

    @model_validator(mode="after")
    def validate_storage_semantics(self) -> "RuntimeConfiguration":
        if self.conversation_content_storage.mode == "disabled" and any(
            entry.conversation_content_storage_question_html is not None
            for entry in self.localization.locales
        ):
            raise ValueError("storage questions must be null when storage is disabled")
        return self


class RuntimeErrorDetails(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=200)
    retryable: bool
    correlation_id: str = Field(alias="correlationId", min_length=1, max_length=128)


class RuntimeErrorEnvelope(ContractModel):
    contract_version: str = Field(alias="contractVersion", pattern="^1[.]0$")
    error: RuntimeErrorDetails


class StudioRuntimeClientError(RuntimeError):
    """Safe failure surfaced by the Studio runtime client."""

    def __init__(self, code: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True)
class RuntimeHttpResponse:
    status: int
    payload: Mapping[str, Any]


class RuntimeTransport(Protocol):
    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> RuntimeHttpResponse: ...


class AiohttpRuntimeTransport:
    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> RuntimeHttpResponse:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                try:
                    payload = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    raise StudioRuntimeClientError(
                        "studio_runtime_response_invalid", retryable=False, status=response.status
                    ) from None
                if not isinstance(payload, Mapping):
                    raise StudioRuntimeClientError(
                        "studio_runtime_response_invalid", retryable=False, status=response.status
                    )
                return RuntimeHttpResponse(status=response.status, payload=payload)


class StudioRuntimeClient:
    """Fetch and validate one tenant's Studio Runtime Configuration V1."""

    def __init__(
        self,
        base_url: str,
        token_provider: Callable[[], Awaitable[str]],
        *,
        transport: RuntimeTransport | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        parsed_url = urlsplit(base_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.path not in {"", "/"}
        ):
            raise ValueError("base_url must be an HTTP origin")
        if parsed_url.query or parsed_url.fragment:
            raise ValueError("base_url must not contain a query or fragment")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 0 and 30")
        self._url = f"{base_url.rstrip('/')}{RUNTIME_PATH}"
        self._token_provider = token_provider
        self._transport = transport or AiohttpRuntimeTransport()
        self._timeout_seconds = timeout_seconds

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeConfiguration:
        _validate_request_context(tenant_id, correlation_id)

        token = await self._token_provider()
        if not token:
            raise StudioRuntimeClientError("studio_runtime_token_invalid", retryable=False)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Studio-Tenant-Id": tenant_id,
            "X-Correlation-Id": correlation_id,
        }
        try:
            response = await self._transport.get(self._url, headers, self._timeout_seconds)
        except StudioRuntimeClientError:
            raise
        except (TimeoutError, asyncio.TimeoutError, aiohttp.ClientError):
            raise StudioRuntimeClientError("studio_runtime_network_error", retryable=True) from None

        if response.status == 200:
            try:
                configuration = RuntimeConfiguration.model_validate(response.payload)
            except ValidationError:
                raise StudioRuntimeClientError(
                    "studio_runtime_response_invalid", retryable=False, status=200
                ) from None
            if configuration.tenant.id != tenant_id:
                raise StudioRuntimeClientError(
                    "studio_runtime_tenant_mismatch", retryable=False, status=200
                )
            return configuration

        if response.status not in SUPPORTED_ERROR_STATUSES:
            raise StudioRuntimeClientError(
                "studio_runtime_unexpected_status",
                retryable=response.status >= 500,
                status=response.status,
            )
        try:
            envelope = RuntimeErrorEnvelope.model_validate(response.payload)
        except ValidationError:
            raise StudioRuntimeClientError(
                "studio_runtime_error_invalid", retryable=False, status=response.status
            ) from None
        expected_codes = EXPECTED_ERROR_CODES.get(response.status)
        if expected_codes is not None and envelope.error.code not in expected_codes:
            raise StudioRuntimeClientError(
                "studio_runtime_error_invalid", retryable=False, status=response.status
            )
        raise StudioRuntimeClientError(
            envelope.error.code,
            retryable=envelope.error.retryable,
            status=response.status,
        )


def _validate_request_context(tenant_id: str, correlation_id: str) -> None:
    if (
        not tenant_id
        or len(tenant_id) > 128
        or any(ord(character) < 32 or ord(character) > 126 for character in tenant_id)
    ):
        raise ValueError("tenant_id must be printable ASCII with at most 128 characters")
    if (
        not correlation_id
        or len(correlation_id) > 128
        or any(ord(character) < 32 or ord(character) > 126 for character in correlation_id)
    ):
        raise ValueError("correlation_id must be printable ASCII with at most 128 characters")
