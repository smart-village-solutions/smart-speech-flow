"""Strict consumer for the Studio Runtime Configuration V1 contract."""

from __future__ import annotations

import hmac
import re
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, HttpUrl, field_validator, model_validator

from .studio_v1 import (
    ContractModel,
    StudioV1ClientError,
    StudioV1Endpoint,
    StudioV1Transport,
    require_printable_ascii,
)

RUNTIME_PATH = "/internal/plugins/ssf/v1/runtime-configuration"
REVISION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
LOCALE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$")
EXPECTED_ERROR_CODES = {
    400: {"malformed_request"},
    401: {"service_authentication_invalid"},
    403: {"service_action_forbidden"},
    404: {"tenant_not_found"},
    409: {"tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"},
    503: {"runtime_configuration_unavailable"},
}


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


class StudioRuntimeClientError(StudioV1ClientError):
    """Safe failure surfaced by the Studio runtime client."""


class StudioRuntimeClient:
    """Fetch and validate one tenant's Studio Runtime Configuration V1."""

    def __init__(
        self,
        base_url: str,
        token_provider: Callable[[], Awaitable[str]],
        *,
        transport: StudioV1Transport | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._endpoint = StudioV1Endpoint(
            base_url,
            RUNTIME_PATH,
            error_type=StudioRuntimeClientError,
            code_prefix="studio_runtime",
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
        self._token_provider = token_provider

    @property
    def timeout_seconds(self) -> float:
        """The per-read timeout this client was built with."""
        return self._endpoint.timeout_seconds

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeConfiguration:
        require_printable_ascii(tenant_id, "tenant_id")
        require_printable_ascii(correlation_id, "correlation_id")
        token = await self._endpoint.bearer_token(self._token_provider)
        configuration = await self._endpoint.fetch_validated(
            {
                "Authorization": f"Bearer {token}",
                "X-Studio-Tenant-Id": tenant_id,
                "X-Correlation-Id": correlation_id,
            },
            RuntimeConfiguration,
            EXPECTED_ERROR_CODES,
        )
        # Studio's tenant id is not guaranteed ASCII, and compare_digest raises on non-ASCII str.
        if not hmac.compare_digest(
            configuration.tenant.id.encode("utf-8"), tenant_id.encode("utf-8")
        ):
            raise StudioRuntimeClientError(
                "studio_runtime_tenant_mismatch", retryable=False, status=200
            )
        return configuration
