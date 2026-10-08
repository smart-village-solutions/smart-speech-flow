"""One app's Studio collaborators, wired one way for the lifespan and the contract suite.

The runtime client sits behind the content cache's recording fetcher, and that
one fetcher serves session create, activation, the persistence gate and the
content routes. Every policy read therefore refreshes display content.
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
    runtime = None if runtime_client is None else ContentRecordingFetcher(runtime_client, cache)
    content = StudioContentService(
        cache,
        runtime=runtime,
        installation=installation_client,
        metrics=content_metrics,
        cache_seconds=cache_seconds,
    )
    if runtime is None:
        return StudioWiring(None, None, content)
    gate = RuntimePolicyGate(runtime, metrics=RuntimePolicyMetrics(policy_registry))
    return StudioWiring(StudioRuntimeFlow(runtime), gate, content)
