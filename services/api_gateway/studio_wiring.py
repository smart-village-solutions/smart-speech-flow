"""One app's Studio collaborators, wired one way for the lifespan and the contract suite.

Session create and activation read through the content cache's recording
fetcher, so every policy read refreshes display content. The
content routes read the same client directly and record what they read once.
"""

from __future__ import annotations

from dataclasses import dataclass

from .studio_content import ContentRecordingFetcher, StudioContentCache
from .studio_content_metrics import StudioContentMetrics
from .studio_content_service import (
    DEFAULT_CACHE_SECONDS,
    InstallationFetcher,
    StudioContentService,
)
from .studio_policy_reads import StudioPolicyReadMetrics
from .studio_runtime_flow import RuntimeConfigurationFetcher, StudioRuntimeFlow


@dataclass(frozen=True, slots=True)
class StudioWiring:
    # None when Studio is unconfigured.
    runtime_flow: StudioRuntimeFlow | None
    content: StudioContentService


def wire_studio(
    runtime_client: RuntimeConfigurationFetcher | None,
    installation_client: InstallationFetcher | None,
    cache: StudioContentCache,
    *,
    content_metrics: StudioContentMetrics,
    policy_reads: StudioPolicyReadMetrics,
    cache_seconds: float = DEFAULT_CACHE_SECONDS,
) -> StudioWiring:
    # The service records its own reads; the recording fetcher serves the policy reads.
    content = StudioContentService(
        cache,
        runtime=runtime_client,
        installation=installation_client,
        metrics=content_metrics,
        cache_seconds=cache_seconds,
    )
    if runtime_client is None:
        return StudioWiring(None, content)
    runtime = ContentRecordingFetcher(runtime_client, cache)
    return StudioWiring(StudioRuntimeFlow(runtime, policy_reads=policy_reads), content)
