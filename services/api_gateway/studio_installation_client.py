"""Consumer for the Studio installation content v2 contract: the pre-tenant pages."""

from __future__ import annotations

from typing import Awaitable, Callable

from .studio_v1 import (
    StudioV1ClientError,
    StudioV1Endpoint,
    StudioV1Transport,
    require_printable_ascii,
)
from .studio_v2 import InstallationContent, StudioContractError, parse_installation_content_v2

INSTALLATION_PATH = "/internal/plugins/ssf/v2/installation-content"
# Studio documents no installation-specific 503 code, so both plausible ones are accepted.
EXPECTED_ERROR_CODES = {
    400: {"malformed_request"},
    401: {"service_authentication_invalid"},
    403: {"service_action_forbidden"},
    503: {"installation_content_unavailable", "runtime_configuration_unavailable"},
}
_CODE_PREFIX = "studio_installation"


class StudioInstallationClientError(StudioV1ClientError):
    """Safe failure surfaced by the Studio installation content client."""


class StudioInstallationClient:
    """Fetch installation content v2, which carries no tenant header."""

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
            INSTALLATION_PATH,
            error_type=StudioInstallationClientError,
            code_prefix=_CODE_PREFIX,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
        self._token_provider = token_provider

    @property
    def timeout_seconds(self) -> float:
        """The per-read timeout this client was built with."""
        return self._endpoint.timeout_seconds

    async def fetch(self, correlation_id: str) -> InstallationContent:
        require_printable_ascii(correlation_id, "correlation_id")
        token = await self._endpoint.bearer_token(self._token_provider)
        payload = await self._endpoint.fetch_payload(
            {"Authorization": f"Bearer {token}", "X-Correlation-Id": correlation_id},
            EXPECTED_ERROR_CODES,
        )
        try:
            return parse_installation_content_v2(payload)
        except StudioContractError as error:
            raise StudioInstallationClientError(
                f"{_CODE_PREFIX}_{error.reason}", retryable=False, status=200
            ) from None
