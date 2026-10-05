"""One asyncio lock per key, held only while someone needs it."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass(slots=True)
class _Entry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    holders: int = 0


class KeyedLocks[KeyT: Hashable]:
    """Serialize work per key in the order it arrives; forget a key once it is idle.

    `asyncio.Lock` is fair, so work under one key runs in arrival order, and
    work under different keys never waits for each other. An entry lives only
    while a holder or waiter needs it, so the map stays as small as the work in
    flight.
    """

    def __init__(self) -> None:
        self._entries: dict[KeyT, _Entry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    @asynccontextmanager
    async def hold(self, key: KeyT) -> AsyncIterator[None]:
        entry = self._entries.get(key)
        if entry is None:
            entry = self._entries[key] = _Entry()
        entry.holders += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.holders -= 1
            if entry.holders == 0:
                del self._entries[key]
