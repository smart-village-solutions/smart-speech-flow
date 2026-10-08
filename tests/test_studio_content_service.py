"""Display reads: brief reuse, one shared live read, stale content on Studio failure."""

from __future__ import annotations

import asyncio

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.studio_content import StudioContentCache
from services.api_gateway.studio_content_metrics import StudioContentMetrics
from services.api_gateway.studio_content_service import (
    ContentUnavailable,
    StudioContentService,
    content_cache_seconds,
    installation_client_from_environment,
)
from services.api_gateway.studio_installation_client import StudioInstallationClientError
from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2ClientError
from services.api_gateway.studio_v2 import (
    parse_installation_content_v2,
    parse_runtime_configuration_v2,
)
from services.studio_mock import contract_fixtures

TENANT = "tenant-kassel"
FETCH = "ssf_studio_content_fetch_total"
STALENESS = "ssf_studio_content_staleness_seconds"
DOWN = StudioRuntimeV2ClientError("studio_runtime_network_error", retryable=True)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def read(tenant_id: str = TENANT, *, scenario: str | None = None, seed: str = ""):
    body = contract_fixtures.runtime_configuration_v2(tenant_id, scenario)
    if seed:
        body["configurationRevision"] = "sha256:" + seed * 64
    return parse_runtime_configuration_v2(body, expected_tenant_id=tenant_id)


class Studio:
    """A scripted Studio: the next outcomes, then the last one forever."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.gate: asyncio.Event | None = None

    async def _next(self):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def fetch(self, *arguments):
        return await self._next()


def service(runtime=None, installation=None, clock=None):
    registry = CollectorRegistry()
    cache = StudioContentCache(clock=clock or Clock())
    content = StudioContentService(
        cache,
        runtime=runtime,
        installation=installation,
        metrics=StudioContentMetrics(registry),
        cache_seconds=60,
    )
    return content, cache, registry


def answered(registry, endpoint: str, outcome: str) -> float:
    return registry.get_sample_value(FETCH, {"endpoint": endpoint, "outcome": outcome})


async def test_content_younger_than_the_cache_period_needs_no_read() -> None:
    clock = Clock()
    studio = Studio(read())
    content, cache, registry = service(studio, clock=clock)
    cache.record(read())
    clock.now += 59

    tenant = await content.tenant_content(TENANT, "c", endpoint="staff_content")

    assert tenant.revision == read().policy.configuration_revision
    assert studio.calls == 0
    assert answered(registry, "staff_content", "cached") == 1
    assert registry.get_sample_value(STALENESS, {"endpoint": "staff_content"}) == 59


async def test_older_content_makes_one_live_read_for_all_concurrent_callers() -> None:
    clock = Clock()
    studio = Studio(read(seed="2"))
    studio.gate = asyncio.Event()
    content, cache, registry = service(studio, clock=clock)
    cache.record(read(seed="1"))
    clock.now += 61

    waiting = [
        asyncio.create_task(content.tenant_content(TENANT, "c", endpoint="guest_languages"))
        for _ in range(5)
    ]
    await asyncio.sleep(0)
    studio.gate.set()
    results = await asyncio.gather(*waiting)

    assert studio.calls == 1
    assert {result.revision for result in results} == {"sha256:" + "2" * 64}
    assert answered(registry, "guest_languages", "live") == 5


async def test_studio_failure_serves_the_last_known_content() -> None:
    clock = Clock()
    content, cache, registry = service(Studio(DOWN), clock=clock)
    cache.record(read())
    clock.now += 600

    tenant = await content.tenant_content(TENANT, "c", endpoint="staff_content")

    assert tenant.revision == read().policy.configuration_revision
    assert answered(registry, "staff_content", "stale") == 1
    assert registry.get_sample_value(STALENESS, {"endpoint": "staff_content"}) == 600


async def test_nothing_ever_read_and_studio_down_is_unavailable() -> None:
    content, _, registry = service(Studio(DOWN))

    with pytest.raises(ContentUnavailable):
        await content.tenant_content(TENANT, "c", endpoint="staff_content")

    assert answered(registry, "staff_content", "unavailable") == 1


async def test_without_studio_settings_content_is_unavailable() -> None:
    content, _, _ = service(None, None)

    with pytest.raises(ContentUnavailable):
        await content.tenant_content(TENANT, "c", endpoint="staff_content")
    with pytest.raises(ContentUnavailable):
        await content.installation_content("c")
    guest = await content.guest_content(TENANT, "c")
    assert (guest.mode, guest.content) == ("unknown", None)


async def test_a_new_revision_reaches_later_reads() -> None:
    clock = Clock()
    content, cache, _ = service(Studio(read(seed="9")), clock=clock)
    cache.record(read(seed="1"))
    clock.now += 61

    await content.tenant_content(TENANT, "c", endpoint="staff_content")
    clock.now += 1
    tenant = await content.tenant_content(TENANT, "c", endpoint="staff_content")

    assert tenant.revision == "sha256:" + "9" * 64


async def test_the_guest_mode_comes_from_each_live_read_never_the_cache() -> None:
    ask = read()
    disabled = parse_runtime_configuration_v2(
        {
            **contract_fixtures.runtime_configuration_v2(TENANT, "storage-disabled"),
            "configurationRevision": ask.policy.configuration_revision,
        },
        expected_tenant_id=TENANT,
    )
    studio = Studio(ask, disabled)
    content, _, registry = service(studio)

    first = await content.guest_content(TENANT, "c")
    second = await content.guest_content(TENANT, "c")

    assert (first.mode, second.mode) == ("ask", "disabled")
    assert studio.calls == 2
    assert answered(registry, "guest_content", "live") == 2


async def test_a_failed_guest_read_reports_unknown_with_stale_content() -> None:
    content, cache, registry = service(Studio(DOWN))
    cache.record(read())

    guest = await content.guest_content(TENANT, "c")

    assert guest.mode == "unknown"
    assert guest.content is not None and "en" in guest.content.guest_languages
    assert answered(registry, "guest_content", "stale") == 1


async def test_a_failed_guest_read_with_nothing_cached_reports_unknown_alone() -> None:
    content, _, registry = service(Studio(DOWN))

    guest = await content.guest_content(TENANT, "c")

    assert (guest.mode, guest.content) == ("unknown", None)
    assert answered(registry, "guest_content", "unavailable") == 1


async def test_a_read_naming_another_tenant_is_not_served() -> None:
    content, _, _ = service(Studio(read("tenant-fulda")))

    guest = await content.guest_content(TENANT, "c")

    assert (guest.mode, guest.content) == ("unknown", None)


async def test_installation_content_is_cached_refreshed_and_stale_on_failure() -> None:
    clock = Clock()
    installation = parse_installation_content_v2(contract_fixtures.installation_content_v2(None))
    studio = Studio(
        installation,
        StudioInstallationClientError("studio_installation_network_error", retryable=True),
    )
    content, _, registry = service(installation=studio, clock=clock)

    live = await content.installation_content("c")
    clock.now += 30
    cached = await content.installation_content("c")
    clock.now += 31
    stale = await content.installation_content("c")

    assert live is cached is stale
    assert studio.calls == 2
    assert [answered(registry, "installation", o) for o in ("live", "cached", "stale")] == [1, 1, 1]


async def test_installation_never_loaded_is_unavailable() -> None:
    content, _, registry = service(
        installation=Studio(
            StudioInstallationClientError("studio_installation_network_error", retryable=True)
        )
    )

    with pytest.raises(ContentUnavailable):
        await content.installation_content("c")
    assert answered(registry, "installation", "unavailable") == 1


def test_environment_defaults_and_fallbacks(monkeypatch) -> None:
    class Tokens:
        async def get_token(self) -> str:
            return "t"

    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "http://studio-mock:8000")
    for raw, expected in (("", 60.0), ("15", 15.0), ("0", 60.0), ("nan", 60.0), ("x", 60.0)):
        monkeypatch.setenv("STUDIO_CONTENT_CACHE_SECONDS", raw)
        assert content_cache_seconds() == expected
    for raw, expected in (("", 3.0), ("1.5", 1.5), ("31", 3.0)):
        monkeypatch.setenv("STUDIO_INSTALLATION_CONTENT_TIMEOUT_SECONDS", raw)
        client = installation_client_from_environment(Tokens())
        assert client is not None and client.timeout_seconds == expected
    assert installation_client_from_environment(None) is None
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "")
    assert installation_client_from_environment(Tokens()) is None


async def test_after_a_failed_read_studio_is_left_alone_for_one_cache_period() -> None:
    clock = Clock()
    studio = Studio(DOWN, DOWN, read(seed="2"))
    content, cache, registry = service(studio, clock=clock)
    cache.record(read(seed="1"))
    clock.now += 61

    await content.tenant_content(TENANT, "c", endpoint="staff_content")
    clock.now += 59
    during = await content.tenant_content(TENANT, "c", endpoint="staff_content")
    reads_during_pause = studio.calls
    clock.now += 1
    await content.tenant_content(TENANT, "c", endpoint="staff_content")
    clock.now += 60
    after = await content.tenant_content(TENANT, "c", endpoint="staff_content")

    assert reads_during_pause == 1
    assert during.revision == "sha256:" + "1" * 64
    assert studio.calls == 3
    assert after.revision == "sha256:" + "2" * 64
    assert answered(registry, "staff_content", "stale") == 3


async def test_nothing_held_during_the_pause_is_unavailable_without_a_read() -> None:
    clock = Clock()
    installation = Studio(
        StudioInstallationClientError("studio_installation_network_error", retryable=True)
    )
    content, _, registry = service(installation=installation, clock=clock)

    for _ in range(3):
        with pytest.raises(ContentUnavailable):
            await content.installation_content("c")

    assert installation.calls == 1
    assert answered(registry, "installation", "unavailable") == 3


async def test_concurrent_guest_requests_share_one_live_read() -> None:
    studio = Studio(read())
    studio.gate = asyncio.Event()
    content, _, _ = service(studio)

    waiting = [asyncio.create_task(content.guest_content(TENANT, "c")) for _ in range(4)]
    await asyncio.sleep(0)
    studio.gate.set()
    results = await asyncio.gather(*waiting)

    assert studio.calls == 1
    assert {result.mode for result in results} == {"ask"}


async def test_guest_content_answers_unknown_at_once_while_studio_is_paused() -> None:
    clock = Clock()
    studio = Studio(DOWN, read())
    content, cache, _ = service(studio, clock=clock)
    cache.record(read())

    first = await content.guest_content(TENANT, "c")
    clock.now += 59
    paused = await content.guest_content(TENANT, "c")
    reads_while_paused = studio.calls
    clock.now += 1
    after = await content.guest_content(TENANT, "c")

    assert (first.mode, paused.mode, after.mode) == ("unknown", "unknown", "ask")
    assert reads_while_paused == 1
    assert paused.content is not None
    assert studio.calls == 2


async def test_a_failed_guest_read_pauses_display_reads_too() -> None:
    clock = Clock()
    studio = Studio(DOWN)
    content, cache, _ = service(studio, clock=clock)
    cache.record(read())
    clock.now += 61

    await content.guest_content(TENANT, "c")
    await content.tenant_content(TENANT, "c", endpoint="guest_languages")

    assert studio.calls == 1


async def test_guest_and_display_requests_share_one_live_read() -> None:
    clock = Clock()
    studio = Studio(read(seed="2"))
    studio.gate = asyncio.Event()
    content, cache, _ = service(studio, clock=clock)
    cache.record(read(seed="1"))
    clock.now += 61

    waiting = [
        asyncio.create_task(content.guest_content(TENANT, "c")),
        asyncio.create_task(content.tenant_content(TENANT, "c", endpoint="guest_languages")),
    ]
    await asyncio.sleep(0)
    studio.gate.set()
    guest, languages = await asyncio.gather(*waiting)

    assert studio.calls == 1
    assert guest.content is not None
    assert guest.content.revision == languages.revision == "sha256:" + "2" * 64


class FailingNewRevisions(StudioContentCache):
    """Holds what it already has; caching any further revision fails."""

    frozen = False

    def record(self, read):
        if self.frozen:
            raise RuntimeError("sanitiser defect")
        return super().record(read)


async def test_a_live_mode_is_never_paired_with_another_revisions_content() -> None:
    cache = FailingNewRevisions(clock=Clock())
    cache.record(read(seed="1"))
    cache.frozen = True
    disabled = read(scenario="storage-disabled", seed="2")
    content = StudioContentService(
        cache,
        runtime=Studio(disabled),
        installation=None,
        metrics=StudioContentMetrics(CollectorRegistry()),
    )

    guest = await content.guest_content(TENANT, "c")

    # Revision 1 asks the storage question; it must not sit beside "disabled".
    assert (guest.mode, guest.content) == ("disabled", None)


async def test_display_reads_fall_back_when_a_read_cannot_be_cached() -> None:
    clock = Clock()
    cache = FailingNewRevisions(clock=clock)
    cache.record(read(seed="1"))
    cache.frozen = True
    clock.now += 61
    content = StudioContentService(
        cache,
        runtime=Studio(read(seed="2")),
        installation=None,
        metrics=StudioContentMetrics(CollectorRegistry()),
    )

    tenant = await content.tenant_content(TENANT, "c", endpoint="guest_languages")

    assert tenant.revision == "sha256:" + "1" * 64
