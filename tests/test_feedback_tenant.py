"""Where a feedback row's tenant comes from.

The feedback table has carried a tenant column from its first migration,
populated through this port. Since the tenant-isolation release a session knows
its tenant, and FeedbackService resolves the key holding it; SessionTenantResolver
maps that key, and the configured value survives only as the fallback for what
carries none.
"""

import pytest

from services.api_gateway.feedback.tenant import (
    DEFAULT_TENANT_ENV,
    ConfiguredTenantResolver,
    TenantResolver,
)


async def test_it_resolves_the_configured_tenant() -> None:
    resolver = ConfiguredTenantResolver(tenant_id="tenant-a")

    assert await resolver.resolve("ABC12345", None) == "tenant-a"


async def test_the_fallback_gives_every_session_the_same_tenant() -> None:
    """The fallback is one value by design; two sessions must not diverge."""
    resolver = ConfiguredTenantResolver(tenant_id="tenant-a")

    assert await resolver.resolve("ABC12345", None) == await resolver.resolve("XYZ99999", None)


async def test_a_sessionless_submission_still_gets_a_tenant() -> None:
    """tenant_id is NOT NULL; the admin dashboard submits without a session."""
    resolver = ConfiguredTenantResolver(tenant_id="tenant-a")

    assert await resolver.resolve(None, None) == "tenant-a"


async def test_from_environment_reads_the_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEFAULT_TENANT_ENV, "kassel")

    resolver = ConfiguredTenantResolver.from_environment()

    assert await resolver.resolve(None, None) == "kassel"


async def test_from_environment_falls_back_to_a_named_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank tenant would violate the NOT NULL constraint at insert time."""
    monkeypatch.delenv(DEFAULT_TENANT_ENV, raising=False)

    resolver = ConfiguredTenantResolver.from_environment()

    assert await resolver.resolve(None, None) == "default"


async def test_a_blank_environment_value_does_not_become_an_empty_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEFAULT_TENANT_ENV, "   ")

    resolver = ConfiguredTenantResolver.from_environment()

    assert await resolver.resolve(None, None) == "default"


def test_the_configured_resolver_satisfies_the_port() -> None:
    """A future SessionTenantResolver must be substitutable for this one."""
    assert isinstance(ConfiguredTenantResolver(tenant_id="t"), TenantResolver)


class TestTheTenantComesFromTheSession:
    """Since the tenant-isolation release, a session knows its tenant.

    The key arrives already resolved, from FeedbackService. Resolving the
    session a second time here is what would let the two disagree at the edge
    of the feedback grace window (#324) and file a tenant's feedback under the
    configured fallback instead, so this port maps the key it is handed and
    looks nothing up. The configured value covers what has no key to give: a
    legacy session, and a submission that names no session at all.
    """

    def _resolver(self):
        from services.api_gateway.feedback.tenant import (
            ConfiguredTenantResolver,
            SessionTenantResolver,
        )

        return SessionTenantResolver(
            fallback=ConfiguredTenantResolver(tenant_id="configured"),
        )

    def _key(self, tenant_id: str, session_id: str):
        from services.api_gateway.tenant_session import TenantSessionKey

        return TenantSessionKey(tenant_id, session_id)

    async def test_a_session_key_resolves_to_its_own_tenant(self) -> None:
        key = self._key("tenant-kassel", "KASSEL01")

        assert await self._resolver().resolve(key.session_id, key) == "tenant-kassel"

    async def test_two_tenants_sessions_stay_apart(self) -> None:
        """The whole point: one deployment, several tenants, no commingling."""
        kassel = self._key("tenant-kassel", "KASSEL01")
        gotha = self._key("tenant-gotha", "GOTHA001")
        resolver = self._resolver()

        assert await resolver.resolve(kassel.session_id, kassel) == "tenant-kassel"
        assert await resolver.resolve(gotha.session_id, gotha) == "tenant-gotha"

    async def test_a_session_with_no_key_falls_back(self) -> None:
        """A legacy session is known to the manager but has no tenant to give."""
        assert await self._resolver().resolve("LEGACY01", None) == "configured"

    async def test_no_session_falls_back_to_the_configured_tenant(self) -> None:
        assert await self._resolver().resolve(None, None) == "configured"

    def test_the_session_resolver_satisfies_the_port(self) -> None:
        assert isinstance(self._resolver(), TenantResolver)
