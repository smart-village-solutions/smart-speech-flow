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
marked until its re-read is recorded. While halted, the guard also follows the
newest events it has seen, so a second restore before the acknowledgement
marks every tenant for a re-read again.

The marks advance only at the end of a pass, after every hold the pass applied
is in the audit log: a restore to a dump taken during the pass still falls
behind them.

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
        self,
        path: Path,
        marks: dict[str, AuditMark],
        halted: bool,
        recheck: set[str],
        seen: dict[str, AuditMark],
    ) -> None:
        self._path = path
        self.marks = marks
        self.halted = halted
        self.recheck = recheck
        # While halted: the newest events seen since, to notice a further restore.
        self.seen = seen

    def observe(
        self,
        behind: bool,
        regressed: bool,
        latest: Mapping[str, AuditMark],
        *,
        advance: bool,
    ) -> bool:
        """Halted, persisted: once the database was behind a mark, until acknowledged.

        `behind`: the database lacks an event the marks name. `regressed`: it
        lacks one seen while halted. `advance`: the pass is over, so the marks
        may move on to `latest`.
        """
        if not self.halted and behind:
            self.halted = True
            self._recheck_all(latest)
            self.seen = dict(latest)
        elif self.halted:
            if regressed or ALL_TENANTS in self.recheck:
                self._recheck_all(latest)
                self.seen = dict(latest)
            else:
                self.seen = {**self.seen, **latest}
        elif advance:
            self.marks = {**self.marks, **latest}
        self._save()
        return self.halted

    def _recheck_all(self, latest: Mapping[str, AuditMark]) -> None:
        self.recheck = set(self.marks) | set(self.seen) | set(latest)
        self.recheck.discard(ALL_TENANTS)

    def rechecked(self, tenant_id: str) -> None:
        self.recheck.discard(tenant_id)
        self._save()

    def acknowledge(self, latest: Mapping[str, AuditMark]) -> None:
        self.marks, self.halted, self.recheck, self.seen = dict(latest), False, set(), {}
        self._save()

    def _save(self) -> None:
        raw = {
            "marks": _encode(self.marks),
            "halted": self.halted,
            "recheck": sorted(self.recheck),
            "seen": _encode(self.seen),
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

    def _load(self) -> tuple[dict[str, AuditMark], bool, set[str], dict[str, AuditMark]]:
        try:
            raw: Any = json.loads((self._dir / STATE_FILE).read_text())
            if not isinstance(raw["halted"], bool):
                raise ValueError("halted")
            recheck = {str(tenant) for tenant in raw.get("recheck", [])}
            return _decode(raw["marks"]), raw["halted"], recheck, _decode(raw.get("seen", {}))
        except FileNotFoundError:
            return {}, False, set(), {}
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            # An unreadable mark cannot vouch for the database: halt and re-read everything.
            return {}, True, {ALL_TENANTS}, {}


def _encode(marks: Mapping[str, AuditMark]) -> dict[str, dict[str, Any]]:
    return {tenant: {"seq": mark.seq, "hash": mark.hash} for tenant, mark in marks.items()}


def _decode(raw: Any) -> dict[str, AuditMark]:
    return {
        str(tenant): AuditMark(int(mark["seq"]), str(mark["hash"])) for tenant, mark in raw.items()
    }
