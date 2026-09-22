"""Where a feedback row's tenant comes from.

Since the tenant-isolation release, a session opened through the tenant flow
knows its tenant: it lives under a TenantSessionKey. FeedbackService resolves
that key once -- for a live session, and within the grace window for one that
has just ended (#324) -- and hands it here, so the check that accepts a
submission and the lookup that files it cannot disagree at the edge of the
window. ConfiguredTenantResolver remains the fallback for what carries no key
-- a legacy session, and a submission that names no session at all -- and
supplies SSF_DEFAULT_TENANT_ID.

SSF remains authoritative for conversation content and owns its own runtime
databases; see docs/architecture/sva-studio-control-plane.md.
"""

from __future__ import annotations

import os
from typing import Final, Protocol, override, runtime_checkable

from ..tenant_session import TenantSessionKey

DEFAULT_TENANT_ENV: Final[str] = "SSF_DEFAULT_TENANT_ID"

# Named rather than blank: tenant_id is NOT NULL, and an empty string would
# pass the constraint while grouping every row under a tenant that reads as
# missing data in any later report.
_FALLBACK_TENANT: Final[str] = "default"


@runtime_checkable
class TenantResolver(Protocol):
    async def resolve(self, session_id: str | None, session_key: TenantSessionKey | None) -> str:
        """Resolve the storage tenant for a submission's already-resolved session."""
        ...


class ConfiguredTenantResolver(TenantResolver):
    """One configured tenant: the fallback for anything that carries none."""

    def __init__(self, *, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    @classmethod
    def from_environment(cls) -> "ConfiguredTenantResolver":
        configured = (os.environ.get(DEFAULT_TENANT_ENV) or "").strip()
        return cls(tenant_id=configured or _FALLBACK_TENANT)

    @override
    async def resolve(self, session_id: str | None, session_key: TenantSessionKey | None) -> str:
        return self._tenant_id


class SessionTenantResolver:
    """The tenant of the session a submission names, when it has one.

    A mapping, not a lookup: the key is resolved once upstream, and resolving
    it again here is what would let the two resolutions diverge.
    """

    def __init__(self, *, fallback: TenantResolver) -> None:
        self._fallback = fallback

    async def resolve(self, session_id: str | None, session_key: TenantSessionKey | None) -> str:
        if session_key is not None:
            return session_key.tenant_id
        return await self._fallback.resolve(session_id, session_key)
