"""Tenant-bound composition for Studio Runtime Configuration V1."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Protocol

from .studio_runtime_client import RuntimeConfiguration, StudioRuntimeClientError
from .studio_runtime_token import StudioTokenError
from .tenant_context import StudioTenantContext


class RuntimeConfigurationFetcher(Protocol):
    """The already validated Studio Runtime Configuration V1 client boundary."""

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeConfiguration:
        raise NotImplementedError


class StudioRuntimeFlowError(RuntimeError):
    """A safe, classified failure from the composed runtime flow."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ValidatedRuntimeConfiguration:
    """A Studio configuration bound to one validated SSF tenant context."""

    context: StudioTenantContext
    configuration: RuntimeConfiguration
    correlation_id: str


class StudioRuntimeFlow:
    """Fetch Runtime Configuration V1 only for its validated tenant context."""

    def __init__(self, client: RuntimeConfigurationFetcher) -> None:
        self._client = client

    async def resolve(
        self,
        context: StudioTenantContext,
        correlation_id: str,
    ) -> ValidatedRuntimeConfiguration:
        """Return a configuration only when tenant and revision both match."""
        try:
            configuration = await self._client.fetch(context.tenant_id, correlation_id)
        except (StudioRuntimeClientError, StudioTokenError) as error:
            raise StudioRuntimeFlowError(
                error.code, retryable=error.retryable
            ) from None

        if configuration.tenant.id != context.tenant_id:
            raise StudioRuntimeFlowError(
                "studio_runtime_tenant_mismatch", retryable=False
            )
        if not hmac.compare_digest(
            configuration.authorization_revision,
            context.authorization_revision,
        ):
            raise StudioRuntimeFlowError(
                "studio_runtime_authorization_mismatch", retryable=False
            )

        return ValidatedRuntimeConfiguration(
            context=context,
            configuration=configuration,
            correlation_id=correlation_id,
        )
