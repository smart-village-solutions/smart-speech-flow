"""Consumer for the Studio Runtime Configuration v2 contract.

Error codes match the V1 client, so the policy gate and the activation
conflict classify a v2 failure exactly as they classified a V1 one.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from .studio_v1 import (
    StudioV1ClientError,
    StudioV1Endpoint,
    StudioV1Transport,
    require_printable_ascii,
)
from .studio_v2 import RuntimeRead, StudioContractError, parse_runtime_configuration_v2

RUNTIME_V2_PATH = "/internal/plugins/ssf/v2/runtime-configuration"
EXPECTED_ERROR_CODES = {
    400: {"malformed_request"},
    401: {"service_authentication_invalid"},
    403: {"service_action_forbidden"},
    404: {"tenant_not_found"},
    409: {"tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"},
    503: {"runtime_configuration_unavailable"},
}
# The tenant states Studio answers 409 for: a session may not start, and they are
# deliberate, not failures of Studio.
TENANT_CONFLICT_CODES = frozenset(EXPECTED_ERROR_CODES[409])
_CODE_PREFIX = "studio_runtime"


class StudioRuntimeV2ClientError(StudioV1ClientError):
    """Safe failure surfaced by the Studio runtime v2 client."""


class StudioRuntimeV2Client:
    """Fetch one tenant's runtime configuration v2: strict policy, lenient content."""

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
            RUNTIME_V2_PATH,
            error_type=StudioRuntimeV2ClientError,
            code_prefix=_CODE_PREFIX,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
        self._token_provider = token_provider

    @property
    def timeout_seconds(self) -> float:
        """The per-read timeout this client was built with."""
        return self._endpoint.timeout_seconds

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeRead:
        require_printable_ascii(tenant_id, "tenant_id")
        require_printable_ascii(correlation_id, "correlation_id")
        token = await self._endpoint.bearer_token(self._token_provider)
        payload = await self._endpoint.fetch_payload(
            {
                "Authorization": f"Bearer {token}",
                "X-Studio-Tenant-Id": tenant_id,
                "X-Correlation-Id": correlation_id,
            },
            EXPECTED_ERROR_CODES,
        )
        try:
            return parse_runtime_configuration_v2(payload, expected_tenant_id=tenant_id)
        except StudioContractError as error:
            raise StudioRuntimeV2ClientError(
                f"{_CODE_PREFIX}_{error.reason}", retryable=False, status=200
            ) from None
