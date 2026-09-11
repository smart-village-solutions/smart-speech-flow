"""Where a feedback row's tenant comes from.

Since the tenant-isolation release, a session opened through the tenant flow
knows its tenant: it lives under a TenantSessionKey, reachable from the bare
id the browser sends through the session store's join index.
SessionTenantResolver reads it from there. ConfiguredTenantResolver remains as
the fallback for what carries no tenant -- a legacy session, and a submission
that names no session at all -- and supplies SSF_DEFAULT_TENANT_ID.

SSF remains authoritative for conversation content and owns its own runtime
databases; see docs/architecture/sva-studio-control-plane.md.
"""

from __future__ import annotations

import os
from typing import Any, Final, Protocol, runtime_checkable

DEFAULT_TENANT_ENV: Final[str] = "SSF_DEFAULT_TENANT_ID"

# Named rather than blank: tenant_id is NOT NULL, and an empty string would
# pass the constraint while grouping every row under a tenant that reads as
# missing data in any later report.
_FALLBACK_TENANT: Final[str] = "default"


@runtime_checkable
class TenantResolver(Protocol):
    async def resolve(self, session_id: str | None) -> str: ...


class ConfiguredTenantResolver:
    """One configured tenant: the fallback for anything that carries none."""

    def __init__(self, *, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    @classmethod
    def from_environment(cls) -> "ConfiguredTenantResolver":
        configured = (os.environ.get(DEFAULT_TENANT_ENV) or "").strip()
        return cls(tenant_id=configured or _FALLBACK_TENANT)

    async def resolve(self, session_id: str | None) -> str:
        return self._tenant_id


class SessionTenantResolver:
    """The tenant of the session a submission names, when it has one.

    Only a live tenant-flow session resolves. A terminated one does not: the
    store revokes its join link on termination, so feedback given after a
    conversation ends is refused upstream as an unknown session before this
    runs (#324). Everything else falls back, rather than being guessed.
    """

    def __init__(self, *, session_manager: Any, fallback: TenantResolver) -> None:
        self._session_manager = session_manager
        self._fallback = fallback

    async def resolve(self, session_id: str | None) -> str:
        if session_id:
            key = self._session_manager.resolve_customer_session(session_id)
            if key is not None:
                return key.tenant_id
        return await self._fallback.resolve(session_id)
