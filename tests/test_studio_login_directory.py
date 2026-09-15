"""Behavior tests for the bounded Studio login-directory cache."""

import asyncio

import pytest
from pydantic import ValidationError

from services.api_gateway.studio_login_directory import StudioLoginDirectoryService
from services.api_gateway.studio_login_directory_client import (
    StudioLoginDirectory,
    StudioLoginDirectoryClientError,
)

REVISION_A = f"sha256:{'a' * 64}"
REVISION_B = f"sha256:{'b' * 64}"


def directory(
    revision: str = REVISION_A,
    *,
    tenants: list[dict[str, str]] | None = None,
) -> StudioLoginDirectory:
    return StudioLoginDirectory.model_validate(
        {
            "contractVersion": "1.0",
            "directoryRevision": revision,
            "tenants": (
                tenants
                if tenants is not None
                else [
                    {
                        "id": "tenant-kassel",
                        "displayName": "Stadt Kassel",
                        "realm": "kassel-ssf-2025",
                    }
                ]
            ),
        }
    )


class MutableClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class StubDirectoryClient:
    def __init__(self, *outcomes: StudioLoginDirectory | Exception) -> None:
        self.outcomes = list(outcomes)
        self.correlation_ids: list[str] = []

    async def fetch(self, correlation_id: str) -> StudioLoginDirectory:
        self.correlation_ids.append(correlation_id)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_first_request_fetches_and_caches_the_validated_directory() -> None:
    expected = directory()
    client = StubDirectoryClient(expected)
    service = StudioLoginDirectoryService(client, cache_seconds=60, clock=MutableClock())

    result = await service.get("correlation-1")

    assert result is expected
    assert client.correlation_ids == ["correlation-1"]


@pytest.mark.asyncio
async def test_request_within_ttl_reuses_the_cached_directory() -> None:
    clock = MutableClock()
    expected = directory()
    client = StubDirectoryClient(expected)
    service = StudioLoginDirectoryService(client, cache_seconds=60, clock=clock)

    first = await service.get("correlation-1")
    clock.now = 59.999
    second = await service.get("correlation-2")

    assert first is expected
    assert second is expected
    assert client.correlation_ids == ["correlation-1"]


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_refresh() -> None:
    clock = MutableClock()
    original = directory()
    refreshed = directory(REVISION_B)
    fetch_started = asyncio.Event()
    allow_fetch = asyncio.Event()

    class BlockingClient:
        def __init__(self) -> None:
            self.correlation_ids: list[str] = []

        async def fetch(self, correlation_id: str) -> StudioLoginDirectory:
            self.correlation_ids.append(correlation_id)
            if len(self.correlation_ids) == 1:
                return original
            fetch_started.set()
            await allow_fetch.wait()
            return refreshed

    client = BlockingClient()
    service = StudioLoginDirectoryService(client, cache_seconds=60, clock=clock)

    assert await service.get("correlation-1") is original
    clock.now = 60

    first_task = asyncio.create_task(service.get("correlation-2"))
    await fetch_started.wait()
    second_task = asyncio.create_task(service.get("correlation-3"))
    await asyncio.sleep(0)
    allow_fetch.set()

    first_result, second_result = await asyncio.gather(first_task, second_task)

    assert first_result is refreshed
    assert second_result is refreshed
    assert client.correlation_ids == ["correlation-1", "correlation-2"]


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_failed_refresh_then_a_later_call_retries() -> None:
    clock = MutableClock()
    original = directory()
    refreshed = directory(REVISION_B)
    failure = StudioLoginDirectoryClientError(
        "studio_login_directory_network_error", retryable=True
    )
    fetch_started = asyncio.Event()
    allow_failure = asyncio.Event()

    class FailingRefreshClient:
        def __init__(self) -> None:
            self.correlation_ids: list[str] = []

        async def fetch(self, correlation_id: str) -> StudioLoginDirectory:
            self.correlation_ids.append(correlation_id)
            if len(self.correlation_ids) == 1:
                return original
            if len(self.correlation_ids) == 2:
                fetch_started.set()
                await allow_failure.wait()
                raise failure
            return refreshed

    client = FailingRefreshClient()
    service = StudioLoginDirectoryService(client, cache_seconds=60, clock=clock)

    assert await service.get("correlation-1") is original
    clock.now = 60

    first_task = asyncio.create_task(service.get("correlation-2"))
    await fetch_started.wait()
    second_task = asyncio.create_task(service.get("correlation-3"))
    await asyncio.sleep(0)
    allow_failure.set()

    first_result, second_result = await asyncio.gather(
        first_task, second_task, return_exceptions=True
    )

    assert first_result is failure
    assert second_result is failure
    assert client.correlation_ids == ["correlation-1", "correlation-2"]

    assert await service.get("correlation-4") is refreshed
    assert client.correlation_ids == [
        "correlation-1",
        "correlation-2",
        "correlation-4",
    ]


@pytest.mark.asyncio
async def test_request_at_ttl_expiry_refreshes_the_directory() -> None:
    clock = MutableClock()
    original = directory()
    refreshed = directory(REVISION_B)
    client = StubDirectoryClient(original, refreshed)
    service = StudioLoginDirectoryService(client, cache_seconds=60, clock=clock)

    assert await service.get("correlation-1") is original
    clock.now = 60

    assert await service.get("correlation-2") is refreshed
    assert client.correlation_ids == ["correlation-1", "correlation-2"]


@pytest.mark.asyncio
async def test_valid_empty_directory_is_cached() -> None:
    clock = MutableClock()
    empty = directory(tenants=[])
    client = StubDirectoryClient(empty)
    service = StudioLoginDirectoryService(client, cache_seconds=60, clock=clock)

    assert (await service.get("correlation-1")).tenants == ()
    clock.now = 1
    assert (await service.get("correlation-2")).tenants == ()
    assert client.correlation_ids == ["correlation-1"]


@pytest.mark.asyncio
async def test_cached_directory_cannot_be_mutated_by_a_consumer() -> None:
    expected = directory()
    client = StubDirectoryClient(expected)
    service = StudioLoginDirectoryService(client, cache_seconds=60, clock=MutableClock())

    first = await service.get("correlation-1")

    with pytest.raises(AttributeError):
        getattr(first.tenants, "clear")()
    with pytest.raises(ValidationError):
        first.tenants[0].display_name = "Poisoned tenant"

    second = await service.get("correlation-2")
    assert second.tenants[0].display_name == "Stadt Kassel"
    assert client.correlation_ids == ["correlation-1"]


@pytest.mark.asyncio
async def test_failed_refresh_does_not_serve_or_extend_expired_data() -> None:
    clock = MutableClock()
    original = directory()
    refreshed = directory(REVISION_B)
    failure = StudioLoginDirectoryClientError(
        "studio_login_directory_network_error", retryable=True
    )
    client = StubDirectoryClient(original, failure, refreshed)
    service = StudioLoginDirectoryService(client, cache_seconds=60, clock=clock)

    assert await service.get("correlation-1") is original
    clock.now = 60

    with pytest.raises(StudioLoginDirectoryClientError) as caught:
        await service.get("correlation-2")

    assert caught.value is failure
    assert await service.get("correlation-3") is refreshed
    assert client.correlation_ids == [
        "correlation-1",
        "correlation-2",
        "correlation-3",
    ]
