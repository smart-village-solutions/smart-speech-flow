"""The retention workers' heartbeats, exported by the gateway (spec §16.1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.recording import wiring
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.retention.metrics import RetentionWorkerMetrics, WorkerStatus

BEAT = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
FAMILIES = (
    "ssf_retention_worker_last_beat_timestamp_seconds",
    "ssf_retention_worker_failing_seconds",
    "ssf_retention_worker_halted",
    "ssf_retention_hold_mismatches",
)


def _value(registry, family, site):
    return registry.get_sample_value(family, {"site": site})


def _status(site="primary", **changes) -> WorkerStatus:
    values = {"beat_at": BEAT, "failing_seconds": 90.0, "halted": True, "hold_mismatches": 2}
    return WorkerStatus(site=site, **(values | changes))


def test_each_site_gets_all_four_series():
    registry = CollectorRegistry()
    RetentionWorkerMetrics(registry).update([_status(), _status("replica", halted=False)])
    assert [_value(registry, family, "primary") for family in FAMILIES] == [
        BEAT.timestamp(),
        90.0,
        1.0,
        2.0,
    ]
    assert _value(registry, "ssf_retention_worker_halted", "replica") == 0.0


def test_a_site_no_longer_reported_keeps_no_stale_series():
    registry = CollectorRegistry()
    metrics = RetentionWorkerMetrics(registry)
    metrics.update([_status(), _status("replica")])
    metrics.update([_status()])
    assert all(_value(registry, family, "replica") is None for family in FAMILIES)
    assert _value(registry, "ssf_retention_worker_halted", "primary") == 1.0


class Decisions:
    def __init__(self, *answers):
        self.answers = list(answers)

    async def worker_statuses(self):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


async def test_the_status_loop_exports_and_keeps_the_last_values_on_a_failed_read(
    monkeypatch, capsys
):
    registry = CollectorRegistry()
    state = SimpleNamespace(
        recording_retention=Decisions(
            [_status()], RecordingStorageUnavailable("the recording database is unavailable")
        ),
        retention_worker_metrics=RetentionWorkerMetrics(registry),
    )
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(wiring.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await wiring.recording_retention_status_task(state)

    assert sleeps == [60.0, 60.0, 60.0]
    assert _value(registry, "ssf_retention_worker_last_beat_timestamp_seconds", "primary") == (
        BEAT.timestamp()
    )
    assert "RecordingStorageUnavailable" in capsys.readouterr().err


async def test_the_status_loop_waits_while_recording_is_not_wired(monkeypatch):
    state = SimpleNamespace(recording_retention=None, retention_worker_metrics=None)
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(wiring.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await wiring.recording_retention_status_task(state)
