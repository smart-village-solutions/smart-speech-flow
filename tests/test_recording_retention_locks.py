"""Lock planning and reconciling, the heart of retention (spec §16.1)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

import pytest

from services.api_gateway.recording.retention.locks import (
    GUARD_REVISIT,
    IDLE_REVISIT,
    LockReconciler,
    plan,
)
from services.api_gateway.recording.retention.store import DueVersion
from services.api_gateway.recording.storage.archive import (
    ArchiveNotFoundError,
    ArchiveRefusedError,
    ArchiveUnavailableError,
)
from services.api_gateway.recording.storage.filesystem import FilesystemArchiveStore
from tests.recording_retention_fakes import KEY, NOW, TENANT, Failing
from tests.recording_retention_fakes import FakeRetentionStore as FakeRows
from tests.recording_retention_fakes import due_row as _row

HELD = {"held": True, "held_since": NOW - timedelta(hours=2)}
SHREDDED = {"shredded_at": NOW - timedelta(hours=1), "retention_until": NOW - timedelta(hours=1)}


@pytest.mark.parametrize(
    ("rule", "row", "destructive", "actions", "revisit", "mismatch"),
    [
        (
            "1 a row never checked is read first",
            _row(checked_at=None),
            True,
            ("check",),
            NOW,
            False,
        ),
        (
            "2 a hold decided is applied",
            _row(legal_hold=True, hold_on_at=NOW - timedelta(minutes=1)),
            True,
            ("hold_on",),
            NOW + IDLE_REVISIT,
            False,
        ),
        (
            "3 a later hold_off lifts",
            _row(**HELD, hold_off_at=NOW - timedelta(hours=1)),
            True,
            ("lift",),
            NOW + IDLE_REVISIT,
            False,
        ),
        (
            "3 no hold_off: a mismatch, not a lift",
            _row(**HELD),
            True,
            (),
            NOW + IDLE_REVISIT,
            True,
        ),
        (
            "4 a lock short of the date is extended",
            _row(retention_until=NOW + timedelta(days=60)),
            True,
            ("extend",),
            NOW + IDLE_REVISIT,
            False,
        ),
        (
            "4 an unlocked version is extended",
            _row(locked_until=None),
            True,
            ("extend",),
            NOW + IDLE_REVISIT,
            False,
        ),
        (
            "5 shredded, lock lapsed: delete",
            _row(**SHREDDED, locked_until=NOW),
            True,
            ("delete",),
            NOW + IDLE_REVISIT,
            False,
        ),
        (
            "5 shredded, still locked: wait for the lock",
            _row(**SHREDDED, locked_until=NOW + timedelta(hours=20)),
            True,
            (),
            NOW + timedelta(hours=20),
            False,
        ),
        (
            "5 shredded and held, hold lifted later: lift first",
            _row(**SHREDDED, **HELD, locked_until=NOW, hold_off_at=NOW - timedelta(hours=1)),
            True,
            ("lift",),
            NOW,
            False,
        ),
        (
            "6 halted: no lift",
            _row(**HELD, hold_off_at=NOW - timedelta(hours=1)),
            False,
            (),
            NOW + GUARD_REVISIT,
            True,
        ),
        (
            "6 halted: no delete",
            _row(**SHREDDED, locked_until=NOW - timedelta(days=1)),
            False,
            (),
            NOW + GUARD_REVISIT,
            False,
        ),
        (
            "6 halted: holds and extensions still apply",
            _row(legal_hold=True, hold_on_at=NOW, retention_until=NOW + timedelta(days=60)),
            False,
            ("hold_on", "extend"),
            NOW + GUARD_REVISIT,
            False,
        ),
        ("7 in order: idle for a day", _row(), True, (), NOW + IDLE_REVISIT, False),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_plan(rule, row, destructive, actions, revisit, mismatch):
    planned = plan(row, NOW, destructive=destructive)
    assert (planned.actions, planned.revisit_at, planned.mismatch) == (actions, revisit, mismatch)


def test_an_older_hold_off_never_lifts_a_hold_found_after_a_restore():
    # The worker found the hold at 11:00 (after the restore); the newest hold_off is from 10:00.
    row = _row(held=True, held_since=NOW - timedelta(hours=1), hold_off_at=NOW - timedelta(hours=2))
    planned = plan(row, NOW, destructive=True)
    assert "lift" not in planned.actions
    assert planned.mismatch
    shredded = dataclasses.replace(row, **SHREDDED, locked_until=NOW - timedelta(days=1))
    assert plan(shredded, NOW, destructive=True).actions == ()


def test_a_hold_off_at_the_same_instant_does_not_lift():
    row = _row(**HELD, hold_off_at=HELD["held_since"])
    assert "lift" not in plan(row, NOW, destructive=True).actions


def test_a_lock_is_extended_to_the_retention_date_and_no_further():
    assert (
        "extend"
        not in plan(_row(locked_until=NOW + timedelta(days=30)), NOW, destructive=True).actions
    )
    assert (
        "extend"
        in plan(
            _row(locked_until=NOW + timedelta(days=30) - timedelta(seconds=1)),
            NOW,
            destructive=True,
        ).actions
    )


def test_a_shredded_version_is_deleted_only_once_its_lock_lapsed():
    for lapse, deleted in (
        (timedelta(seconds=1), False),
        (timedelta(0), True),
        (-timedelta(seconds=1), True),
    ):
        row = _row(**SHREDDED, locked_until=NOW + lapse)
        assert ("delete" in plan(row, NOW, destructive=True).actions) is deleted


def test_a_tripped_guard_neither_lifts_nor_deletes():
    rows = [
        _row(**HELD, hold_off_at=NOW),
        _row(**SHREDDED, locked_until=NOW - timedelta(days=1)),
        _row(**SHREDDED, **HELD, hold_off_at=NOW, locked_until=NOW - timedelta(days=1)),
    ]
    for row in rows:
        actions = plan(row, NOW, destructive=False).actions
        assert "lift" not in actions and "delete" not in actions


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def store(tmp_path):
    clock = Clock()
    return FilesystemArchiveStore(tmp_path, timedelta(days=31), clock=clock), clock


async def _put(archive) -> DueVersion:
    stored = await archive.put(TENANT, KEY, b"ciphertext")
    return _row(version_id=stored.version_id, checked_at=None, locked_until=None)


async def test_a_check_records_the_real_lock_and_then_acts_on_it(store):
    archive, _ = store
    row = dataclasses.replace(await _put(archive), retention_until=NOW + timedelta(days=40))
    rows = FakeRows(row)

    report = await LockReconciler(rows, archive).run(TENANT, NOW, destructive=True)

    state, revisit = rows.recorded[row.version_id]
    assert (state.checked_at, state.held, state.held_since) == (NOW, False, None)
    # The bucket locked it for 31 days; the conversation's date is later, so it was extended.
    assert state.locked_until == NOW + timedelta(days=40)
    assert (await archive.retention(TENANT, KEY, row.version_id)).retain_until == NOW + timedelta(
        days=40
    )
    assert revisit == NOW + IDLE_REVISIT
    assert (report.processed, report.failures, report.mismatches) == (1, 0, 0)


async def test_a_hold_is_applied_with_its_decision_time_and_lifted_by_a_later_hold_off(store):
    archive, _ = store
    row = await _put(archive)
    decided = NOW - timedelta(minutes=5)
    rows = FakeRows(dataclasses.replace(row, legal_hold=True, hold_on_at=decided))
    reconciler = LockReconciler(rows, archive)
    await reconciler.run(TENANT, NOW, destructive=True)
    assert (await archive.retention(TENANT, KEY, row.version_id)).legal_hold is True
    assert rows.recorded[row.version_id][0].held_since == decided

    rows.rows[row.version_id] = dataclasses.replace(
        rows.rows[row.version_id], legal_hold=False, hold_off_at=NOW, next_attempt_at=NOW
    )
    await reconciler.run(TENANT, NOW, destructive=True)
    assert (await archive.retention(TENANT, KEY, row.version_id)).legal_hold is False


async def test_a_hold_found_by_a_check_counts_from_now(store):
    archive, _ = store
    row = await _put(archive)
    await archive.set_legal_hold(TENANT, KEY, row.version_id, True)
    rows = FakeRows(dataclasses.replace(row, hold_off_at=NOW - timedelta(seconds=1)))

    report = await LockReconciler(rows, archive).run(TENANT, NOW, destructive=True)

    state, _ = rows.recorded[row.version_id]
    assert (state.held, state.held_since) == (True, NOW)
    assert (await archive.retention(TENANT, KEY, row.version_id)).legal_hold is True
    assert report.mismatches == 1


async def test_a_lapsed_shredded_version_is_deleted(store):
    archive, clock = store
    row = await _put(archive)
    clock.now = NOW + timedelta(days=32)
    rows = FakeRows(dataclasses.replace(row, **SHREDDED))
    await LockReconciler(rows, archive).run(TENANT, clock.now, destructive=True)
    assert await archive.list_versions(TENANT, "") == []
    assert rows.rows == {}


async def test_an_unreachable_store_records_a_failure_and_stops_the_tenants_pass(store):
    archive, _ = store
    first, second = await _put(archive), _row(version_id="v2", checked_at=None)
    rows = FakeRows(first, second)
    failing = Failing(archive, "retention", ArchiveUnavailableError("network_error"))

    report = await LockReconciler(rows, failing).run(TENANT, NOW, destructive=True)

    assert (report.processed, report.failures) == (1, 1)
    assert rows.failed == [first.version_id]
    assert rows.recorded == {}


async def test_a_refused_extension_is_a_failure_and_the_pass_goes_on(store):
    archive, _ = store
    first = dataclasses.replace(await _put(archive), retention_until=NOW + timedelta(days=60))
    second = dataclasses.replace(first, version_id="v2")
    rows = FakeRows(first, second)
    failing = Failing(archive, "extend_retention", ArchiveRefusedError("AccessDenied"))

    report = await LockReconciler(rows, failing).run(TENANT, NOW, destructive=True)

    assert report.failures == 2
    assert rows.failed == [first.version_id, "v2"]


async def test_a_version_gone_from_a_shredded_conversation_is_recorded_deleted(store):
    archive, _ = store
    rows = FakeRows(_row(**SHREDDED, version_id="v9", locked_until=NOW - timedelta(days=1)))
    report = await LockReconciler(rows, archive).run(TENANT, NOW, destructive=True)
    assert rows.rows == {}
    assert report.failures == 0


async def test_a_version_missing_from_a_live_conversation_is_retried(store):
    archive, _ = store
    rows = FakeRows(_row(version_id="v9", checked_at=None))
    report = await LockReconciler(rows, archive).run(TENANT, NOW, destructive=True)
    assert rows.failed == ["v9"] and report.failures == 1


async def test_a_refused_delete_rereads_the_lock_and_counts_no_failure(store):
    archive, _ = store
    row = await _put(archive)
    # The worker believes the lock lapsed; the store still holds it for 31 days.
    rows = FakeRows(dataclasses.replace(row, **SHREDDED, checked_at=NOW, locked_until=NOW))

    report = await LockReconciler(rows, archive).run(TENANT, NOW, destructive=True)

    state, revisit = rows.recorded[row.version_id]
    assert state.locked_until == NOW + timedelta(days=31)
    assert revisit == NOW + timedelta(days=31)
    assert state.deleted_at is None and report.failures == 0
    assert await archive.list_versions(TENANT, "") != []


async def test_a_backlog_is_drained_in_batches(store):
    archive, _ = store
    rows = FakeRows(*(_row(version_id=f"v{index}") for index in range(450)))
    report = await LockReconciler(rows, archive).run(TENANT, NOW, destructive=True)
    assert report.processed == 450
    assert rows.calls == 3


async def test_a_refused_delete_with_a_lapsed_lock_waits_an_hour(store):
    archive, _ = store
    row = await _put(archive)
    rows = FakeRows(dataclasses.replace(row, **SHREDDED, checked_at=NOW, locked_until=NOW))
    failing = Failing(archive, "delete_version", ArchiveRefusedError("AccessDenied"))
    failing_reads = Failing(failing, "retention", ArchiveUnavailableError("network_error"))
    await LockReconciler(rows, failing_reads).run(TENANT, NOW, destructive=True)
    assert rows.recorded[row.version_id][1] == NOW + GUARD_REVISIT


@pytest.mark.parametrize("error", [ArchiveNotFoundError("NoSuchVersion")])
async def test_a_hold_on_a_missing_live_version_is_a_failure(store, error):
    archive, _ = store
    rows = FakeRows(_row(version_id="v9", legal_hold=True, hold_on_at=NOW))
    failing = Failing(archive, "set_legal_hold", error)
    report = await LockReconciler(rows, failing).run(TENANT, NOW, destructive=True)
    assert report.failures == 1
