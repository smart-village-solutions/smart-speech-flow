"""The local spool between encryption and the archive store (spec §12.3).

Every encrypted object goes to the spool first and is uploaded from there in
submission order, so an outage of the store only delays uploads and never
reorders them. The spool lives on a gateway volume and survives a restart.
It holds ciphertext only. When it cannot take the next object it raises
SpoolFullError, and recording pauses (#615).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import sys
import threading
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from ...session_pseudonym import tenant_ref
from .archive import (
    ArchiveError,
    ArchiveKeyExistsError,
    ArchiveRefusedError,
    ArchiveWriter,
    StoredVersion,
)

DEFAULT_CAPACITY_BYTES: Final[int] = 1 << 30
_DIGITS: Final[int] = 20


class SpoolFullError(Exception):
    """The spool cannot take this object: its capacity would be exceeded, or its disk refused the write."""


@dataclass(frozen=True)
class SpoolItem:
    seq: int
    tenant_id: str
    key: str
    size: int
    sha256: str


def _fsync_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    # The rename itself survives a power loss only once its directory is synced.
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class ArchiveSpool:
    """A durable FIFO of objects waiting for upload.

    It is thread-safe. `submit`, `read` and `remove` do blocking file I/O; the
    queue accessors never wait for it, so the event loop may call them directly.
    """

    def __init__(self, directory: Path, capacity_bytes: int = DEFAULT_CAPACITY_BYTES) -> None:
        self._directory = directory
        self._capacity = capacity_bytes
        # One submit writes at a time; the queue itself is locked only around memory.
        self._writing = threading.Lock()
        self._state = threading.Lock()
        directory.mkdir(parents=True, exist_ok=True)
        self._items = self._recover()
        self._used = sum(item.size for item in self._items)
        self._next_seq = self._items[-1].seq + 1 if self._items else 1

    def _recover(self) -> list[SpoolItem]:
        """Items whose metadata was written; a blob without metadata never completed."""
        for leftover in self._directory.glob("*.tmp"):
            leftover.unlink()
        items = [
            SpoolItem(**json.loads(path.read_text()))
            for path in sorted(self._directory.glob("*.json"))
        ]
        complete = {self._blob(item).name for item in items}
        for blob in self._directory.glob("*.bin"):
            if blob.name not in complete:
                blob.unlink()
        return items

    def _blob(self, item: SpoolItem) -> Path:
        return self._directory / f"{item.seq:0{_DIGITS}d}.bin"

    def _meta(self, item: SpoolItem) -> Path:
        return self._directory / f"{item.seq:0{_DIGITS}d}.json"

    @property
    def used_bytes(self) -> int:
        with self._state:
            return self._used

    @property
    def pending(self) -> int:
        with self._state:
            return len(self._items)

    def has_room(self, size: int) -> bool:
        with self._state:
            return self._used + size <= self._capacity

    def submit(self, tenant_id: str, key: str, data: bytes) -> SpoolItem:
        with self._writing:
            if not self.has_room(len(data)):
                raise SpoolFullError()
            item = SpoolItem(
                self._next_seq, tenant_id, key, len(data), hashlib.sha256(data).hexdigest()
            )
            try:
                _fsync_write(self._blob(item), data)
                _fsync_write(self._meta(item), json.dumps(asdict(item)).encode())
            except OSError as error:
                self._discard(item)
                raise SpoolFullError() from error
            with self._state:
                self._next_seq += 1
                self._items.append(item)
                self._used += item.size
            return item

    def _discard(self, item: SpoolItem) -> None:
        for path in (self._blob(item), self._meta(item)):
            for leftover in (path, path.with_name(path.name + ".tmp")):
                with contextlib.suppress(OSError):
                    leftover.unlink(missing_ok=True)

    def oldest(self) -> SpoolItem | None:
        with self._state:
            return self._items[0] if self._items else None

    def read(self, item: SpoolItem) -> bytes:
        return self._blob(item).read_bytes()

    def remove(self, item: SpoolItem) -> None:
        """Only the uploader removes, so the item stays the oldest while its files go."""
        with self._state:
            if not self._items or self._items[0] != item:
                raise ValueError("only the oldest item leaves the spool")
        # missing_ok: a removal interrupted between the two files must not stall the next pass.
        self._meta(item).unlink(missing_ok=True)
        self._blob(item).unlink(missing_ok=True)
        with self._state:
            self._items.pop(0)
            self._used -= item.size


def _label(item: SpoolItem) -> str:
    """Which item is stuck, without naming the tenant or the conversation."""
    return f"seq {item.seq} tenant {tenant_ref(item.tenant_id)}"


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


# Called at least once per item: after a crash between recording and removal,
# the item is uploaded again, found stored, and reported again.
OnStored = Callable[[SpoolItem, StoredVersion], Awaitable[None]]


class ArchiveUploader:
    """Uploads the spool in order. A failure stops the pass; nothing is ever dropped."""

    def __init__(
        self,
        spool: ArchiveSpool,
        writer: ArchiveWriter,
        on_stored: OnStored,
        *,
        retry_initial_seconds: float = 1.0,
        retry_ceiling_seconds: float = 60.0,
    ) -> None:
        self._spool = spool
        self._writer = writer
        self._on_stored = on_stored
        self._retry_initial = retry_initial_seconds
        self._retry_ceiling = retry_ceiling_seconds
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def notify(self) -> None:
        """Called after a submit, so an idle uploader starts at once. Safe from any thread."""
        loop = self._loop
        if loop is not None and _running_loop() is not loop:
            loop.call_soon_threadsafe(self._wake.set)
        else:
            self._wake.set()

    async def _store(self, item: SpoolItem) -> StoredVersion:
        try:
            data = await asyncio.to_thread(self._spool.read, item)
        except OSError:
            raise ArchiveRefusedError("spool_unreadable") from None
        if hashlib.sha256(data).hexdigest() != item.sha256:
            raise ArchiveRefusedError("spool_item_corrupt")
        try:
            return await self._writer.put(item.tenant_id, item.key, data)
        except ArchiveKeyExistsError:
            # An earlier attempt stored it and its answer was lost.
            stored = await self._writer.head(item.tenant_id, item.key)
            if stored.sha256 != item.sha256:
                raise ArchiveRefusedError("key_holds_other_bytes") from None
            return stored

    async def flush(self) -> bool:
        """Uploads until the spool is empty (True) or a step fails (False)."""
        while (item := self._spool.oldest()) is not None:
            try:
                stored = await self._store(item)
            except ArchiveError as error:
                # The code only: a key names a conversation, which is not for logs.
                sys.stderr.write(f"Archive upload deferred: {_label(item)} {error.code}\n")
                return False
            try:
                await self._on_stored(item, stored)
            except Exception as error:  # the recorder's database may be down; retry the item
                sys.stderr.write(
                    f"Archive upload not yet recorded: {_label(item)} {type(error).__name__}\n"
                )
                return False
            try:
                await asyncio.to_thread(self._spool.remove, item)
            except OSError as error:
                # The next pass uploads it again, finds it stored and records it again.
                sys.stderr.write(
                    f"Archive spool item not removed: {_label(item)} {type(error).__name__}\n"
                )
                return False
        return True

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        delay = self._retry_initial
        while True:
            self._wake.clear()
            if await self.flush():
                delay = self._retry_initial
                await self._wake.wait()
                continue
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._retry_ceiling)
