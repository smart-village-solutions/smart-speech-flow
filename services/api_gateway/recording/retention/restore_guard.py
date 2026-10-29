"""Stop destructive steps when `ssf_recording` falls behind what the worker saw (spec §16.1).

Audit events are append-only and hash-chained, so each tenant's chain only
grows. The worker keeps, per tenant, the sequence number and hash of the last
event it saw. If the database no longer holds that event, or holds another one
at that number, it was restored from a dump: decisions made since then are
gone, so lifting holds, shredding or deleting could act on an outdated state.
The hash catches a restore even after new events have passed the old number.
The worker stays halted until an operator acknowledges the restore.

When the guard trips, every tenant is marked for a re-read: its versions'
real locks and holds are read from the store again, because the restored rows
no longer know about holds and extensions set since the dump. A tenant stays
marked until its re-read is recorded.

The state is read and written under a file lock, so `acknowledge-restore`,
run beside the worker's loop, is never overwritten by it.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

STATE_FILE: Final[str] = "audit-high-water.json"
LOCK_FILE: Final[str] = "audit-high-water.lock"
# Every tenant the next pass sees: the state was unreadable, so none is known.
ALL_TENANTS: Final[str] = "*"


@dataclass(frozen=True)
class AuditMark:
    seq: int
    hash: str  # hex of the event's chain hash


class GuardState:
    """The marks and the halt as stored; changes are saved at once."""

    def __init__(
        self, path: Path, marks: dict[str, AuditMark], halted: bool, recheck: set[str]
    ) -> None:
        self._path = path
        self.marks = marks
        self.halted = halted
        self.recheck = recheck

    def observe(self, behind: bool, latest: Mapping[str, AuditMark]) -> bool:
        """Halted, persisted: once the database was behind a mark, until acknowledged."""
        if (behind and not self.halted) or ALL_TENANTS in self.recheck:
            self.recheck = set(self.marks) | set(latest)
        if behind or self.halted:
            self.halted = True
        else:
            self.marks = {**self.marks, **latest}
        self._save()
        return self.halted

    def rechecked(self, tenant_id: str) -> None:
        self.recheck.discard(tenant_id)
        self._save()

    def acknowledge(self, latest: Mapping[str, AuditMark]) -> None:
        self.marks, self.halted, self.recheck = dict(latest), False, set()
        self._save()

    def _save(self) -> None:
        raw = {
            "marks": {t: {"seq": m.seq, "hash": m.hash} for t, m in self.marks.items()},
            "halted": self.halted,
            "recheck": sorted(self.recheck),
        }
        descriptor, temporary = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        with os.fdopen(descriptor, "w") as handle:  # mkstemp creates it 0600
            json.dump(raw, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)


class AuditHighWater:
    def __init__(self, state_dir: Path) -> None:
        self._dir = state_dir

    @property
    def halted(self) -> bool:
        with self.locked() as state:
            return state.halted

    @contextmanager
    def locked(self) -> Iterator[GuardState]:
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self._dir / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield GuardState(self._dir / STATE_FILE, *self._load())
        finally:
            os.close(descriptor)  # releases the lock

    def _load(self) -> tuple[dict[str, AuditMark], bool, set[str]]:
        try:
            raw: Any = json.loads((self._dir / STATE_FILE).read_text())
            if not isinstance(raw["halted"], bool):
                raise ValueError("halted")
            marks = {
                str(tenant): AuditMark(int(mark["seq"]), str(mark["hash"]))
                for tenant, mark in raw["marks"].items()
            }
            return marks, raw["halted"], {str(tenant) for tenant in raw.get("recheck", [])}
        except FileNotFoundError:
            return {}, False, set()
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            # An unreadable mark cannot vouch for the database: halt and re-read everything.
            return {}, True, {ALL_TENANTS}
