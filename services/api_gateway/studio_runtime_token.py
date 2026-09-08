"""OAuth2 client-credentials token provider for the Studio runtime API."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

import aiohttp

DEFAULT_CLIENT_ID = "ssf-runtime"
DEFAULT_AUDIENCE = "sva-studio-ssf-runtime"


class StudioTokenError(RuntimeError):
    """A safe, classified Studio token acquisition failure."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class StudioTokenConfig:
    """Configuration for Studio service-token acquisition."""

    token_url: str
    client_secret: str
    client_id: str = DEFAULT_CLIENT_ID
    audience: str = DEFAULT_AUDIENCE
    timeout_seconds: float = 5.0
    refresh_skew_seconds: float = 30.0
    fixed_token: str | None = None

    def __post_init__(self) -> None:
        normalized_fixed_token = self.fixed_token.strip() if self.fixed_token else None
        object.__setattr__(self, "fixed_token", normalized_fixed_token or None)
        if not self.fixed_token and (
            not self.token_url or not self.client_id or not self.client_secret or not self.audience
        ):
            raise StudioTokenError("studio_token_configuration_invalid", retryable=False)
        if not 0 < self.timeout_seconds <= 30 or not 0 <= self.refresh_skew_seconds <= 300:
            raise StudioTokenError("studio_token_configuration_invalid", retryable=False)

    @classmethod
    def from_env(cls) -> "StudioTokenConfig":
        """Load the provider configuration from environment variables."""
        fixed_token = (os.getenv("STUDIO_RUNTIME_FIXED_TOKEN") or "").strip() or None
        token_url = os.getenv("STUDIO_RUNTIME_TOKEN_URL", "").strip()
        client_secret = os.getenv("STUDIO_RUNTIME_CLIENT_SECRET", "")
        if not fixed_token and (not token_url or not client_secret):
            raise StudioTokenError("studio_token_configuration_invalid", retryable=False)
        try:
            timeout_seconds = float(os.getenv("STUDIO_RUNTIME_TOKEN_TIMEOUT_SECONDS", "5"))
            refresh_skew_seconds = float(
                os.getenv("STUDIO_RUNTIME_TOKEN_REFRESH_SKEW_SECONDS", "30")
            )
        except ValueError:
            raise StudioTokenError("studio_token_configuration_invalid", retryable=False) from None
        return cls(
            token_url=token_url,
            client_secret=client_secret,
            client_id=os.getenv("STUDIO_RUNTIME_CLIENT_ID", DEFAULT_CLIENT_ID),
            audience=os.getenv("STUDIO_RUNTIME_AUDIENCE", DEFAULT_AUDIENCE),
            timeout_seconds=timeout_seconds,
            refresh_skew_seconds=refresh_skew_seconds,
            fixed_token=fixed_token,
        )


@dataclass(frozen=True)
class TokenResponse:
    status: int
    payload: Mapping[str, Any]


class TokenTransport(Protocol):
    async def post_form(
        self, url: str, data: Mapping[str, str], timeout_seconds: float
    ) -> TokenResponse: ...


class AiohttpTokenTransport:
    """Small default HTTP transport; tests inject a deterministic replacement."""

    async def post_form(
        self, url: str, data: Mapping[str, str], timeout_seconds: float
    ) -> TokenResponse:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=data) as response:
                try:
                    payload = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    raise StudioTokenError(
                        "studio_token_response_invalid", retryable=False
                    ) from None
                if not isinstance(payload, Mapping):
                    raise StudioTokenError("studio_token_response_invalid", retryable=False)
                return TokenResponse(status=response.status, payload=payload)


class StudioRuntimeTokenProvider:
    """Acquire and reuse a short-lived Studio service token in memory."""

    def __init__(
        self,
        config: StudioTokenConfig,
        *,
        transport: TokenTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._transport = transport or AiohttpTokenTransport()
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return a valid token, refreshing it once for concurrent callers."""
        if self._config.fixed_token:
            return self._config.fixed_token
        if self._is_valid():
            return self._token or ""

        async with self._lock:
            if self._is_valid():
                return self._token or ""
            return await self._refresh()

    def _is_valid(self) -> bool:
        return bool(
            self._token and self._expires_at - self._config.refresh_skew_seconds > self._clock()
        )

    async def _refresh(self) -> str:
        request = {
            "grant_type": "client_credentials",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "audience": self._config.audience,
        }
        try:
            response = await self._transport.post_form(
                self._config.token_url, request, self._config.timeout_seconds
            )
        except StudioTokenError:
            raise
        except (TimeoutError, asyncio.TimeoutError, aiohttp.ClientError):
            raise StudioTokenError("studio_token_network_error", retryable=True) from None

        if response.status < 200 or response.status >= 300:
            raise StudioTokenError(
                "studio_token_authentication_failed", retryable=response.status >= 500
            )

        token = response.payload.get("access_token")
        expires_in = response.payload.get("expires_in")
        token_type = response.payload.get("token_type", "Bearer")
        if (
            not isinstance(token, str)
            or not token
            or isinstance(expires_in, bool)
            or not isinstance(expires_in, (int, float))
            or expires_in <= 0
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
        ):
            raise StudioTokenError("studio_token_response_invalid", retryable=False)

        self._token = token
        self._expires_at = self._clock() + float(expires_in)
        return token
