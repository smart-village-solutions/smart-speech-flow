"""Custodians from the Studio recording directory (spec §10.1), read live for every use."""

from __future__ import annotations

import sys
from collections.abc import Mapping

from ..studio_recording_directory_client import StudioRecordingDirectoryClient
from ..studio_runtime_token import StudioTokenError
from ..studio_v1 import StudioV1ClientError
from .permissions import CUSTODIAN


class StudioCustodianDirectory:
    def __init__(self, client: StudioRecordingDirectoryClient | None) -> None:
        self._client = client

    async def custodians(self, tenant_id: str, correlation_id: str) -> Mapping[str, str] | None:
        """Subject -> display name of every custodian; None when Studio cannot answer."""
        if self._client is None:
            return None
        try:
            directory = await self._client.fetch(tenant_id, correlation_id)
        except (StudioV1ClientError, StudioTokenError) as error:
            # The code only: Studio errors carry no content, but the rule is the same everywhere.
            sys.stderr.write(f"Recording directory read failed: {error.code}\n")
            return None
        return {sub: user.display_name for sub, user in directory.holders_of(CUSTODIAN).items()}
