"""One spool and one uploader per tenant (spec §12.3).

A single queue for every tenant would let one tenant's broken bucket or
credential stall everyone's uploads and, once the spool filled, pause every
recording. Per tenant, a fault stays with the tenant that has it. Order only
matters within a conversation, and a conversation belongs to one tenant.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Final

from ...session_pseudonym import tenant_ref
from .archive import ArchiveWriter
from .spool import DEFAULT_CAPACITY_BYTES, ArchiveSpool, ArchiveUploader, OnStored

# Room for one more message at least: two 20 s WAVs and a record.
DEFAULT_HEADROOM_BYTES: Final[int] = 8 << 20


class TenantSpools:
    """Spools are created and their uploaders started on the event loop's thread only."""

    def __init__(
        self,
        root: Path,
        writer: ArchiveWriter,
        on_stored: OnStored,
        *,
        capacity_bytes: int = DEFAULT_CAPACITY_BYTES,
        headroom_bytes: int = DEFAULT_HEADROOM_BYTES,
    ) -> None:
        self._root = root
        self._writer = writer
        self._on_stored = on_stored
        self._capacity = capacity_bytes
        self._headroom = headroom_bytes
        self._spools: dict[str, tuple[ArchiveSpool, ArchiveUploader]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._running = False

    def recover(self) -> None:
        """Pick up what a previous process left, so it is uploaded before anything new."""
        self._root.mkdir(parents=True, exist_ok=True)
        for directory in sorted(path for path in self._root.iterdir() if path.is_dir()):
            spool = ArchiveSpool(directory, self._capacity)
            oldest = spool.oldest()
            if oldest is not None and tenant_ref(oldest.tenant_id) == directory.name:
                self._register(oldest.tenant_id, spool)

    def _register(
        self, tenant_id: str, spool: ArchiveSpool
    ) -> tuple[ArchiveSpool, ArchiveUploader]:
        uploader = ArchiveUploader(spool, self._writer, self._on_stored)
        self._spools[tenant_id] = (spool, uploader)
        if self._running:
            self._start(tenant_id, uploader)
        return spool, uploader

    def _entry(self, tenant_id: str) -> tuple[ArchiveSpool, ArchiveUploader]:
        entry = self._spools.get(tenant_id)
        if entry is None:
            spool = ArchiveSpool(self._root / tenant_ref(tenant_id), self._capacity)
            entry = self._register(tenant_id, spool)
        return entry

    def spool(self, tenant_id: str) -> ArchiveSpool:
        return self._entry(tenant_id)[0]

    def notify(self, tenant_id: str) -> None:
        self._entry(tenant_id)[1].notify()

    def ready(self, tenant_id: str) -> bool:
        """Whether one more message fits; recording pauses with reason `storage` otherwise."""
        return self._entry(tenant_id)[0].has_room(self._headroom)

    def _start(self, tenant_id: str, uploader: ArchiveUploader) -> None:
        self._tasks[tenant_id] = asyncio.create_task(
            uploader.run(), name=f"archive-uploader-{tenant_ref(tenant_id)}"
        )

    def start(self) -> None:
        self._running = True
        for tenant_id, (_, uploader) in self._spools.items():
            if tenant_id not in self._tasks:
                self._start(tenant_id, uploader)

    async def stop(self) -> None:
        self._running = False
        tasks, self._tasks = list(self._tasks.values()), {}
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def flush(self) -> bool:
        """Upload every tenant's spool now; for tests and operator checks."""
        results = [await uploader.flush() for _, uploader in self._spools.values()]
        return all(results)
