"""Where a feedback row's tenant comes from.

The feedback table has carried a tenant column from its first migration,
populated through this port. Since the tenant-isolation release a session
knows its tenant, so SessionTenantResolver reads it from there, and the
configured value survives only as the fallback for what carries none.
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


async def test_the_fallback_gives_every_session_the_same_tenant() -> None:
    """The fallback is one value by design; two sessions must not diverge."""
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


class TestTheTenantComesFromTheSession:
    """Since the tenant-isolation release, a session knows its tenant.

    A tenant-flow session resolves through the join index to a
    TenantSessionKey, and that key is the only source for its tenant. The
    configured value is a fallback for what has no tenant to give: a legacy
    session, and a submission that names no session at all.
    """

    REVISION = f"sha256:{'a' * 64}"

    def _manager(self, *identifiers: str):
        from services.api_gateway.session_manager import SessionManager
        from services.api_gateway.session_store import MemoryTenantSessionStore

        ids = iter(identifiers)
        return SessionManager(
            store=MemoryTenantSessionStore(), session_id_factory=lambda: next(ids)
        )

    def _snapshot(self):
        from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

        return RuntimeConfigurationSnapshot(self.REVISION, self.REVISION, "{}")

    def _resolver(self, manager):
        from services.api_gateway.feedback.tenant import (
            ConfiguredTenantResolver,
            SessionTenantResolver,
        )

        return SessionTenantResolver(
            session_manager=manager,
            fallback=ConfiguredTenantResolver(tenant_id="configured"),
        )

    async def test_a_tenant_session_resolves_to_its_own_tenant(self) -> None:
        manager = self._manager("KASSEL01")
        session = await manager.create_admin_session("tenant-kassel", self._snapshot())

        assert await self._resolver(manager).resolve(session.id) == "tenant-kassel"

    async def test_two_tenants_sessions_stay_apart(self) -> None:
        """The whole point: one deployment, several tenants, no commingling."""
        manager = self._manager("KASSEL01", "GOTHA001")
        kassel = await manager.create_admin_session("tenant-kassel", self._snapshot())
        gotha = await manager.create_admin_session("tenant-gotha", self._snapshot())
        resolver = self._resolver(manager)

        assert await resolver.resolve(kassel.id) == "tenant-kassel"
        assert await resolver.resolve(gotha.id) == "tenant-gotha"

    async def test_a_legacy_session_falls_back_to_the_configured_tenant(self) -> None:
        manager = self._manager()
        legacy_id = manager.create_session("de")

        assert await self._resolver(manager).resolve(legacy_id) == "configured"

    async def test_no_session_falls_back_to_the_configured_tenant(self) -> None:
        assert await self._resolver(self._manager()).resolve(None) == "configured"
