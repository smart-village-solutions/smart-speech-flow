"""Where a feedback row's tenant comes from.

Sessions do not carry a tenant yet. When the SVA Studio integration lands, a
SessionTenantResolver implements this same Protocol and the lifespan swaps one
constructor -- the feedback table already has the column, so no migration and
no backfill are needed. See docs/architecture/sva-studio-control-plane.md,
which records that SSF remains authoritative for conversation content and owns
its own runtime databases.
"""

from __future__ import annotations

import os
from typing import Final, Protocol, runtime_checkable

DEFAULT_TENANT_ENV: Final[str] = "SSF_DEFAULT_TENANT_ID"

# Named rather than blank: tenant_id is NOT NULL, and an empty string would
# pass the constraint while grouping every row under a tenant that reads as
# missing data in any later report.
_FALLBACK_TENANT: Final[str] = "default"


@runtime_checkable
class TenantResolver(Protocol):
    async def resolve(self, session_id: str | None) -> str: ...


class ConfiguredTenantResolver:
    """One tenant for the whole deployment, until Studio provides real ones."""

    def __init__(self, *, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    @classmethod
    def from_environment(cls) -> "ConfiguredTenantResolver":
        configured = (os.environ.get(DEFAULT_TENANT_ENV) or "").strip()
        return cls(tenant_id=configured or _FALLBACK_TENANT)

    async def resolve(self, session_id: str | None) -> str:
        return self._tenant_id
