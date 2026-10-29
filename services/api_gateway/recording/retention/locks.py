"""Bringing each stored version's lock and hold to its conversation's state (spec §16.1).

`plan` is pure: what one version on one site needs, from what the database
wants and what this site's worker last confirmed. A hold is lifted only for a
`hold_off` decided after the hold was applied or found, never because the two
differ, so a database restored to an older state cannot lift a hold.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal, Protocol

from ..storage.archive import (
    ArchiveNotFoundError,
    ArchiveRefusedError,
    ArchiveRetention,
    ArchiveUnavailableError,
)
from .decisions import MAX_EXTENSION
from .store import DueVersion, LockState

Action = Literal["check", "hold_on", "lift", "extend", "delete"]
IDLE_REVISIT: Final[timedelta] = timedelta(days=1)
# While the restore guard holds destructive steps back, and after a refused delete.
GUARD_REVISIT: Final[timedelta] = timedelta(hours=1)
BATCH: Final[int] = 200
MAX_BATCHES: Final[int] = 10


@dataclass(frozen=True)
class Plan:
    actions: tuple[Action, ...]
    revisit_at: datetime
    mismatch: bool = False


@dataclass
class ReconcileReport:
    processed: int = 0
    failures: int = 0
    mismatches: int = 0


class RetentionRows(Protocol):
    async def due_versions(
        self, tenant_id: str, now: datetime, limit: int = BATCH
    ) -> list[DueVersion]: ...

    async def record(self, row: DueVersion, state: LockState, revisit_at: datetime) -> None: ...

    async def record_failure(
        self, row: DueVersion, now: datetime, state: LockState | None = None
    ) -> None: ...


def _lift_allowed(row: DueVersion) -> bool:
    return (
        row.hold_off_at is not None
        and row.held_since is not None
        and row.hold_off_at > row.held_since
    )


def plan(row: DueVersion, now: datetime, *, destructive: bool) -> Plan:
    if row.checked_at is None:
        return Plan(("check",), now)
    if row.shredded_at is not None:
        return _plan_shredded(row, now, destructive)
    actions: list[Action] = []
    mismatch = False
    if row.legal_hold and not row.held:
        actions.append("hold_on")
    elif not row.legal_hold and row.held:
        if destructive and _lift_allowed(row):
            actions.append("lift")
        else:
            mismatch = True
    if row.locked_until is None or row.locked_until < lock_target(row, now):
        actions.append("extend")
    revisit = IDLE_REVISIT if destructive else GUARD_REVISIT
    return Plan(tuple(actions), now + revisit, mismatch)


def _plan_shredded(row: DueVersion, now: datetime, destructive: bool) -> Plan:
    if not destructive:
        return Plan((), now + GUARD_REVISIT, mismatch=row.held)
    if row.held:
        if _lift_allowed(row):
            return Plan(("lift",), now)
        return Plan((), now + IDLE_REVISIT, mismatch=True)
    if row.locked_until is not None and row.locked_until > now:
        return Plan((), row.locked_until)
    return Plan(("delete",), now + IDLE_REVISIT)


def lock_target(row: DueVersion, now: datetime) -> datetime:
    """The conversation's date, but never more than one extension step ahead of now.

    A compliance lock cannot be shortened, so a date the database should not
    hold is approached a step at a time rather than set at once.
    """
    return min(row.retention_until, now + MAX_EXTENSION)


def _recorded(row: DueVersion, now: datetime) -> LockState:
    return LockState(row.checked_at or now, row.locked_until, row.held, row.held_since, None)


def _confirmed(row: DueVersion, state: LockState) -> DueVersion:
    return dataclasses.replace(
        row,
        checked_at=state.checked_at,
        locked_until=state.locked_until,
        held=state.held,
        held_since=state.held_since,
    )


class LockReconciler:
    def __init__(self, store: RetentionRows, archive: ArchiveRetention) -> None:
        self._store = store
        self._archive = archive

    async def run(self, tenant_id: str, now: datetime, *, destructive: bool) -> ReconcileReport:
        report = ReconcileReport()
        for _ in range(MAX_BATCHES):
            rows = await self._store.due_versions(tenant_id, now, BATCH)
            for row in rows:
                if not await self._apply(row, now, destructive, report):
                    return report  # the store is unreachable: every other row would wait too
            if len(rows) < BATCH:
                break
        return report

    async def _read(self, row: DueVersion, now: datetime, held_since: datetime | None) -> LockState:
        found = await self._archive.retention(row.tenant_id, row.key, row.version_id)
        # A hold this worker did not apply counts from now: no older hold_off lifts it.
        since = (held_since or now) if found.legal_hold else None
        return LockState(now, found.retain_until, found.legal_hold, since, None)

    async def _apply(
        self, row: DueVersion, now: datetime, destructive: bool, report: ReconcileReport
    ) -> bool:
        """False when the store was unreachable."""
        report.processed += 1
        # None until the store has been read: a failure then records nothing as read.
        state = None if row.checked_at is None else _recorded(row, now)
        action: Action = "check"
        try:
            if state is None:
                state = await self._read(row, now, None)
            steps = plan(_confirmed(row, state), now, destructive=destructive)
            for action in steps.actions:
                state = await self._act(action, row, state, now)
        except ArchiveUnavailableError:
            await self._failed(row, now, report, state)
            return False
        except ArchiveNotFoundError:
            if row.shredded_at is None:
                await self._failed(row, now, report, state)
                return True
            # Gone, or not yet copied here: the prefix listing finds a late copy (expiry.py).
            gone = dataclasses.replace(state or _recorded(row, now), deleted_at=now)
            await self._store.record(row, gone, now)
            return True
        except ArchiveRefusedError:
            if action != "delete" or state is None:
                await self._failed(row, now, report, state)
                return True
            await self._refused_delete(row, state, now, report)
            return True
        report.mismatches += steps.mismatch
        await self._store.record(row, state, steps.revisit_at)
        return True

    async def _failed(
        self, row: DueVersion, now: datetime, report: ReconcileReport, state: LockState | None
    ) -> None:
        """Count the failure, and keep what earlier steps of the plan did, such as a hold."""
        report.failures += 1
        await self._store.record_failure(row, now, state)

    async def _refused_delete(
        self, row: DueVersion, state: LockState, now: datetime, report: ReconcileReport
    ) -> None:
        """The store kept the version: wait if its lock or a hold explains it, else fail."""
        try:
            state = await self._read(row, now, state.held_since)
        except (ArchiveUnavailableError, ArchiveRefusedError, ArchiveNotFoundError):
            await self._failed(row, now, report, state)
            return
        if state.held or (state.locked_until is not None and state.locked_until > now):
            later = now + GUARD_REVISIT
            if state.locked_until is not None and state.locked_until > later:
                later = state.locked_until
            await self._store.record(row, state, later)
            return
        # Lapsed and free, yet refused: a credential without delete rights, for instance.
        await self._failed(row, now, report, state)

    async def _act(
        self, action: Action, row: DueVersion, state: LockState, now: datetime
    ) -> LockState:
        tenant_id, key, version = row.tenant_id, row.key, row.version_id
        if action == "hold_on":
            await self._archive.set_legal_hold(tenant_id, key, version, True)
            return dataclasses.replace(state, held=True, held_since=row.hold_on_at or now)
        if action == "lift":
            await self._archive.set_legal_hold(tenant_id, key, version, False)
            return dataclasses.replace(state, held=False, held_since=None)
        if action == "extend":
            target = lock_target(row, now)
            await self._archive.extend_retention(tenant_id, key, version, target)
            return dataclasses.replace(state, locked_until=target)
        if action == "delete":
            await self._archive.delete_version(tenant_id, key, version)
            return dataclasses.replace(state, deleted_at=now)
        raise ValueError(f"no store call for the action {action!r}")
