"""Strict consumer for the Studio administrative login-directory V1 contract."""

from __future__ import annotations

import re
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .studio_v1 import (
    StudioV1ClientError,
    StudioV1Endpoint,
    StudioV1Transport,
    require_printable_ascii,
)

DIRECTORY_PATH = "/internal/plugins/ssf/v1/admin-login-tenants"
TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
REALM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REVISION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_ERROR_CODES = {
    401: {"service_authentication_invalid"},
    403: {"service_action_forbidden"},
    503: {"admin_login_directory_unavailable"},
}


class StudioLoginTenant(BaseModel):
    """One publicly displayable Studio tenant and its provisioned realm."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, populate_by_name=True)

    id: str
    display_name: str = Field(alias="displayName", min_length=1, max_length=200)
    realm: str
    studio_url: str | None = Field(default=None, alias="studioUrl", max_length=2_048)

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

    @field_validator("studio_url")
    @classmethod
    def validate_studio_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(character.isspace() for character in value)
        ):
            raise ValueError("studioUrl must be a safe HTTPS URL")
        _ = parsed.port
        return value


class StudioLoginDirectory(BaseModel):
    """The validated tenant-unbound Studio login directory."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, populate_by_name=True)

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


class StudioLoginDirectoryClientError(StudioV1ClientError):
    """Safe failure surfaced by the Studio login-directory client."""


class StudioLoginDirectoryClient:
    """Fetch and validate the Studio administrative login-directory V1 contract."""

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
            DIRECTORY_PATH,
            error_type=StudioLoginDirectoryClientError,
            code_prefix="studio_login_directory",
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
        self._token_provider = token_provider

    async def fetch(self, correlation_id: str) -> StudioLoginDirectory:
        require_printable_ascii(correlation_id, "correlation_id")
        token = await self._endpoint.bearer_token(self._token_provider)
        return await self._endpoint.fetch_validated(
            {"Authorization": f"Bearer {token}", "X-Correlation-Id": correlation_id},
            StudioLoginDirectory,
            EXPECTED_ERROR_CODES,
        )
