"""Expiry: shred on the date, clear each site's versions, then delete the rows (spec §16.1).

Only the primary site's worker shreds and deletes rows; both sites clear
their own versions and sweep their own orphans. Every deletion here goes
through the store's lock, so nothing locked or held can be removed: a version
this worker does not track (a late upload, a late copy) is deleted once its
lock lapses, and a held one is reported, never touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..audit import RETENTION_ACTOR
from ..storage.archive import (
    ArchiveNotFoundError,
    ArchiveRefusedError,
    ArchiveRetention,
    VersionEntry,
)


class ExpiryRows(Protocol):
    async def due_expiries(self, tenant_id: str, now: datetime) -> list[str]: ...

    async def shred(
        self, tenant_id: str, conversation_id: str, now: datetime, actor: str
    ) -> bool: ...

    async def clearable(self, tenant_id: str) -> list[str]: ...

    async def record_clearance(
        self, tenant_id: str, conversation_id: str, now: datetime
    ) -> None: ...

    async def deletable(self, tenant_id: str) -> list[str]: ...

    async def delete_rows(self, tenant_id: str, conversation_id: str, now: datetime) -> bool: ...

    async def known_conversations(self, tenant_id: str) -> dict[str, bool]: ...


@dataclass
class ExpiryReport:
    shredded: int = 0
    versions_deleted: int = 0
    cleared: int = 0
    rows_deleted: int = 0
    # Untracked versions under a hold: nothing lifts them without a decision.
    # Found clearing a shredded conversation, and by the sweep.
    held_orphans: int = 0
    swept_held: int = 0
    # Deletes the store refused although its own lock read said lapsed and free.
    refused: int = 0


class Expirer:
    def __init__(self, store: ExpiryRows, archive: ArchiveRetention) -> None:
        self._store = store
        self._archive = archive

    async def shred_due(self, tenant_id: str, now: datetime, report: ExpiryReport) -> None:
        for conversation_id in await self._store.due_expiries(tenant_id, now):
            if await self._store.shred(tenant_id, conversation_id, now, RETENTION_ACTOR):
                report.shredded += 1

    async def clear(self, tenant_id: str, now: datetime, report: ExpiryReport) -> None:
        """Record each shredded conversation whose prefix lists nothing on this site."""
        for conversation_id in await self._store.clearable(tenant_id):
            prefix = f"{conversation_id}/"
            listed = await self._listed(tenant_id, prefix)
            for entry in listed:
                await self._settle(tenant_id, entry, now, report, sweeping=False)
            if listed:
                listed = await self._listed(tenant_id, prefix)
            if not listed:
                await self._store.record_clearance(tenant_id, conversation_id, now)
                report.cleared += 1

    async def delete_rows(self, tenant_id: str, now: datetime, report: ExpiryReport) -> None:
        for conversation_id in await self._store.deletable(tenant_id):
            if await self._store.delete_rows(tenant_id, conversation_id, now):
                report.rows_deleted += 1

    async def sweep(self, tenant_id: str, now: datetime, report: ExpiryReport) -> None:
        """Versions of conversations that have no rows at all, as after a late upload."""
        # Listed first: a conversation's row exists before its first upload, so a
        # version listed now and missing from the rows read after is an orphan.
        listed = await self._listed(tenant_id, "")
        known = await self._store.known_conversations(tenant_id)
        for entry in listed:
            if entry.key.split("/", 1)[0] not in known:
                await self._settle(tenant_id, entry, now, report, sweeping=True)

    async def _listed(self, tenant_id: str, prefix: str) -> list[VersionEntry]:
        """A tenant onboarded before its bucket was created has nothing stored yet."""
        try:
            return await self._archive.list_versions(tenant_id, prefix)
        except ArchiveNotFoundError as error:
            if error.code != "NoSuchBucket":
                raise
            return []

    async def _settle(
        self,
        tenant_id: str,
        entry: VersionEntry,
        now: datetime,
        report: ExpiryReport,
        *,
        sweeping: bool,
    ) -> None:
        """Delete an untracked version or delete marker once nothing holds it."""
        try:
            if not entry.is_marker:
                state = await self._archive.retention(tenant_id, entry.key, entry.version_id)
                if state.legal_hold:
                    if sweeping:
                        report.swept_held += 1
                    else:
                        report.held_orphans += 1
                    return
                if state.retain_until is not None and state.retain_until > now:
                    return
            await self._archive.delete_version(tenant_id, entry.key, entry.version_id)
        except ArchiveNotFoundError:
            return  # gone already
        except ArchiveRefusedError:
            # Retried next pass; counted, so a missing delete right does not go unnoticed.
            report.refused += 1
            return
        report.versions_deleted += 1
