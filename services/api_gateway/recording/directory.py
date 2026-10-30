"""Custodians from the Studio recording directory (spec §10.1), read live for every use."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import Protocol

from ..studio_recording_directory_client import (
    RecordingDirectory,
    StudioRecordingDirectoryClient,
)
from ..studio_runtime_token import StudioTokenError
from ..studio_v1 import StudioV1ClientError
from .permissions import CUSTODIAN


class NameSource(Protocol):
    """Display names for subs, from the directory; empty when it cannot answer."""

    async def names(self, tenant_id: str, correlation_id: str) -> Mapping[str, str]: ...


class StudioCustodianDirectory:
    def __init__(self, client: StudioRecordingDirectoryClient | None) -> None:
        self._client = client

    async def _fetch(self, tenant_id: str, correlation_id: str) -> RecordingDirectory | None:
        if self._client is None:
            return None
        try:
            return await self._client.fetch(tenant_id, correlation_id)
        except (StudioV1ClientError, StudioTokenError) as error:
            # The code only: Studio errors carry no content, but the rule is the same everywhere.
            sys.stderr.write(f"Recording directory read failed: {error.code}\n")
            return None

    async def custodians(self, tenant_id: str, correlation_id: str) -> Mapping[str, str] | None:
        """Subject -> display name of every custodian; None when Studio cannot answer."""
        directory = await self._fetch(tenant_id, correlation_id)
        if directory is None:
            return None
        return {sub: user.display_name for sub, user in directory.holders_of(CUSTODIAN).items()}

    async def members(self, tenant_id: str, correlation_id: str) -> frozenset[str] | None:
        """Every sub the directory lists; None when Studio cannot answer, never an empty set."""
        directory = await self._fetch(tenant_id, correlation_id)
        return None if directory is None else frozenset(user.sub for user in directory.users)

    async def names(self, tenant_id: str, correlation_id: str) -> Mapping[str, str]:
        """Subject -> display name of every recording user; nothing when Studio cannot answer.

        Callers show the sub instead, which is not a stale name (spec §10.1).
        """
        directory = await self._fetch(tenant_id, correlation_id)
        return {} if directory is None else {u.sub: u.display_name for u in directory.users}
