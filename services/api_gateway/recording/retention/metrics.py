"""The retention workers' heartbeats as the gateway's gauges (spec §16.1).

The workers run on the archive VMs, which Prometheus does not scrape; each
writes a heartbeat row, and the gateway exports the rows. The last beat is a
timestamp rather than an age, so a gateway that can no longer read the rows
leaves the age to grow in the alert rather than freezing it here. Once the
gateway has an archive, both sites are expected: one that never reported is
exported with a last beat at the epoch, so its silence alerts too.
`unconfirmed_since` is 0 while a site has read every stored version (#626).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from prometheus_client import CollectorRegistry, Gauge

SITES: Final[tuple[str, ...]] = ("primary", "replica")


@dataclass(frozen=True)
class WorkerStatus:
    site: str
    beat_at: datetime
    failing_seconds: float
    halted: bool
    hold_mismatches: int
    unconfirmed_since: datetime | None


class RetentionWorkerMetrics:
    """One app's retention series, registered once per app registry."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._last_beat = Gauge(
            "ssf_retention_worker_last_beat_timestamp_seconds",
            "When each site's retention worker last finished a pass",
            ("site",),
            registry=registry,
        )
        self._failing = Gauge(
            "ssf_retention_worker_failing_seconds",
            "How long the oldest overdue or failing retention step on each site has waited",
            ("site",),
            registry=registry,
        )
        self._halted = Gauge(
            "ssf_retention_worker_halted",
            "1 while a site's worker holds destructive steps back after a database restore",
            ("site",),
            registry=registry,
        )
        self._mismatches = Gauge(
            "ssf_retention_hold_mismatches",
            "Versions held on a site although no hold applies, awaiting a hold_off decision",
            ("site",),
            registry=registry,
        )
        self._unconfirmed = Gauge(
            "ssf_retention_unconfirmed_since_timestamp_seconds",
            "When the oldest stored version a site has never read was stored; 0 when none",
            ("site",),
            registry=registry,
        )
        self._gauges = (
            self._last_beat,
            self._failing,
            self._halted,
            self._mismatches,
            self._unconfirmed,
        )
        self._sites: set[str] = set()

    def update(self, statuses: Sequence[WorkerStatus], expected: Sequence[str] = ()) -> None:
        reported = {status.site: status for status in statuses}
        sites = set(reported) | set(expected)
        for site in self._sites - sites:
            for gauge in self._gauges:
                gauge.remove(site)
        for site in sites - set(reported):
            self._never_reported(site)
        for status in statuses:
            self._last_beat.labels(site=status.site).set(status.beat_at.timestamp())
            self._failing.labels(site=status.site).set(status.failing_seconds)
            self._halted.labels(site=status.site).set(1 if status.halted else 0)
            self._mismatches.labels(site=status.site).set(status.hold_mismatches)
            unconfirmed = status.unconfirmed_since
            self._unconfirmed.labels(site=status.site).set(
                0 if unconfirmed is None else unconfirmed.timestamp()
            )
        self._sites = sites

    def expect(self, sites: Sequence[str]) -> None:
        """Sites the rows could not be read for: known ones keep their last values."""
        for site in set(sites) - self._sites:
            self._never_reported(site)
        self._sites |= set(sites)

    def _never_reported(self, site: str) -> None:
        for gauge in self._gauges:
            gauge.labels(site=site).set(0)
