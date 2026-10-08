"""One app's Studio collaborators, wired one way for the lifespan and the contract suite.

Session create, activation and the persistence gate read through the content
cache's recording fetcher, so every policy read refreshes display content. The
content routes read the same client directly and record what they read once.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry

from .runtime_policy import RuntimePolicyGate
from .runtime_policy_metrics import RuntimePolicyMetrics
from .studio_content import ContentRecordingFetcher, StudioContentCache
from .studio_content_metrics import StudioContentMetrics
from .studio_content_service import (
    DEFAULT_CACHE_SECONDS,
    InstallationFetcher,
    StudioContentService,
)
from .studio_runtime_flow import RuntimeConfigurationFetcher, StudioRuntimeFlow


@dataclass(frozen=True, slots=True)
class StudioWiring:
    # Both None when Studio is unconfigured: no gate refuses every write.
    runtime_flow: StudioRuntimeFlow | None
    runtime_policy: RuntimePolicyGate | None
    content: StudioContentService


def wire_studio(
    runtime_client: RuntimeConfigurationFetcher | None,
    installation_client: InstallationFetcher | None,
    cache: StudioContentCache,
    *,
    policy_registry: CollectorRegistry,
    content_metrics: StudioContentMetrics,
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
        return StudioWiring(None, None, content)
    runtime = ContentRecordingFetcher(runtime_client, cache)
    gate = RuntimePolicyGate(runtime, metrics=RuntimePolicyMetrics(policy_registry))
    return StudioWiring(StudioRuntimeFlow(runtime), gate, content)
