"""Studio content for the browser routes: brief reuse, one shared refresh, stale on failure.

Display routes fail open to the last content read, and the browser falls back
to bundled copy when there is none. The storage mode fails to `unknown`.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
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
from .studio_settings import seconds_setting, studio_base_url
from .studio_v1 import StudioV1ClientError
from .studio_v2 import InstallationContent

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


# Every Studio client and the token provider raise only these; anything else is a defect.
_STUDIO_FAILURES = (StudioV1ClientError, StudioTokenError)
_NEVER = float("-inf")


@dataclass(frozen=True, slots=True)
class _LiveRead:
    mode: Literal["ask", "disabled"]
    # None when this read could not be cached.
    content: TenantContent | None


class StudioContentService:
    """Answer display reads from the cache, refreshing it from Studio when it has aged.

    One live read per tenant at a time serves every route. After it fails,
    Studio is left alone for one cache period: display routes answer from what
    is held and the guest content route answers `unknown`, each without waiting.
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
        self._runtime_reads: _SingleFlight[str, _LiveRead] = _SingleFlight()
        self._installation_reads: _SingleFlight[None, InstallationContent] = _SingleFlight()
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
        live = await self._live_read(tenant_id, correlation_id, endpoint)
        if live is not None and live.content is not None:
            return self._answer(endpoint, "live", Cached(live.content, 0.0))
        return self._fallback(endpoint, self._cache.latest(tenant_id))

    async def guest_content(self, tenant_id: str, correlation_id: str) -> GuestContent:
        """The storage mode from a live read, never from the cache, and the content beside it."""
        endpoint: ContentEndpoint = "guest_content"
        live = await self._live_read(tenant_id, correlation_id, endpoint)
        if live is not None:
            # Content of another revision could contradict the live mode, so a
            # read that could not be cached answers with no Studio content at all.
            self._metrics.answered(endpoint, "live", None if live.content is None else 0.0)
            return GuestContent(live.mode, live.content)
        try:
            return GuestContent("unknown", self._fallback(endpoint, self._cache.latest(tenant_id)))
        except ContentUnavailable:
            return GuestContent("unknown", None)

    async def _live_read(
        self, tenant_id: str, correlation_id: str, endpoint: ContentEndpoint
    ) -> _LiveRead | None:
        """None when Studio is unconfigured, paused after a failure, or failing now."""
        runtime = self._runtime
        if runtime is None or self._clock() < self._tenant_retry_after.get(tenant_id, _NEVER):
            return None
        read = partial(self._read_runtime, runtime, tenant_id, correlation_id)
        try:
            live = await self._runtime_reads.run(tenant_id, read)
        except _STUDIO_FAILURES as error:
            _log_failure(endpoint, error)
            self._tenant_retry_after[tenant_id] = self._clock() + self._cache_seconds
            return None
        self._tenant_retry_after.pop(tenant_id, None)
        return live

    async def _read_installation(
        self, installation: InstallationFetcher, correlation_id: str
    ) -> InstallationContent:
        return self._cache.record_installation(await installation.fetch(correlation_id))

    async def _read_runtime(
        self, runtime: RuntimeConfigurationFetcher, tenant_id: str, correlation_id: str
    ) -> _LiveRead:
        read = await runtime.fetch(tenant_id, correlation_id)
        # The client checks this too; these routes serve the content, so they check
        # again rather than trust whichever fetcher they were given.
        if not hmac.compare_digest(read.policy.tenant_id.encode(), tenant_id.encode()):
            raise StudioRuntimeV2ClientError("studio_runtime_tenant_mismatch", retryable=False)
        return _LiveRead(read.policy.mode, self._cache.try_record(read))

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


def _log_failure(endpoint: ContentEndpoint, error: StudioV1ClientError | StudioTokenError) -> None:
    logger.warning("Studio content read failed for %s (%s)", endpoint, error.code)


def installation_client_from_environment(
    token_provider: StudioRuntimeTokenProvider | None,
) -> StudioInstallationClient | None:
    """The installation content client, or None when Studio is not configured."""
    if token_provider is None:
        return None
    try:
        return StudioInstallationClient(
            studio_base_url(),
            token_provider.get_token,
            timeout_seconds=seconds_setting(
                "STUDIO_INSTALLATION_CONTENT_TIMEOUT_SECONDS",
                DEFAULT_INSTALLATION_TIMEOUT_SECONDS,
                30,
            ),
        )
    except ValueError:
        return None


def content_cache_seconds() -> float:
    """How long display content is reused before the next live read: positive, at most an hour."""
    return seconds_setting("STUDIO_CONTENT_CACHE_SECONDS", DEFAULT_CACHE_SECONDS, 3600)
