"""Leavers: an org admin retires the key of someone Studio no longer lists (spec §9.8).

Nothing is retired automatically. Only a user missing from the recording
directory can be marked, and the directory must look like the tenant's: an
answer naming none of the tenant's key holders is a fault, never a list.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from ..clock import utc_now
from .recovery_requests_model import Refused
from .repository import RecordingStorageUnavailable

T = TypeVar("T")


@dataclass(frozen=True)
class KeyHolder:
    """A user with an active key, with what lets an admin recognise them without a name."""

    sub: str
    key_version: int
    fingerprint: bytes
    enrolled_at: datetime
    conversations: int
    last_conversation_at: datetime | None
    custodian: bool
    # Recorded by the current generation for a custodian; no other name outlives the directory.
    display_name: str | None


@dataclass(frozen=True)
class MarkedLeaver:
    sub: str
    key_version: int
    custodian: bool
    wraps_deleted: int


class LeaverError(Exception):
    """directory_unavailable, still_in_directory, the store's refusals, or unavailable."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LeaverStore(Protocol):
    async def holders(self, tenant_id: str) -> list[KeyHolder]: ...

    async def holder_subs(self, tenant_id: str) -> frozenset[str]:
        """Who holds an active key, without the activity `holders` scans for."""
        ...

    async def mark(
        self, tenant_id: str, sub: str, key_version: int, actor: str, now: datetime
    ) -> Refused | MarkedLeaver: ...


class Members(Protocol):
    async def members(self, tenant_id: str, correlation_id: str) -> frozenset[str] | None: ...


class Leavers:
    def __init__(
        self,
        *,
        store: LeaverStore,
        directory: Members,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._directory = directory
        self._clock = clock

    async def candidates(self, tenant_id: str, correlation_id: str) -> list[KeyHolder]:
        present = await self._present(tenant_id, correlation_id)
        holders = await _stored(self._store.holders(tenant_id))
        _check_plausible(present, {holder.sub for holder in holders})
        return [holder for holder in holders if holder.sub not in present]

    async def mark(
        self, tenant_id: str, actor: str, sub: str, key_version: int, correlation_id: str
    ) -> MarkedLeaver:
        present = await self._present(tenant_id, correlation_id)
        _check_plausible(present, await _stored(self._store.holder_subs(tenant_id)))
        if sub in present:
            raise LeaverError("still_in_directory")
        marked = await _stored(self._store.mark(tenant_id, sub, key_version, actor, self._clock()))
        if isinstance(marked, Refused):
            raise LeaverError(marked.code)
        return marked

    async def _present(self, tenant_id: str, correlation_id: str) -> frozenset[str]:
        present = await self._directory.members(tenant_id, correlation_id)
        if present is None:
            raise LeaverError("directory_unavailable")
        return present


async def _stored(read: Awaitable[T]) -> T:
    try:
        return await read
    except RecordingStorageUnavailable:
        raise LeaverError("unavailable") from None


def _check_plausible(present: frozenset[str], holders: set[str] | frozenset[str]) -> None:
    # An empty or truncated answer would make every key holder a leaver.
    if holders and present.isdisjoint(holders):
        raise LeaverError("directory_unavailable")
