"""One retention pass over every tenant on this worker's site, and the loop around it.

A pass checks the restore guard, tracks every newly stored version, shreds
what expired (primary), brings due versions' locks and holds to their
conversation's state, clears and sweeps this site's versions, deletes the rows
both sites have cleared (primary), and ends with a heartbeat the gateway
exports. While the guard is tripped nothing destructive runs: no shred, no
lift, no deletion. A tenant whose pass fails waits for the next one; the
others go on.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final, Protocol

from ...clock import utc_now
from ..repository import RecordingStorageUnavailable
from ..storage.archive import ArchiveError, ArchiveRetention
from .expiry import Expirer, ExpiryReport, ExpiryRows
from .locks import LockReconciler, RetentionRows
from .restore_guard import AuditHighWater, AuditMark
from .settings import WorkerSettings

SWEEP_STATE_FILE: Final[str] = "sweep.json"
# Tenants whose whole pass has been failing, and since when: they count as overdue.
FAILURES_STATE_FILE: Final[str] = "tenant-failures.json"


class WorkerStore(RetentionRows, ExpiryRows, Protocol):
    async def tenants(self) -> list[str]: ...

    async def audit_mark(self, tenant_id: str) -> AuditMark | None: ...

    async def audit_hash_at(self, tenant_id: str, seq: int) -> str | None: ...

    async def recheck_all(self, tenant_id: str, now: datetime) -> None: ...

    async def discover(self, tenant_id: str, now: datetime) -> int: ...

    async def hold_mismatches(self, tenant_id: str) -> int: ...

    async def overdue_since(self, tenant_id: str, now: datetime) -> datetime | None: ...

    async def beat(
        self, now: datetime, failing_seconds: float, halted: bool, hold_mismatches: int
    ) -> None: ...


@dataclass
class PassReport:
    tenants: int
    processed: int = 0
    failures: int = 0
    # Versions held on this site with nothing to lift them: from the database's
    # state and this site's untracked held versions, not from this pass alone.
    mismatches: int = 0
    halted: bool = False
    shredded: int = 0
    versions_deleted: int = 0
    cleared: int = 0
    rows_deleted: int = 0
    swept: bool = False
    held_orphans: int = field(default=0, repr=False)
    swept_held: int = field(default=0, repr=False)

    def as_dict(self) -> dict[str, Any]:
        report = asdict(self)
        del report["held_orphans"], report["swept_held"]
        return report


def _read_state(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write_state(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle)
    os.replace(temporary, path)


class RetentionWorker:
    def __init__(
        self,
        settings: WorkerSettings,
        store: WorkerStore,
        archive: ArchiveRetention,
        guard: AuditHighWater,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._settings = settings
        self._store = store
        self._guard = guard
        self._clock = clock
        self._reconciler = LockReconciler(store, archive)
        self._expirer = Expirer(store, archive)
        self._primary = settings.site == "primary"

    async def run_once(self) -> PassReport:
        now = self._clock()
        tenants = await self._store.tenants()
        halted, recheck = await self._observe(tenants)
        report = PassReport(len(tenants), halted=halted)
        report.swept = not halted and self._sweep_due(now)
        failed = await self._tenant_passes(tenants, now, report, recheck)
        report.mismatches = await self._mismatches(tenants, report, complete=not failed)
        overdue = await self._overdue_seconds(tenants, now, failed)
        await self._store.beat(now, overdue, halted, report.mismatches)
        return report

    async def _observe(self, tenants: list[str]) -> tuple[bool, set[str]]:
        """Whether the database is behind the marks, and which tenants owe a re-read."""
        with self._guard.locked() as guard:
            behind = False
            for tenant, mark in guard.marks.items():
                if await self._store.audit_hash_at(tenant, mark.seq) != mark.hash:
                    behind = True
            latest = {}
            for tenant in tenants:
                if (newest := await self._store.audit_mark(tenant)) is not None:
                    latest[tenant] = newest
            halted = guard.observe(behind, latest)
            return halted, set(guard.recheck)

    async def _tenant_passes(
        self, tenants: list[str], now: datetime, report: PassReport, recheck: set[str]
    ) -> set[str]:
        failed = set()
        for tenant in tenants:
            try:
                if tenant in recheck:
                    await self._recheck(tenant, now)
                await self._tenant_pass(tenant, now, report)
            except (RecordingStorageUnavailable, ArchiveError):
                report.failures += 1  # this tenant's turn comes again in the next pass
                failed.add(tenant)
        self._record_failures(set(tenants), failed, now)
        if report.swept and not failed:
            _write_state(
                self._settings.state_dir / SWEEP_STATE_FILE,
                {"at": now.isoformat(), "held_orphans": report.swept_held},
            )
        return failed

    async def _recheck(self, tenant_id: str, now: datetime) -> None:
        await self._store.recheck_all(tenant_id, now)
        with self._guard.locked() as guard:
            guard.rechecked(tenant_id)

    async def _tenant_pass(self, tenant_id: str, now: datetime, report: PassReport) -> None:
        expiry = ExpiryReport()
        await self._store.discover(tenant_id, now)
        if self._primary and not report.halted:
            # First, so the shredded conversation's versions are reconciled in this pass.
            await self._expirer.shred_due(tenant_id, now, expiry)
        locks = await self._reconciler.run(tenant_id, now, destructive=not report.halted)
        report.processed += locks.processed
        report.failures += locks.failures
        try:
            if not report.halted:
                await self._expire(tenant_id, now, report.swept, expiry)
        finally:
            report.shredded += expiry.shredded
            report.versions_deleted += expiry.versions_deleted
            report.cleared += expiry.cleared
            report.rows_deleted += expiry.rows_deleted
            report.held_orphans += expiry.held_orphans
            report.swept_held += expiry.swept_held

    async def _expire(
        self, tenant_id: str, now: datetime, sweep: bool, expiry: ExpiryReport
    ) -> None:
        await self._expirer.clear(tenant_id, now, expiry)
        if self._primary:
            await self._expirer.delete_rows(tenant_id, now, expiry)
        if sweep:
            await self._expirer.sweep(tenant_id, now, expiry)

    def _sweep_due(self, now: datetime) -> bool:
        """Once `sweep_hours` after the last complete sweep; an unreadable record sweeps now."""
        try:
            raw = _read_state(self._settings.state_dir / SWEEP_STATE_FILE)
            elapsed = now - datetime.fromisoformat(raw["at"])
        except (ValueError, TypeError, KeyError):
            return True
        return elapsed >= timedelta(hours=self._settings.sweep_hours)

    def _swept_orphans(self) -> int:
        """Held untracked versions the last complete sweep found."""
        raw = _read_state(self._settings.state_dir / SWEEP_STATE_FILE)
        held = raw.get("held_orphans") if isinstance(raw, dict) else None
        return held if isinstance(held, int) else 0

    async def _mismatches(self, tenants: list[str], report: PassReport, complete: bool) -> int:
        # This pass's sweep once it is recorded; otherwise the last recorded sweep's.
        swept = report.swept_held if report.swept and complete else self._swept_orphans()
        total = swept + report.held_orphans
        for tenant in tenants:
            try:
                total += await self._store.hold_mismatches(tenant)
            except RecordingStorageUnavailable:
                pass  # its pass failed too, and counts as overdue
        return total

    def _record_failures(self, tenants: set[str], failed: set[str], now: datetime) -> None:
        path = self._settings.state_dir / FAILURES_STATE_FILE
        raw = _read_state(path)
        known = raw if isinstance(raw, dict) else {}
        since = {
            tenant: known.get(tenant, now.isoformat()) for tenant in failed if tenant in tenants
        }
        if since != known:
            _write_state(path, since)

    async def _overdue_seconds(self, tenants: list[str], now: datetime, failed: set[str]) -> float:
        """How long the oldest step this site owes has been overdue; 0 when none is."""
        moments = []
        raw = _read_state(self._settings.state_dir / FAILURES_STATE_FILE)
        for tenant, since in (raw if isinstance(raw, dict) else {}).items():
            try:
                moments.append(datetime.fromisoformat(since))
            except (TypeError, ValueError):
                moments.append(now)
        for tenant in set(tenants) - failed:
            try:
                if (moment := await self._store.overdue_since(tenant, now)) is not None:
                    moments.append(moment)
            except RecordingStorageUnavailable:
                moments.append(now)
        return max(0.0, (now - min(moments)).total_seconds()) if moments else 0.0

    async def run_forever(self) -> None:
        while True:
            try:
                report = await self.run_once()
                if report.halted:
                    sys.stderr.write("Retention halted: the database is behind the audit mark\n")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # The type only: a driver or storage error can quote a DSN or a key.
                sys.stderr.write(f"Retention pass failed ({type(error).__name__})\n")
            await asyncio.sleep(self._settings.interval_seconds)
