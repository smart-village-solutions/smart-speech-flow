"""Studio display content held by revision: sanitised once, never the storage mode."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from services.api_gateway.studio_content import (
    MAX_REVISIONS_PER_TENANT,
    ContentRecordingFetcher,
    StudioContentCache,
    TenantContent,
)
from services.api_gateway.studio_v2 import (
    parse_installation_content_v2,
    parse_runtime_configuration_v2,
)
from services.studio_mock import contract_fixtures
from tests.runtime_policy_helpers import RecordingClient
from tests.studio_v2_fixtures import INSTALLATION, KASSEL, load_fixture

ATTACK = '<p onclick="evil()">kept<script>evil()</script><img src=x onerror="evil()"></p>'
TENANT = "tenant-kassel"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _poison_html(node: Any) -> int:
    """Replace every `*Html` string in a Studio body with ATTACK; return how many."""
    count = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("Html") and isinstance(value, str):
                node[key] = ATTACK
                count += 1
            else:
                count += _poison_html(value)
    elif isinstance(node, list):
        count += sum(_poison_html(item) for item in node)
    return count


def _html_fields(node: Any) -> list[str]:
    """Every `*_html` string reachable from cached content."""
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return [v for f in dataclasses.fields(node) for v in _html_fields(getattr(node, f.name))]
    if hasattr(node, "model_fields"):
        found = []
        for name in type(node).model_fields:
            value = getattr(node, name)
            if name.endswith("_html") and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_html_fields(value))
        return found
    if isinstance(node, (list, tuple)):
        return [v for item in node for v in _html_fields(item)]
    if hasattr(node, "values"):
        return [v for item in node.values() for v in _html_fields(item)]
    return []


def kassel_read(revision_seed: str = "", *, mode_scenario: str | None = None):
    body = contract_fixtures.runtime_configuration_v2(TENANT, mode_scenario)
    if revision_seed:
        body["configurationRevision"] = "sha256:" + revision_seed * 64
    return parse_runtime_configuration_v2(body, expected_tenant_id=TENANT)


def test_every_html_field_is_sanitised_at_insert() -> None:
    body = load_fixture(KASSEL)
    poisoned = _poison_html(body)
    read = parse_runtime_configuration_v2(body, expected_tenant_id=body["tenant"]["id"])

    content = StudioContentCache().record(read)

    html = _html_fields(content)
    assert len(html) == poisoned
    for fragment in html:
        assert "kept" in fragment
        assert "<script" not in fragment
        assert "onclick" not in fragment
        assert "onerror" not in fragment
        assert "<img" not in fragment


def test_every_installation_html_field_is_sanitised() -> None:
    body = load_fixture(INSTALLATION)
    poisoned = _poison_html(body)

    content = StudioContentCache().record_installation(parse_installation_content_v2(body))

    html = _html_fields(content)
    assert len(html) == poisoned
    assert all("<script" not in fragment and "onclick" not in fragment for fragment in html)


def test_cached_content_has_no_storage_mode_and_no_display_name() -> None:
    names = {field.name for field in dataclasses.fields(TenantContent)}

    assert names == {"revision", "time_zone", "branding", "staff", "guest_languages"}
    content = StudioContentCache().record(kassel_read())
    with pytest.raises((AttributeError, TypeError)):
        content.mode = "ask"  # type: ignore[misc, attr-defined]
    assert "Kassel Test Municipality" not in repr(content)


def test_guest_languages_are_keyed_by_ssf_code_in_ssf_order() -> None:
    skipped: list[str] = []

    content = StudioContentCache(on_skip=skipped.append).record(kassel_read())

    assert list(content.guest_languages) == ["en", "ar", "tr", "ku"]
    assert content.guest_languages["ku"].locale == "kmr"
    assert content.guest_languages["ar"].icon is None
    assert skipped == ["unsupported"]


def test_a_known_revision_is_reused_and_reports_no_second_skip() -> None:
    skipped: list[str] = []
    cache = StudioContentCache(on_skip=skipped.append)

    first = cache.record(kassel_read())
    second = cache.record(kassel_read())

    assert second is first
    assert skipped == ["unsupported"]


def test_the_pointer_follows_the_latest_read_and_ages() -> None:
    clock = Clock()
    cache = StudioContentCache(clock=clock)
    cache.record(kassel_read("1"))
    clock.now += 5
    cache.record(kassel_read("2"))
    clock.now += 7

    latest = cache.latest(TENANT)

    assert latest is not None
    assert latest.content.revision == "sha256:" + "2" * 64
    assert latest.age_seconds == 7
    assert cache.latest("tenant-fulda") is None


def test_at_most_four_revisions_are_kept_per_tenant() -> None:
    cache = StudioContentCache()
    for seed in "12345":
        cache.record(kassel_read(seed))

    assert MAX_REVISIONS_PER_TENANT == 4
    assert cache.at_revision(TENANT, "sha256:" + "1" * 64) is None
    for seed in "2345":
        assert cache.at_revision(TENANT, "sha256:" + seed * 64) is not None


def test_installation_is_reused_for_its_revision_and_ages() -> None:
    clock = Clock()
    cache = StudioContentCache(clock=clock)
    installation = parse_installation_content_v2(load_fixture(INSTALLATION))

    first = cache.record_installation(installation)
    clock.now += 3

    assert cache.record_installation(installation) is first
    clock.now += 2
    cached = cache.installation()
    assert cached is not None and cached.content is first and cached.age_seconds == 2


async def test_the_recording_fetcher_refreshes_the_cache_and_passes_the_read_on() -> None:
    read = kassel_read()
    cache = StudioContentCache()

    returned = await ContentRecordingFetcher(RecordingClient(read), cache).fetch(TENANT, "c")

    assert returned is read
    latest = cache.latest(TENANT)
    assert latest is not None and latest.content.revision == read.policy.configuration_revision


async def test_a_caching_failure_never_fails_the_policy_read(caplog) -> None:
    class BrokenCache(StudioContentCache):
        def record(self, read):
            raise RuntimeError("Kassel Test Municipality")

    read = kassel_read()

    returned = await ContentRecordingFetcher(RecordingClient(read), BrokenCache()).fetch(
        TENANT, "c"
    )

    assert returned is read
    assert "Studio content not cached (RuntimeError)" in caplog.text
    assert "Kassel Test Municipality" not in caplog.text


async def test_a_failed_read_records_nothing() -> None:
    cache = StudioContentCache()

    with pytest.raises(LookupError):
        await ContentRecordingFetcher(RecordingClient(LookupError()), cache).fetch(TENANT, "c")

    assert cache.latest(TENANT) is None
