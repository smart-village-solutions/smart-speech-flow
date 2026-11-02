"""The nightly revocation check (spec §10.7, §17).

It deletes wraps on its own, driven by the Studio directory, so it trusts a
directory only after it reads the same revision twice, finds it plausible, and
sees that it would not revoke more than a bound. Anything doubtful skips the
tenant, which is audited and leaves the last-success metric to age into its
alert; an operator confirms a real mass removal with `--allow-mass`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

from prometheus_client import CollectorRegistry, Gauge

from ..clock import utc_now
from ..studio_recording_directory_client import RecordingDirectory
from .permissions import REVIEW, SUPERVISE
from .recovery_requests_model import SYSTEM_ACTOR
from .repository import RecordingStorageUnavailable
from .revocation_repository import Grants

logger = logging.getLogger(__name__)

LOCAL_ZONE: Final[str] = "Europe/Berlin"
STARTS_AT_HOUR: Final[int] = 2
STABILITY_SECONDS: Final[float] = 60.0
RECLAIM_AFTER: Final[timedelta] = timedelta(hours=6)
CHECK_INTERVAL_SECONDS: Final[float] = 15 * 60
# More than this many grantees and this share of all of them is a mass removal.
BOUND_COUNT: Final[int] = 2
BOUND_SHARE: Final[float] = 0.25
OPERATOR_ACTOR: Final[str] = "operator"


class Snapshots(Protocol):
    async def snapshot(self, tenant_id: str, correlation_id: str) -> RecordingDirectory | None: ...


class RevocationStore(Protocol):
    async def key_holders(self, tenant_id: str) -> frozenset[str]: ...

    async def grants(self, tenant_id: str) -> Grants: ...

    async def revoke(
        self,
        tenant_id: str,
        conversation_id: str,
        withdraw: Sequence[str],
        unsupervised: Sequence[str],
        actor: str,
        now: datetime,
    ) -> int: ...

    async def skipped(
        self, tenant_id: str, guard: str, day: date, now: datetime, actor: str
    ) -> None: ...


def _local(now: datetime) -> datetime:
    return now.astimezone(ZoneInfo(LOCAL_ZONE))


def run_date(now: datetime) -> date:
    return _local(now).date()


def due(now: datetime) -> bool:
    return _local(now).hour >= STARTS_AT_HOUR


def _members(directory: RecordingDirectory) -> frozenset[str]:
    return frozenset(user.sub for user in directory.users)


def _mass_removal(affected: set[str], grantees: set[str]) -> bool:
    return len(affected) > BOUND_COUNT and len(affected) > BOUND_SHARE * len(grantees)


class RevocationCheck:
    def __init__(
        self,
        store: RevocationStore,
        directory: Snapshots,
        *,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        stability_seconds: float = STABILITY_SECONDS,
    ) -> None:
        self._store = store
        self._directory = directory
        self._clock = clock
        self._sleep = sleep
        self._stability = stability_seconds

    async def _trusted(self, tenant_id: str, correlation_id: str) -> RecordingDirectory | str:
        """The directory, or the guard it failed."""
        first = await self._directory.snapshot(tenant_id, correlation_id)
        if first is None:
            return "unreadable"
        holders = await self._store.key_holders(tenant_id)
        # An empty or truncated answer would revoke everyone (§9.8's plausibility check).
        if holders and _members(first).isdisjoint(holders):
            return "implausible"
        await self._sleep(self._stability)
        second = await self._directory.snapshot(tenant_id, correlation_id)
        if second is None or second.directory_revision != first.directory_revision:
            return "unstable"
        return first

    async def run_tenant(
        self,
        tenant_id: str,
        correlation_id: str,
        *,
        allow_mass: bool = False,
        actor: str = SYSTEM_ACTOR,
    ) -> str:
        """The outcome recorded for the run: `done` or `skipped_<guard>`."""
        read_at = self._clock()
        trusted = await self._trusted(tenant_id, correlation_id)
        if isinstance(trusted, str):
            return await self._skip(tenant_id, trusted, actor)
        grants = await self._store.grants(tenant_id)
        reviewers = set(trusted.holders_of(REVIEW))
        supervisors = set(trusted.holders_of(SUPERVISE))
        withdraw = [
            item
            for item in grants.assignments
            if item.reviewer_sub not in reviewers and item.directory_read_at < read_at
        ]
        unsupervised = [(cid, sub) for cid, sub in grants.recovered if sub not in supervisors]
        affected = {item.reviewer_sub for item in withdraw} | {sub for _, sub in unsupervised}
        grantees = {item.reviewer_sub for item in grants.assignments}
        grantees |= {sub for _, sub in grants.recovered}
        if not allow_mass and _mass_removal(affected, grantees):
            return await self._skip(tenant_id, "bound", actor)
        conversations = sorted(
            {item.conversation_id for item in withdraw}
            | {cid for cid, _ in unsupervised}
            | set(grants.orphaned)
        )
        for conversation_id in conversations:
            await self._store.revoke(
                tenant_id,
                conversation_id,
                [
                    item.verification_id
                    for item in withdraw
                    if item.conversation_id == conversation_id
                ],
                [sub for cid, sub in unsupervised if cid == conversation_id],
                actor,
                self._clock(),
            )
        return "done"

    async def _skip(self, tenant_id: str, guard: str, actor: str) -> str:
        now = self._clock()
        await self._store.skipped(tenant_id, guard, run_date(now), now, actor)
        logger.warning("recording_revocation_skipped guard=%s", guard)
        return f"skipped_{guard}"


class RevocationMetrics:
    """The oldest last success across tenants, NaN while there is no tenant to check.

    NaN keeps a gateway without recording out of the alert. A tenant never
    checked at all counts from this process's start; one that ran but never
    succeeded counts from its first run, which a restart does not reset.
    """

    def __init__(self, registry: CollectorRegistry, *, started_at: datetime | None = None) -> None:
        self._started_at = started_at or utc_now()
        self._gauge = Gauge(
            "ssf_recording_revocation_last_success_timestamp_seconds",
            "When the nightly revocation check last succeeded, for the tenant it is oldest for",
            registry=registry,
        )
        self._gauge.set(float("nan"))

    def update(self, owed_since: Mapping[str, datetime | None]) -> None:
        times = [at or self._started_at for at in owed_since.values()]
        self._gauge.set(min(times).timestamp() if times else float("nan"))


class Runs(Protocol):
    async def claim(
        self, tenant_id: str, day: date, now: datetime, reclaim_after: timedelta
    ) -> bool: ...

    async def finish(self, tenant_id: str, day: date, outcome: str, now: datetime) -> None: ...

    async def owed_since(self, tenant_id: str) -> datetime | None: ...


async def run_due(
    check: RevocationCheck,
    runs: Runs,
    tenants: Iterable[str],
    now: datetime,
    metrics: RevocationMetrics | None = None,
) -> dict[str, str]:
    """Each writer tenant's run for today, if this gateway claims it first."""
    outcomes: dict[str, str] = {}
    if due(now):
        for tenant_id in tenants:
            day = run_date(now)
            if not await runs.claim(tenant_id, day, now, RECLAIM_AFTER):
                continue
            try:
                outcomes[tenant_id] = await check.run_tenant(tenant_id, f"revocation-{day}")
            except RecordingStorageUnavailable:
                # Left unfinished: the run is claimed again after RECLAIM_AFTER, the same day.
                outcomes[tenant_id] = "failed"
                continue
            await runs.finish(tenant_id, day, outcomes[tenant_id], now)
    if metrics is not None:
        metrics.update({tenant_id: await runs.owed_since(tenant_id) for tenant_id in tenants})
    return outcomes


async def revocation_task(state: Any) -> None:
    """Every quarter hour, from the start: the night's run once due, and the metric either way."""
    while True:
        wiring = getattr(state, "recording_revocation", None)
        if wiring is not None:
            check, runs, tenants = wiring
            try:
                await run_due(check, runs, tuple(tenants()), utc_now(), state.revocation_metrics)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                sys.stderr.write(f"Recording revocation check failed ({type(error).__name__})\n")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the recording revocation check now.")
    parser.add_argument("--tenant", required=True)
    parser.add_argument(
        "--allow-mass",
        action="store_true",
        help="Revoke even past the mass-removal bound, after confirming the removal is real.",
    )
    return parser.parse_args(argv)


async def operator_run(argv: Sequence[str], check: RevocationCheck) -> str:
    """An operator's run outside the schedule; it neither claims nor finishes a nightly run."""
    arguments = _arguments(argv)
    return await check.run_tenant(
        arguments.tenant,
        "revocation-operator",
        allow_mass=arguments.allow_mass,
        actor=OPERATOR_ACTOR,
    )
