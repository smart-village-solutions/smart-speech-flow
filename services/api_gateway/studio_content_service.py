"""Studio content for the browser routes: brief reuse, one shared refresh, stale on failure.

Display routes fail open to the last content read, and the browser falls back
to bundled copy when there is none. The storage mode fails to `unknown`.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal, Protocol

from .studio_content import Cached, StudioContentCache, TenantContent
from .studio_content_metrics import ContentEndpoint, ContentOutcome, StudioContentMetrics
from .studio_installation_client import StudioInstallationClient
from .studio_runtime_flow import RuntimeConfigurationFetcher
from .studio_runtime_token import StudioRuntimeTokenProvider, StudioTokenError
from .studio_runtime_v2_client import StudioRuntimeV2ClientError
from .studio_v1 import StudioV1ClientError
from .studio_v2 import InstallationContent, RuntimeRead

logger = logging.getLogger(__name__)

StorageMode = Literal["ask", "disabled", "unknown"]
DEFAULT_CACHE_SECONDS = 60.0
DEFAULT_INSTALLATION_TIMEOUT_SECONDS = 3.0


class ContentUnavailable(LookupError):
    """Studio cannot be read now, and nothing was read before."""


class InstallationFetcher(Protocol):
    async def fetch(self, correlation_id: str) -> InstallationContent:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class GuestContent:
    """The live storage mode, and the content to show beside it."""

    mode: StorageMode
    content: TenantContent | None


class _SingleFlight[K, V]:
    """At most one read per key in flight; concurrent callers all await that one."""

    def __init__(self) -> None:
        self._running: dict[K, asyncio.Task[V]] = {}

    async def run(self, key: K, read: Callable[[], Coroutine[Any, Any, V]]) -> V:
        task = self._running.get(key)
        if task is None:
            task = asyncio.create_task(read())
            self._running[key] = task
            task.add_done_callback(partial(self._finished, key))
        # Shielded: one caller giving up must not cancel the read the others await.
        return await asyncio.shield(task)

    def _finished(self, key: K, task: asyncio.Task[V]) -> None:
        if self._running.get(key) is task:
            del self._running[key]
        if not task.cancelled():
            # Retrieved, so a read every caller abandoned does not log as unhandled.
            task.exception()


class _ContentNotCached(Exception):
    """A read arrived but its content could not be cached; it counts as a failed read."""

    code = "studio_content_not_cached"


# Every Studio client and the token provider raise only these; anything else is a defect.
_STUDIO_FAILURES = (StudioV1ClientError, StudioTokenError, _ContentNotCached)
_NEVER = float("-inf")


class StudioContentService:
    """Answer display reads from the cache, refreshing it from Studio when it has aged.

    After a failed read, display reads answer from what is held, without waiting
    on Studio again, until one cache period has passed. The storage mode has no
    such pause: every guest content request reads it live.
    """

    def __init__(
        self,
        cache: StudioContentCache,
        *,
        runtime: RuntimeConfigurationFetcher | None,
        installation: InstallationFetcher | None,
        metrics: StudioContentMetrics,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
    ) -> None:
        self._cache = cache
        self._clock = cache.clock
        self._runtime = runtime
        self._installation = installation
        self._metrics = metrics
        self._cache_seconds = cache_seconds
        self._tenant_reads: _SingleFlight[str, TenantContent] = _SingleFlight()
        self._installation_reads: _SingleFlight[None, InstallationContent] = _SingleFlight()
        # Concurrent guest requests share one live read; nothing of it is kept.
        self._guest_reads: _SingleFlight[str, GuestContent] = _SingleFlight()
        self._tenant_retry_after: dict[str, float] = {}
        self._installation_retry_after = _NEVER

    async def installation_content(self, correlation_id: str) -> InstallationContent:
        """Raises ContentUnavailable when nothing was ever read and Studio fails now."""
        endpoint: ContentEndpoint = "installation"
        cached = self._cache.installation()
        if cached is not None and cached.age_seconds < self._cache_seconds:
            return self._answer(endpoint, "cached", cached)
        if self._installation is not None and self._clock() >= self._installation_retry_after:
            read = partial(self._read_installation, self._installation, correlation_id)
            try:
                content = await self._installation_reads.run(None, read)
            except _STUDIO_FAILURES as error:
                _log_failure(endpoint, error)
                self._installation_retry_after = self._clock() + self._cache_seconds
            else:
                self._installation_retry_after = _NEVER
                return self._answer(endpoint, "live", Cached(content, 0.0))
        return self._fallback(endpoint, self._cache.installation())

    async def tenant_content(
        self, tenant_id: str, correlation_id: str, *, endpoint: ContentEndpoint
    ) -> TenantContent:
        """Raises ContentUnavailable when nothing was ever read and Studio fails now."""
        cached = self._cache.latest(tenant_id)
        if cached is not None and cached.age_seconds < self._cache_seconds:
            return self._answer(endpoint, "cached", cached)
        retry_after = self._tenant_retry_after.get(tenant_id, _NEVER)
        if self._runtime is not None and self._clock() >= retry_after:
            read = partial(self._read_tenant, self._runtime, tenant_id, correlation_id)
            try:
                content = await self._tenant_reads.run(tenant_id, read)
            except _STUDIO_FAILURES as error:
                _log_failure(endpoint, error)
                self._tenant_retry_after[tenant_id] = self._clock() + self._cache_seconds
            else:
                self._tenant_retry_after.pop(tenant_id, None)
                return self._answer(endpoint, "live", Cached(content, 0.0))
        return self._fallback(endpoint, self._cache.latest(tenant_id))

    async def guest_content(self, tenant_id: str, correlation_id: str) -> GuestContent:
        """The storage mode from a live read, never from the cache, and the content beside it."""
        endpoint: ContentEndpoint = "guest_content"
        if self._runtime is not None:
            read = partial(self._read_guest, self._runtime, tenant_id, correlation_id)
            try:
                guest = await self._guest_reads.run(tenant_id, read)
            except _STUDIO_FAILURES as error:
                _log_failure(endpoint, error)
            else:
                age = None if guest.content is None else 0.0
                self._metrics.answered(endpoint, "live", age)
                return guest
        try:
            return GuestContent("unknown", self._fallback(endpoint, self._cache.latest(tenant_id)))
        except ContentUnavailable:
            return GuestContent("unknown", None)

    async def _read_installation(
        self, installation: InstallationFetcher, correlation_id: str
    ) -> InstallationContent:
        return self._cache.record_installation(await installation.fetch(correlation_id))

    async def _read_tenant(
        self, runtime: RuntimeConfigurationFetcher, tenant_id: str, correlation_id: str
    ) -> TenantContent:
        return self._record(await runtime.fetch(tenant_id, correlation_id), tenant_id)

    async def _read_guest(
        self, runtime: RuntimeConfigurationFetcher, tenant_id: str, correlation_id: str
    ) -> GuestContent:
        read = _same_tenant(await runtime.fetch(tenant_id, correlation_id), tenant_id)
        # The mode was read either way; only the content beside it may fall back.
        content = self._cache.try_record(read)
        if content is None:
            latest = self._cache.latest(tenant_id)
            content = None if latest is None else latest.content
        return GuestContent(read.policy.mode, content)

    def _record(self, read: RuntimeRead, tenant_id: str) -> TenantContent:
        content = self._cache.try_record(_same_tenant(read, tenant_id))
        if content is None:
            raise _ContentNotCached
        return content

    def _answer[T](
        self, endpoint: ContentEndpoint, outcome: ContentOutcome, cached: Cached[T]
    ) -> T:
        self._metrics.answered(endpoint, outcome, cached.age_seconds)
        return cached.content

    def _fallback[T](self, endpoint: ContentEndpoint, cached: Cached[T] | None) -> T:
        if cached is None:
            self._metrics.answered(endpoint, "unavailable", None)
            raise ContentUnavailable
        return self._answer(endpoint, "stale", cached)


def _same_tenant(read: RuntimeRead, tenant_id: str) -> RuntimeRead:
    # The client checks this too; these routes serve the content, so they check
    # again rather than trust whichever fetcher they were given.
    if not hmac.compare_digest(read.policy.tenant_id.encode(), tenant_id.encode()):
        raise StudioRuntimeV2ClientError("studio_runtime_tenant_mismatch", retryable=False)
    return read


def _log_failure(
    endpoint: ContentEndpoint, error: StudioV1ClientError | StudioTokenError | _ContentNotCached
) -> None:
    logger.warning("Studio content read failed for %s (%s)", endpoint, error.code)


def _seconds(name: str, default: float, maximum: float) -> float:
    """A positive number of seconds up to `maximum`; anything else is the default."""
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if 0 < value <= maximum else default


def installation_client_from_environment(
    token_provider: StudioRuntimeTokenProvider | None,
) -> StudioInstallationClient | None:
    """The installation content client, or None when Studio is not configured."""
    if token_provider is None:
        return None
    try:
        return StudioInstallationClient(
            os.getenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "").strip(),
            token_provider.get_token,
            timeout_seconds=_seconds(
                "STUDIO_INSTALLATION_CONTENT_TIMEOUT_SECONDS",
                DEFAULT_INSTALLATION_TIMEOUT_SECONDS,
                30,
            ),
        )
    except ValueError:
        return None


def content_cache_seconds() -> float:
    """How long display content is reused before the next live read: positive, at most an hour."""
    return _seconds("STUDIO_CONTENT_CACHE_SECONDS", DEFAULT_CACHE_SECONDS, 3600)
