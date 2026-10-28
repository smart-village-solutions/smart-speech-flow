"""The lifespan's one runtime client refreshes the content the browser routes serve."""

from __future__ import annotations

from prometheus_client import CollectorRegistry

from services.api_gateway.app import _build_studio
from services.api_gateway.studio_content import ContentRecordingFetcher
from services.api_gateway.studio_content_metrics import StudioContentMetrics
from services.api_gateway.studio_policy_reads import CountedPolicyReads, StudioPolicyReadMetrics


class Tokens:
    async def get_token(self) -> str:
        return "t"


def test_every_policy_read_goes_through_the_content_cache(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "http://studio-mock:8000")

    studio = _build_studio(
        Tokens(),
        StudioContentMetrics(CollectorRegistry()),
        StudioPolicyReadMetrics(CollectorRegistry()),
    )

    assert studio.runtime_flow is not None
    assert isinstance(studio.runtime_flow.client, ContentRecordingFetcher)
    # Each stage's reads are counted; the flow's own client stays the uncounted one.
    assert isinstance(studio.runtime_flow.reads("activation"), CountedPolicyReads)
    # The service records its own reads; only policy reads go through the wrapper.
    assert studio.content._runtime is studio.runtime_flow.client._inner
    assert studio.content._installation is not None


def test_without_studio_settings_nothing_reads_studio(monkeypatch) -> None:
    monkeypatch.delenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", raising=False)

    studio = _build_studio(
        None,
        StudioContentMetrics(CollectorRegistry()),
        StudioPolicyReadMetrics(CollectorRegistry()),
    )

    assert studio.runtime_flow is None
    assert studio.content._runtime is None and studio.content._installation is None
