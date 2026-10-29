"""One retention pass: every tenant, the restore guard, and the heartbeat."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from pathlib import Path

import pytest

from services.api_gateway.recording.retention import locks
from services.api_gateway.recording.retention.restore_guard import AuditHighWater, AuditMark
from services.api_gateway.recording.retention.settings import WorkerSettings
from services.api_gateway.recording.retention.worker import RetentionWorker
from services.api_gateway.recording.storage.archive import (
    ArchiveNotFoundError,
    ArchiveRefusedError,
)
from services.api_gateway.recording.storage.filesystem import FilesystemArchiveStore
from services.api_gateway.recording.storage.sigv4 import Credentials
from tests.recording_retention_fakes import NOW, TENANT, Failing, FakeRetentionStore, due_row

HELD_AND_LIFTED = {
    "held": True,
    "held_since": NOW - timedelta(hours=2),
    "hold_off_at": NOW - timedelta(hours=1),
}


def _settings(tmp_path: Path) -> WorkerSettings:
    return WorkerSettings(
        site="primary",
        endpoint="http://seaweedfs.test:8333",
        credentials=Credentials("k", "s"),
        database_url="postgresql://unused",
        database_password="unused",
        state_dir=tmp_path / "state",
    )


def _worker(tmp_path, store, archive=None, at=NOW) -> RetentionWorker:
    archive = archive or FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31))
    return RetentionWorker(
        _settings(tmp_path),
        store,
        archive,
        AuditHighWater(tmp_path / "state"),
        clock=lambda: at,
    )


def _tripped(tmp_path) -> None:
    """A mark for an event the database no longer holds: it was restored."""
    with AuditHighWater(tmp_path / "state").locked() as guard:
        guard.observe(False, {TENANT: AuditMark(9, "lost")})


async def _held_in_store(tmp_path):
    archive = FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31))
    stored = await archive.put(TENANT, due_row().key, b"c")
    await archive.set_legal_hold(TENANT, due_row().key, stored.version_id, True)
    return archive, stored.version_id


async def test_a_pass_covers_every_tenant_and_beats(tmp_path):
    store = FakeRetentionStore(positions={TENANT: 4, "tenant-b": 2})
    report = await _worker(tmp_path, store).run_once()
    assert store.discovered == [TENANT, "tenant-b"]
    assert (report.tenants, report.halted) == (2, False)
    assert store.beats == [(NOW, 0.0, False, 0)]


async def test_a_tenant_whose_database_fails_is_skipped_and_the_rest_run(tmp_path):
    store = FakeRetentionStore(positions={TENANT: 4, "tenant-b": 2})
    store.unavailable = {TENANT}
    report = await _worker(tmp_path, store).run_once()
    assert store.discovered == ["tenant-b"]
    assert report.failures == 1
    assert len(store.beats) == 1


async def test_the_heartbeat_reports_the_oldest_failure_and_the_mismatches(tmp_path):
    held = due_row(version_id="v1", held=True, held_since=NOW - timedelta(hours=2))
    extending = due_row(version_id="v2", retention_until=NOW + timedelta(days=60))
    store = FakeRetentionStore(held, extending)
    store.failing["v2"] = NOW - timedelta(hours=3)
    archive = Failing(
        FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31)),
        "extend_retention",
        ArchiveRefusedError("AccessDenied"),
    )

    report = await _worker(tmp_path, store, archive).run_once()

    assert (report.mismatches, report.failures) == (1, 1)
    assert store.beats == [(NOW, 3 * 3600.0, False, 1)]


async def test_a_database_behind_the_audit_mark_halts_destructive_steps(tmp_path):
    _tripped(tmp_path)
    archive, version = await _held_in_store(tmp_path)
    store = FakeRetentionStore(
        due_row(version_id=version, **HELD_AND_LIFTED), positions={TENANT: 4}
    )

    report = await _worker(tmp_path, store, archive).run_once()

    assert report.halted is True
    assert store.beats[0][2] is True
    # Re-read from the store, the hold counts from now: the older hold_off cannot lift it.
    state, revisit = store.recorded[version]
    assert (state.held, state.held_since) == (True, NOW)
    assert revisit == NOW + timedelta(hours=1)
    assert report.mismatches == 1
    assert (await archive.retention(TENANT, due_row().key, version)).legal_hold is True


async def test_a_restore_re_reads_every_version_and_a_lost_hold_blocks_expiry(tmp_path):
    archive, version = await _held_in_store(tmp_path)
    # The restored rows: checked before the hold was set, conversation past its date.
    restored = due_row(
        version_id=version,
        retention_until=NOW - timedelta(days=1),
        locked_until=NOW - timedelta(hours=1),
        next_attempt_at=NOW + timedelta(days=1),
    )
    store = FakeRetentionStore(restored, positions={TENANT: 6})
    store.conversation(restored.conversation_id, due=True)
    with AuditHighWater(tmp_path / "state").locked() as guard:
        guard.observe(False, {TENANT: AuditMark(6, f"{TENANT}:6")})
    store.restore(TENANT, 4)  # gone: events 5 and 6, though the chain grew past them

    halted = await _worker(tmp_path, store, archive).run_once()

    assert halted.halted is True and store.rechecked == [TENANT]
    assert store.recorded[version][0].held is True
    assert (halted.mismatches, halted.shredded) == (1, 0)

    with AuditHighWater(tmp_path / "state").locked() as guard:
        assert guard.recheck == set()
        guard.acknowledge({TENANT: await store.audit_mark(TENANT)})
    resumed = await _worker(tmp_path, store, archive, at=NOW + timedelta(hours=2)).run_once()

    assert (resumed.halted, resumed.shredded, resumed.mismatches) == (False, 0, 1)
    assert store.beats[-1][3] == 1


async def test_the_mismatch_count_holds_between_the_passes_that_see_it(tmp_path):
    store = FakeRetentionStore(due_row(held=True, held_since=NOW - timedelta(hours=2)))
    for minutes in (0, 5, 60):
        await _worker(tmp_path, store, at=NOW + timedelta(minutes=minutes)).run_once()
    assert [beat[3] for beat in store.beats] == [1, 1, 1]


async def test_a_held_orphan_the_sweep_found_counts_until_the_next_sweep(tmp_path):
    archive, _ = await _held_in_store(tmp_path)  # its conversation has no rows at all
    store = FakeRetentionStore()
    first = await _worker(tmp_path, store, archive).run_once()
    second = await _worker(tmp_path, store, archive, at=NOW + timedelta(hours=1)).run_once()
    assert (first.swept, second.swept) == (True, False)
    assert [beat[3] for beat in store.beats] == [1, 1]


async def test_a_tenant_without_a_bucket_is_an_empty_one(tmp_path):
    store = FakeRetentionStore(positions={TENANT: 1, "tenant-b": 1})
    archive = Failing(
        FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31)),
        "list_versions",
        ArchiveNotFoundError("NoSuchBucket"),
    )
    report = await _worker(tmp_path, store, archive).run_once()
    assert (report.failures, report.swept) == (0, True)
    assert store.discovered == [TENANT, "tenant-b"]


async def test_a_tenant_the_store_refuses_fails_alone_and_counts_as_overdue(tmp_path):
    store = FakeRetentionStore(positions={TENANT: 1, "tenant-b": 1})
    archive = Failing(
        FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31)),
        "list_versions",
        ArchiveRefusedError("AccessDenied"),
    )
    first = await _worker(tmp_path, store, archive).run_once()
    later = await _worker(tmp_path, store, archive, at=NOW + timedelta(hours=2)).run_once()

    assert (first.failures, later.failures) == (2, 2)
    assert store.discovered == [TENANT, "tenant-b"] * 2
    assert [beat[1] for beat in store.beats] == [0.0, 7200.0]

    await _worker(tmp_path, store, at=NOW + timedelta(hours=3)).run_once()
    assert store.beats[-1][1] == 0.0


async def test_rows_a_pass_could_not_reach_count_as_overdue(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "BATCH", 1)
    monkeypatch.setattr(locks, "MAX_BATCHES", 1)
    behind = NOW - timedelta(hours=5)
    store = FakeRetentionStore(
        due_row(version_id="v1", next_attempt_at=behind),
        due_row(version_id="v2", next_attempt_at=behind),
    )
    report = await _worker(tmp_path, store).run_once()
    assert report.processed == 1
    assert store.beats[-1][1] == 5 * 3600.0


async def test_an_unhalted_pass_lifts_the_same_hold(tmp_path):
    archive = FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31))
    stored = await archive.put(TENANT, due_row().key, b"c")
    await archive.set_legal_hold(TENANT, due_row().key, stored.version_id, True)
    store = FakeRetentionStore(due_row(version_id=stored.version_id, **HELD_AND_LIFTED))
    await _worker(tmp_path, store, archive).run_once()
    assert store.recorded[stored.version_id][0].held is False


@pytest.mark.parametrize("error", [RuntimeError("boom"), OSError("disk")])
async def test_the_loop_survives_a_failed_pass_and_names_only_its_type(
    tmp_path, monkeypatch, capsys, error
):
    worker = _worker(tmp_path, FakeRetentionStore())
    sleeps = []

    async def fail():
        raise error

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(worker, "run_once", fail)
    monkeypatch.setattr("services.api_gateway.recording.retention.worker.asyncio.sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        await worker.run_forever()
    assert sleeps == [300.0, 300.0]
    err = capsys.readouterr().err
    assert type(error).__name__ in err
    assert str(error) not in err


def _replica(tmp_path, store, archive=None) -> RetentionWorker:
    settings = dataclasses.replace(_settings(tmp_path), site="replica")
    return RetentionWorker(
        settings,
        store,
        archive or FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31)),
        AuditHighWater(tmp_path / "state"),
        clock=lambda: NOW,
    )


async def test_the_primary_shreds_clears_deletes_rows_and_sweeps(tmp_path):
    store = FakeRetentionStore()
    store.conversation("due", due=True)
    store.cleared_elsewhere = {"due"}

    report = await _worker(tmp_path, store).run_once()

    assert (report.shredded, report.cleared, report.rows_deleted, report.swept) == (1, 1, 1, True)
    assert store.rows_deleted == ["due"]
    assert store.steps == ["due_expiries", "clearable", "deletable", "known_conversations"]


async def test_the_replica_never_shreds_or_deletes_rows(tmp_path):
    store = FakeRetentionStore()
    store.conversation("due", due=True)
    store.conversation("shredded", shredded=True)
    store.cleared_elsewhere = {"shredded"}

    await _replica(tmp_path, store).run_once()

    assert "due_expiries" not in store.steps and "deletable" not in store.steps
    assert store.cleared == {"shredded"}
    assert store.rows_deleted == [] and store.shred_actors == []


async def test_a_tripped_guard_runs_no_destructive_step(tmp_path):
    _tripped(tmp_path)
    store = FakeRetentionStore(positions={TENANT: 4})
    store.conversation("due", due=True)

    report = await _worker(tmp_path, store).run_once()

    assert report.halted is True and report.swept is False
    assert store.steps == []
    assert store.shred_actors == []


async def test_the_sweep_runs_once_per_sweep_hours(tmp_path):
    store = FakeRetentionStore()
    first = await _worker(tmp_path, store).run_once()
    store.steps.clear()
    again = RetentionWorker(
        _settings(tmp_path),
        store,
        FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31)),
        AuditHighWater(tmp_path / "state"),
        clock=lambda: NOW + timedelta(hours=23),
    )
    second = await again.run_once()
    later = RetentionWorker(
        _settings(tmp_path),
        store,
        FilesystemArchiveStore(tmp_path / "archive", timedelta(days=31)),
        AuditHighWater(tmp_path / "state"),
        clock=lambda: NOW + timedelta(hours=24),
    )
    third = await later.run_once()
    assert (first.swept, second.swept, third.swept) == (True, False, True)


async def test_an_incomplete_pass_does_not_count_as_a_sweep(tmp_path):
    store = FakeRetentionStore(positions={TENANT: 4, "tenant-b": 1})
    store.unavailable = {"tenant-b"}
    await _worker(tmp_path, store).run_once()
    store.unavailable = set()
    assert (await _worker(tmp_path, store).run_once()).swept is True


async def test_a_lapsed_version_goes_in_the_pass_that_shreds_it(tmp_path):
    moments = [NOW - timedelta(days=40)]
    archive = FilesystemArchiveStore(
        tmp_path / "archive", timedelta(days=31), clock=lambda: moments[-1]
    )
    stored = await archive.put(TENANT, due_row().key, b"c")
    moments.append(NOW)
    row = due_row(
        version_id=stored.version_id,
        retention_until=NOW - timedelta(days=1),
        locked_until=NOW - timedelta(days=9),
        next_attempt_at=NOW + timedelta(days=1),
    )
    store = ShreddingStore(row)
    store.conversation(row.conversation_id, due=True)

    report = await _worker(tmp_path, store, archive).run_once()

    assert report.shredded == 1
    assert await archive.list_versions(TENANT, "") == []
    assert report.cleared == 1


class ShreddingStore(FakeRetentionStore):
    """Shredding marks the conversation's rows shredded and due, as the real store does."""

    async def shred(self, tenant_id, conversation_id, now, actor):
        shredded = await super().shred(tenant_id, conversation_id, now, actor)
        for version, row in list(self.rows.items()):
            if row.conversation_id == conversation_id:
                self.rows[version] = dataclasses.replace(row, shredded_at=now, next_attempt_at=now)
        return shredded
