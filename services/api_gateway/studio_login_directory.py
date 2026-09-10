"""Bounded in-memory cache for the validated Studio login directory."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol

from fastapi import HTTPException, status

from .studio_login_directory_client import StudioLoginDirectory, StudioLoginDirectoryClient
from .studio_runtime_token import StudioRuntimeTokenProvider, StudioTokenConfig, StudioTokenError


class LoginDirectoryFetcher(Protocol):
    """Boundary implemented by the validated Studio directory client."""

    async def fetch(self, correlation_id: str) -> StudioLoginDirectory:
        raise NotImplementedError


class StudioLoginDirectoryConfigurationError(RuntimeError):
    """Safe failure raised when the directory dependency cannot be configured."""


class StudioLoginDirectoryService:
    """Reuse a validated directory for a bounded period within one process."""

    def __init__(
        self,
        client: LoginDirectoryFetcher,
        *,
        cache_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 1 <= cache_seconds <= 300:
            raise ValueError("cache_seconds must be between 1 and 300")
        self._client = client
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._directory: StudioLoginDirectory | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[StudioLoginDirectory] | None = None

    async def get(self, correlation_id: str) -> StudioLoginDirectory:
        """Return a current directory, refreshing it once for concurrent callers."""
        if self._is_current():
            assert self._directory is not None
            return self._directory

        async with self._lock:
            if self._is_current():
                assert self._directory is not None
                return self._directory
            refresh_task = self._refresh_task
            if refresh_task is None or refresh_task.done():
                refresh_task = asyncio.create_task(self._refresh(correlation_id))
                self._refresh_task = refresh_task

        try:
            return await asyncio.shield(refresh_task)
        finally:
            if refresh_task.done():
                async with self._lock:
                    if self._refresh_task is refresh_task:
                        self._refresh_task = None

    def _is_current(self) -> bool:
        return self._directory is not None and self._clock() < self._expires_at

    async def _refresh(self, correlation_id: str) -> StudioLoginDirectory:
        directory = await self._client.fetch(correlation_id)
        self._directory = directory
        self._expires_at = self._clock() + self._cache_seconds
        return directory


@lru_cache(maxsize=1)
def _build_studio_login_directory_service() -> StudioLoginDirectoryService:
    """Construct the process-local service from explicit environment settings."""
    base_url = os.getenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "").strip()
    try:
        cache_seconds = float(os.getenv("STUDIO_LOGIN_DIRECTORY_CACHE_SECONDS", "60"))
        timeout_seconds = float(os.getenv("STUDIO_LOGIN_DIRECTORY_TIMEOUT_SECONDS", "5"))
        if not 1 <= cache_seconds <= 300 or not 0 < timeout_seconds <= 30:
            raise ValueError
        token_provider = StudioRuntimeTokenProvider(StudioTokenConfig.from_env())
        client = StudioLoginDirectoryClient(
            base_url,
            token_provider,
            timeout_seconds=timeout_seconds,
        )
        return StudioLoginDirectoryService(
            client,
            cache_seconds=cache_seconds,
        )
    except (StudioTokenError, ValueError):
        raise StudioLoginDirectoryConfigurationError(
            "studio_login_directory_configuration_invalid"
        ) from None


def get_studio_login_directory_service() -> StudioLoginDirectoryService:
    """Provide the singleton service or a neutral dependency-boundary failure."""
    try:
        return _build_studio_login_directory_service()
    except StudioLoginDirectoryConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The login directory is temporarily unavailable",
        ) from None
