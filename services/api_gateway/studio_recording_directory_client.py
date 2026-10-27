"""Consumer for the Studio recording directory (contract v2, spec §10.1).

No token carries another user's permissions, so the gateway asks Studio who
in a tenant holds an `ssf.recording.*` permission: before a recovery-key
ceremony names its custodians, and later before every reviewer grant. It is
read live, never cached, because a revoked permission must stop counting at
once.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .studio_v1 import (
    StudioV1ClientError,
    StudioV1Endpoint,
    StudioV1Transport,
    require_printable_ascii,
)

RECORDING_DIRECTORY_PATH = "/internal/plugins/ssf/v2/recording-directory"
EXPECTED_ERROR_CODES = {
    400: {"malformed_request"},
    401: {"service_authentication_invalid"},
    403: {"service_action_forbidden"},
    404: {"tenant_not_found"},
    409: {"tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"},
    503: {"recording_directory_unavailable"},
}
SUB_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,254}$")
PERMISSION_PATTERN = re.compile(r"^ssf\.recording(\.[a-z]+)+$")
LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
REVISION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_CODE_PREFIX = "studio_recording_directory"


class RecordingDirectoryUser(BaseModel):
    """One staff member holding at least one recording permission."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, populate_by_name=True)

    sub: str
    display_name: str = Field(alias="displayName", min_length=1, max_length=200)
    permissions: tuple[str, ...] = Field(min_length=1, max_length=20, strict=False)
    languages: tuple[str, ...] = Field(default=(), max_length=40, strict=False)

    @field_validator("sub")
    @classmethod
    def validate_sub(cls, value: str) -> str:
        if not SUB_PATTERN.fullmatch(value):
            raise ValueError("sub must be a safe Keycloak subject")
        return value

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not all(PERMISSION_PATTERN.fullmatch(item) for item in value):
            raise ValueError("permissions must be ssf.recording.* names")
        return value

    @field_validator("languages")
    @classmethod
    def validate_languages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not all(LANGUAGE_PATTERN.fullmatch(item) for item in value):
            raise ValueError("languages must be language tags")
        return value


class RecordingDirectory(BaseModel):
    """The validated recording directory of one tenant."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, populate_by_name=True)

    contract_version: str = Field(alias="contractVersion", pattern=r"^2[.]0$")
    tenant_id: str = Field(alias="tenantId", min_length=1, max_length=128)
    directory_revision: str = Field(alias="directoryRevision")
    users: tuple[RecordingDirectoryUser, ...] = Field(max_length=10_000, strict=False)

    @field_validator("directory_revision")
    @classmethod
    def validate_directory_revision(cls, value: str) -> str:
        if not REVISION_PATTERN.fullmatch(value):
            raise ValueError("directoryRevision must be a lowercase SHA-256 value")
        return value

    @field_validator("users")
    @classmethod
    def validate_unique_users(
        cls, value: tuple[RecordingDirectoryUser, ...]
    ) -> tuple[RecordingDirectoryUser, ...]:
        subs = [user.sub for user in value]
        if len(subs) != len(set(subs)):
            raise ValueError("user subjects must be unique")
        return value

    def holders_of(self, permission: str) -> dict[str, RecordingDirectoryUser]:
        return {user.sub: user for user in self.users if permission in user.permissions}


class StudioRecordingDirectoryClientError(StudioV1ClientError):
    """Safe failure surfaced by the Studio recording-directory client."""


class StudioRecordingDirectoryClient:
    """Fetch one tenant's recording directory; every call is a fresh read."""

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
            RECORDING_DIRECTORY_PATH,
            error_type=StudioRecordingDirectoryClientError,
            code_prefix=_CODE_PREFIX,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
        self._token_provider = token_provider

    async def fetch(self, tenant_id: str, correlation_id: str) -> RecordingDirectory:
        require_printable_ascii(tenant_id, "tenant_id")
        require_printable_ascii(correlation_id, "correlation_id")
        token = await self._endpoint.bearer_token(self._token_provider)
        directory = await self._endpoint.fetch_validated(
            {
                "Authorization": f"Bearer {token}",
                "X-Studio-Tenant-Id": tenant_id,
                "X-Correlation-Id": correlation_id,
            },
            RecordingDirectory,
            EXPECTED_ERROR_CODES,
        )
        if directory.tenant_id != tenant_id:
            raise StudioRecordingDirectoryClientError(
                f"{_CODE_PREFIX}_tenant_mismatch", retryable=False, status=200
            )
        return directory
