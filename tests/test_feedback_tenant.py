"""The seam that makes the SVA Studio integration an adapter swap.

Sessions carry no tenant today. The feedback table has the column from its
first migration anyway, populated through this port, so when Studio lands the
change is one constructor rather than a migration and a backfill over rows
whose tenant nobody can reconstruct.
"""

import pytest

from services.api_gateway.feedback.tenant import (
    DEFAULT_TENANT_ENV,
    ConfiguredTenantResolver,
    TenantResolver,
)


async def test_it_resolves_the_configured_tenant() -> None:
    resolver = ConfiguredTenantResolver(tenant_id="tenant-a")

    assert await resolver.resolve("ABC12345") == "tenant-a"


async def test_every_session_resolves_to_the_same_tenant_for_now() -> None:
    """Single-tenant until Studio; two sessions must not diverge."""
    resolver = ConfiguredTenantResolver(tenant_id="tenant-a")

    assert await resolver.resolve("ABC12345") == await resolver.resolve("XYZ99999")


async def test_a_sessionless_submission_still_gets_a_tenant() -> None:
    """tenant_id is NOT NULL; the admin dashboard submits without a session."""
    resolver = ConfiguredTenantResolver(tenant_id="tenant-a")

    assert await resolver.resolve(None) == "tenant-a"


async def test_from_environment_reads_the_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEFAULT_TENANT_ENV, "kassel")

    resolver = ConfiguredTenantResolver.from_environment()

    assert await resolver.resolve(None) == "kassel"


async def test_from_environment_falls_back_to_a_named_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank tenant would violate the NOT NULL constraint at insert time."""
    monkeypatch.delenv(DEFAULT_TENANT_ENV, raising=False)

    resolver = ConfiguredTenantResolver.from_environment()

    assert await resolver.resolve(None) == "default"


async def test_a_blank_environment_value_does_not_become_an_empty_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEFAULT_TENANT_ENV, "   ")

    resolver = ConfiguredTenantResolver.from_environment()

    assert await resolver.resolve(None) == "default"


def test_the_configured_resolver_satisfies_the_port() -> None:
    """A future SessionTenantResolver must be substitutable for this one."""
    assert isinstance(ConfiguredTenantResolver(tenant_id="t"), TenantResolver)
