"""Tenant-bound composition for Studio runtime configuration v2."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated, Protocol
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status

from .dependencies import get_studio_runtime_flow
from .studio_runtime_token import StudioRuntimeTokenProvider, StudioTokenError
from .studio_runtime_v2_client import StudioRuntimeV2Client, StudioRuntimeV2ClientError
from .studio_settings import seconds_setting, studio_base_url
from .studio_v2 import RuntimeRead
from .tenant_context import StudioTenantContext, require_studio_tenant_context


class RuntimeConfigurationFetcher(Protocol):
    """The already validated Studio runtime configuration v2 client boundary."""

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeRead:
        raise NotImplementedError


class StudioRuntimeFlowError(RuntimeError):
    """A safe, classified failure from the composed runtime flow."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ValidatedRuntimeConfiguration:
    """A Studio read bound to one validated SSF tenant context."""

    context: StudioTenantContext
    read: RuntimeRead
    correlation_id: str


class StudioRuntimeFlow:
    """Fetch the runtime configuration only for its validated tenant context."""

    def __init__(self, client: RuntimeConfigurationFetcher) -> None:
        self._client = client

    @property
    def client(self) -> RuntimeConfigurationFetcher:
        """The underlying fetcher, for callers that carry no tenant context."""
        return self._client

    async def resolve(
        self,
        context: StudioTenantContext,
        correlation_id: str,
    ) -> ValidatedRuntimeConfiguration:
        """Return a read only when its tenant matches the verified realm."""
        try:
            read = await self._client.fetch(context.tenant_id, correlation_id)
        except (StudioRuntimeV2ClientError, StudioTokenError) as error:
            raise StudioRuntimeFlowError(error.code, retryable=error.retryable) from None

        # Studio's tenant id is not guaranteed ASCII, and compare_digest raises on non-ASCII str.
        if not hmac.compare_digest(
            read.policy.tenant_id.encode("utf-8"),
            context.tenant_id.encode("utf-8"),
        ):
            raise StudioRuntimeFlowError("studio_runtime_tenant_mismatch", retryable=False)
        return ValidatedRuntimeConfiguration(
            context=context,
            read=read,
            correlation_id=correlation_id,
        )


_DEFAULT_CONFIGURATION_TIMEOUT_SECONDS = 5.0


def runtime_client_from_environment(
    token_provider: StudioRuntimeTokenProvider | None,
) -> StudioRuntimeV2Client:
    """The app's one runtime client, from explicit settings and the app's token provider.

    An unusable timeout falls back to the default rather than propagating. The
    flow built on this also backs `require_validated_runtime_configuration`,
    so letting the client's range check raise here would turn a mistyped
    timeout into a 502 on every tenant-login request, not merely an unbound
    persistence gate.

    Raises:
        StudioRuntimeFlowError: no token provider, or no usable base URL.
    """
    if token_provider is None:
        raise StudioRuntimeFlowError("studio_runtime_configuration_invalid", retryable=False)
    try:
        return StudioRuntimeV2Client(
            studio_base_url(),
            token_provider.get_token,
            timeout_seconds=seconds_setting(
                "STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS",
                _DEFAULT_CONFIGURATION_TIMEOUT_SECONDS,
                30,
            ),
        )
    except ValueError:
        raise StudioRuntimeFlowError(
            "studio_runtime_configuration_invalid", retryable=False
        ) from None


def runtime_flow_from_environment(
    token_provider: StudioRuntimeTokenProvider | None,
) -> StudioRuntimeFlow:
    """A runtime flow on `runtime_client_from_environment`."""
    return StudioRuntimeFlow(runtime_client_from_environment(token_provider))


async def require_validated_runtime_configuration(
    request: Request,
    context: Annotated[StudioTenantContext, Depends(require_studio_tenant_context)],
    runtime_flow: Annotated[StudioRuntimeFlow | None, Depends(get_studio_runtime_flow)],
) -> ValidatedRuntimeConfiguration:
    """Resolve a tenant-bound runtime configuration for a later route dependency."""
    correlation_id = correlation_id_from_request(request)
    try:
        if runtime_flow is None:
            raise StudioRuntimeFlowError("studio_runtime_configuration_invalid", retryable=False)
        return await runtime_flow.resolve(context, correlation_id)
    except StudioRuntimeFlowError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if error.retryable
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail=error.code,
        ) from None


def correlation_id_from_request(request: Request) -> str:
    """Return a safe caller correlation ID or a gateway-generated UUID.

    Every route that forwards this header to Studio must go through here.
    `StudioRuntimeV2Client` rejects a malformed value with a bare `ValueError`,
    which no caller classifies: on a read path it escapes as a 500, and on a
    write path the policy gate's blanket except turns it into a silent refusal
    to persist.

    Args:
        request: The inbound request whose `X-Correlation-Id` is read.

    Returns:
        The caller's correlation ID, or a fresh UUID when none was supplied.

    Raises:
        HTTPException: 400 when a supplied value is not printable ASCII of at
            most 128 characters.
    """
    correlation_id = request.headers.get("X-Correlation-Id")
    if correlation_id is None:
        return str(uuid4())
    if (
        not correlation_id
        or len(correlation_id) > 128
        or any(ord(character) < 32 or ord(character) > 126 for character in correlation_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid X-Correlation-Id is required when supplied",
        )
    return correlation_id
