"""The nightly revocation check: its guards, its bound and what it revokes (spec §10.7)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.recording.revocation import (
    RevocationCheck,
    RevocationMetrics,
    due,
    run_date,
)
from services.api_gateway.recording.revocation_repository import Assignment, Grants
from tests.recording_verification_world import TENANT, directory

NOW = datetime(2026, 11, 3, 2, 30, tzinfo=timezone.utc)
BEFORE = NOW - timedelta(days=1)
REVIEW = ["ssf.recording.review"]
SUPERVISE = ["ssf.recording.supervise"]


class Studio:
    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.reads = 0

    async def snapshot(self, tenant_id, correlation_id):
        self.reads += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Store:
    def __init__(self, grants: Grants, holders=frozenset({"alice"})) -> None:
        self._grants, self.holders = grants, holders
        self.revoked: list = []
        self.skips: list = []

    async def key_holders(self, tenant_id):
        return self.holders

    async def grants(self, tenant_id):
        return self._grants

    async def revoke(self, tenant_id, conversation_id, withdraw, unsupervised, actor, now):
        self.revoked.append((conversation_id, tuple(withdraw), tuple(unsupervised), actor))
        return len(withdraw) + len(unsupervised)

    async def skipped(self, tenant_id, guard, day, now, actor):
        self.skips.append(guard)
        self.skip_actors = getattr(self, "skip_actors", []) + [actor]


async def _no_sleep(seconds):
    return None


def _check(store, studio, **kwargs) -> RevocationCheck:
    return RevocationCheck(store, studio, clock=lambda: NOW, sleep=_no_sleep, **kwargs)


def _grants(*assignments, recovered=(), orphaned=()) -> Grants:
    return Grants(tuple(assignments), tuple(recovered), tuple(orphaned))


def _people(*removed: str):
    users = [
        ("alice", REVIEW),
        ("sam", SUPERVISE),
        ("rita", REVIEW),
        ("ralf", REVIEW),
        ("rosa", REVIEW),
        ("rolf", REVIEW),
        ("sven", SUPERVISE),
    ]
    return directory(*[u for u in users if u[0] not in removed])


async def test_a_removed_reviewer_is_withdrawn_and_a_kept_one_untouched():
    grants = _grants(
        Assignment("v-1", "c-1", "rita", BEFORE), Assignment("v-2", "c-2", "ralf", BEFORE)
    )
    store = Store(grants)

    outcome = await _check(store, Studio(_people("rita"))).run_tenant(TENANT, "corr")

    assert outcome == "done"
    assert store.revoked == [("c-1", ("v-1",), (), "system")]


async def test_a_supervisor_without_supervise_loses_recovered_wraps():
    store = Store(_grants(recovered=[("c-3", "sam"), ("c-4", "sven")]))
    assert await _check(store, Studio(_people("sam"))).run_tenant(TENANT, "corr") == "done"
    assert store.revoked == [("c-3", (), ("sam",), "system")]


async def test_an_assignment_read_after_the_check_started_survives():
    """Its own directory read is newer than the check's first read (§10.7)."""
    store = Store(_grants(Assignment("v-1", "c-1", "rita", NOW + timedelta(seconds=1))))
    await _check(store, Studio(_people("rita"))).run_tenant(TENANT, "corr")
    assert store.revoked == []


async def test_orphaned_wraps_are_swept_without_counting_towards_the_bound():
    store = Store(_grants(orphaned=["c-9"]))
    assert await _check(store, Studio(_people())).run_tenant(TENANT, "corr") == "done"
    assert store.revoked == [("c-9", (), (), "system")]


@pytest.mark.parametrize(
    ("studio", "holders", "guard"),
    [
        (Studio(None), frozenset({"alice"}), "unreadable"),
        (Studio(directory()), frozenset({"alice"}), "implausible"),
        (Studio(directory(("nobody", REVIEW))), frozenset({"alice"}), "implausible"),
        (Studio(_people(), None), frozenset({"alice"}), "unstable"),
        (Studio(_people("rita"), _people("rita", "ralf")), frozenset({"alice"}), "unstable"),
    ],
)
async def test_a_doubtful_directory_revokes_nothing(studio, holders, guard):
    store = Store(_grants(Assignment("v-1", "c-1", "rita", BEFORE)), holders)
    assert await _check(store, studio).run_tenant(TENANT, "corr") == f"skipped_{guard}"
    assert store.revoked == [] and store.skips == [guard]


async def test_a_tenant_without_key_holders_is_plausible_with_any_directory():
    store = Store(_grants(), holders=frozenset())
    assert await _check(store, Studio(directory())).run_tenant(TENANT, "corr") == "done"


async def test_the_second_read_waits_the_stability_interval():
    waited = []

    async def sleep(seconds):
        waited.append(seconds)

    studio = Studio(_people())
    await RevocationCheck(Store(_grants()), studio, clock=lambda: NOW, sleep=sleep).run_tenant(
        TENANT, "c"
    )
    assert waited == [60] and studio.reads == 2


def _mass(n_removed: int, n_total: int) -> Store:
    subs = [f"r{i}" for i in range(n_total)]
    return (
        Store(_grants(*[Assignment(f"v-{s}", f"c-{s}", s, BEFORE) for s in subs])),
        subs[:n_removed],
        subs,
    )


@pytest.mark.parametrize(
    ("removed", "total", "outcome"), [(3, 4, "skipped_bound"), (3, 20, "done"), (2, 2, "done")]
)
async def test_the_bound_stops_a_mass_removal(removed, total, outcome):
    store, gone, subs = _mass(removed, total)
    users = [("alice", REVIEW)] + [(s, REVIEW) for s in subs if s not in gone]
    assert await _check(store, Studio(directory(*users))).run_tenant(TENANT, "c") == outcome
    assert bool(store.revoked) is (outcome == "done")


async def test_an_operator_may_confirm_a_mass_removal():
    store, gone, subs = _mass(3, 4)
    users = [("alice", REVIEW)] + [(s, REVIEW) for s in subs if s not in gone]
    outcome = await _check(store, Studio(directory(*users))).run_tenant(
        TENANT, "c", allow_mass=True, actor="operator"
    )
    assert outcome == "done" and {r[3] for r in store.revoked} == {"operator"}


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (datetime(2026, 11, 3, 0, 59, tzinfo=timezone.utc), False),  # 01:59 in Berlin (CET)
        (datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 7, 3, 0, 0, tzinfo=timezone.utc), True),  # 02:00 in Berlin (CEST)
        (datetime(2026, 7, 2, 23, 59, tzinfo=timezone.utc), False),
    ],
)
def test_the_check_is_due_after_two_in_berlin(at, expected):
    assert due(at) is expected


def test_the_run_date_is_berlins():
    assert run_date(datetime(2026, 11, 2, 23, 30, tzinfo=timezone.utc)) == date(2026, 11, 3)


def test_the_metric_is_nan_until_there_is_a_tenant_to_check():
    """A gateway without recording must never age into RecordingRevocationStale."""
    import math

    registry = CollectorRegistry()
    metrics = RevocationMetrics(registry, started_at=NOW)
    name = "ssf_recording_revocation_last_success_timestamp_seconds"
    assert math.isnan(registry.get_sample_value(name))
    metrics.update({})
    assert math.isnan(registry.get_sample_value(name))


def test_the_metric_is_the_oldest_last_success_and_a_new_tenant_counts_from_start():
    registry = CollectorRegistry()
    metrics = RevocationMetrics(registry, started_at=NOW)
    metrics.update({"a": NOW - timedelta(hours=30), "b": None})
    assert (
        registry.get_sample_value("ssf_recording_revocation_last_success_timestamp_seconds")
        == (NOW - timedelta(hours=30)).timestamp()
    )
    metrics.update({"b": None})
    assert (
        registry.get_sample_value("ssf_recording_revocation_last_success_timestamp_seconds")
        == NOW.timestamp()
    )


class Runs:
    def __init__(self, claim=True, fail=False) -> None:
        self._claim, self.finished, self.fail = claim, [], fail

    async def claim(self, tenant_id, day, now, reclaim_after):
        return self._claim

    async def finish(self, tenant_id, day, outcome, now):
        self.finished.append((tenant_id, outcome))

    async def owed_since(self, tenant_id):
        return None


class FailingCheck:
    async def run_tenant(self, tenant_id, correlation_id):
        from services.api_gateway.recording.repository import RecordingStorageUnavailable

        raise RecordingStorageUnavailable("down")


async def test_run_due_waits_for_the_night_claims_and_records_failures():
    from services.api_gateway.recording.revocation import run_due

    store = Store(_grants())
    check = _check(store, Studio(_people()))
    registry = CollectorRegistry()
    metrics = RevocationMetrics(registry, started_at=NOW)
    early = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
    assert await run_due(check, Runs(), [TENANT], early, metrics) == {}
    assert await run_due(check, Runs(claim=False), [TENANT], NOW) == {}
    runs = Runs()
    assert await run_due(check, runs, [TENANT], NOW) == {TENANT: "done"}
    assert runs.finished == [(TENANT, "done")]
    failing = Runs()
    assert await run_due(FailingCheck(), failing, [TENANT], NOW) == {TENANT: "failed"}
    assert failing.finished == []  # left unfinished, so the reclaim retries it the same day


async def test_the_task_runs_once_per_interval_and_survives_a_failure(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from services.api_gateway.recording import revocation

    calls = []
    sleeps = iter([None, asyncio.CancelledError()])

    async def sleep(seconds):
        step = next(sleeps)
        if isinstance(step, BaseException):
            raise step

    async def broken_run_due(*args):
        calls.append(args[2])
        raise ValueError("broken")

    monkeypatch.setattr(revocation.asyncio, "sleep", sleep)
    monkeypatch.setattr(revocation, "run_due", broken_run_due)
    state = SimpleNamespace(
        recording_revocation=("check", "runs", lambda: [TENANT]), revocation_metrics=None
    )
    with pytest.raises(asyncio.CancelledError):
        await revocation.revocation_task(state)
    assert calls == [(TENANT,), (TENANT,)]  # once at start, before the first sleep


async def test_the_task_waits_while_recording_is_not_wired(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from services.api_gateway.recording import revocation

    sleeps = iter([None, asyncio.CancelledError()])

    async def sleep(seconds):
        step = next(sleeps)
        if isinstance(step, BaseException):
            raise step

    monkeypatch.setattr(revocation.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await revocation.revocation_task(SimpleNamespace(recording_revocation=None))


async def test_an_operator_run_takes_the_tenant_and_the_mass_flag():
    from services.api_gateway.recording.revocation import operator_run

    store, gone, subs = _mass(3, 4)
    users = [("alice", REVIEW)] + [(s, REVIEW) for s in subs if s not in gone]
    check = _check(store, Studio(directory(*users)))
    assert await operator_run(["--tenant", TENANT], check) == "skipped_bound"
    assert store.skip_actors == ["operator"]
    assert await operator_run(["--tenant", TENANT, "--allow-mass"], check) == "done"
    assert {r[3] for r in store.revoked} == {"operator"}


async def test_the_cli_refuses_without_recording_or_studio(monkeypatch, capsys):
    from services.api_gateway.recording import revocation_cli

    monkeypatch.delenv("SSF_RECORDING_DATABASE_PASSWORD", raising=False)
    assert await revocation_cli.main(["--tenant", TENANT]) == 2
    assert "not configured" in capsys.readouterr().err
