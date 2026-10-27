"""The spool keeps order, survives a restart, never drops, and says when it is full (spec §12.3)."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import stat
import threading
import time
from datetime import timedelta

import pytest

from services.api_gateway.recording.storage.archive import (
    ArchiveNotFoundError,
    ArchiveRefusedError,
    ArchiveUnavailableError,
    StoredVersion,
    object_key,
)
from services.api_gateway.recording.storage.filesystem import FilesystemArchiveStore
from services.api_gateway.recording.storage.spool import (
    ArchiveSpool,
    ArchiveUploader,
    SpoolFullError,
)
from services.api_gateway.session_pseudonym import tenant_ref

TENANT = "tenant-kassel"


def _key(number: int) -> str:
    return object_key(
        f"0d6c2b1a-9e8f-4d7c-b6a5-{number:012x}",
        "1e7d3c2b-0f9e-4e8d-a7b6-5a4f3e2d1c0b",
        "record.json",
    )


class Recorder:
    def __init__(self) -> None:
        self.stored: list[tuple[int, StoredVersion]] = []
        self.fail_next = False

    async def __call__(self, item, stored) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("database down")
        self.stored.append((item.seq, stored))


class Outage:
    """A writer that fails while `down`, then delegates."""

    def __init__(self, inner) -> None:
        self.inner, self.down, self.puts = inner, True, 0

    async def put(self, tenant_id, key, data):
        self.puts += 1
        if self.down:
            raise ArchiveUnavailableError("network_error")
        return await self.inner.put(tenant_id, key, data)

    async def head(self, tenant_id, key):
        return await self.inner.head(tenant_id, key)

    async def get(self, tenant_id, key, version_id):
        return await self.inner.get(tenant_id, key, version_id)


@pytest.fixture
def store(tmp_path):
    return FilesystemArchiveStore(tmp_path / "store", timedelta(days=3))


def test_a_submit_beyond_capacity_is_refused(tmp_path):
    spool = ArchiveSpool(tmp_path / "spool", capacity_bytes=10)
    spool.submit(TENANT, _key(1), b"123456")
    assert not spool.has_room(5)
    with pytest.raises(SpoolFullError):
        spool.submit(TENANT, _key(2), b"12345")
    assert (spool.pending, spool.used_bytes) == (1, 6)


def test_a_restart_finds_complete_items_in_order_and_discards_partial_ones(tmp_path):
    directory = tmp_path / "spool"
    spool = ArchiveSpool(directory)
    for number in (1, 2):
        spool.submit(TENANT, _key(number), f"ciphertext-{number}".encode())
    (directory / f"{3:020d}.bin").write_bytes(b"crashed before its metadata")
    (directory / f"{4:020d}.bin.tmp").write_bytes(b"crashed mid-write")

    again = ArchiveSpool(directory)
    assert (again.pending, again.oldest().seq) == (2, 1)
    assert again.read(again.oldest()) == b"ciphertext-1"
    assert sorted(path.name for path in directory.iterdir()) == [
        f"{1:020d}.bin",
        f"{1:020d}.json",
        f"{2:020d}.bin",
        f"{2:020d}.json",
    ]
    assert again.submit(TENANT, _key(3), b"next").seq == 3


async def test_submits_from_many_threads_each_get_their_own_item(tmp_path):
    spool = ArchiveSpool(tmp_path / "spool")
    payloads = {_key(number): f"ciphertext-{number}".encode() * 4096 for number in range(1, 41)}
    items = await asyncio.gather(
        *(asyncio.to_thread(spool.submit, TENANT, key, data) for key, data in payloads.items())
    )
    assert sorted(item.seq for item in items) == list(range(1, 41))
    again = ArchiveSpool(tmp_path / "spool")
    assert again.pending == 40
    for item in items:
        assert again.read(item) == payloads[item.key]


def test_a_submit_syncs_the_spool_directory_after_each_rename(tmp_path, monkeypatch):
    directories_synced = []
    real_fsync = os.fsync

    def fsync(descriptor: int) -> None:
        directories_synced.append(stat.S_ISDIR(os.fstat(descriptor).st_mode))
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    ArchiveSpool(tmp_path / "spool").submit(TENANT, _key(1), b"ciphertext")
    assert directories_synced == [False, True, False, True]


def test_reading_the_queue_never_waits_for_a_submit_on_disk(tmp_path, monkeypatch):
    spool = ArchiveSpool(tmp_path / "spool")
    spool.submit(TENANT, _key(1), b"first")
    writing, release = threading.Event(), threading.Event()
    real_fsync = os.fsync

    def slow_fsync(descriptor: int) -> None:
        writing.set()
        release.wait(5)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", slow_fsync)
    submit = threading.Thread(target=spool.submit, args=(TENANT, _key(2), b"second"))
    submit.start()
    try:
        assert writing.wait(5)
        started = time.monotonic()
        assert (spool.oldest().seq, spool.pending, spool.used_bytes) == (1, 1, 5)
        assert spool.has_room(1)
        assert time.monotonic() - started < 1  # the event loop calls these directly
    finally:
        release.set()
        submit.join(5)
    assert spool.pending == 2


def test_a_disk_that_cannot_take_the_object_reports_the_spool_full(tmp_path, monkeypatch):
    directory = tmp_path / "spool"
    spool = ArchiveSpool(directory)
    real_fsync = os.fsync

    def disk_full(descriptor: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "fsync", disk_full)
    with pytest.raises(SpoolFullError):
        spool.submit(TENANT, _key(1), b"ciphertext")
    assert (spool.pending, spool.used_bytes, list(directory.iterdir())) == (0, 0, [])
    monkeypatch.setattr(os, "fsync", real_fsync)
    assert spool.submit(TENANT, _key(1), b"ciphertext").seq == 1


def test_an_item_whose_metadata_is_already_gone_still_leaves(tmp_path):
    directory = tmp_path / "spool"
    spool = ArchiveSpool(directory)
    item = spool.submit(TENANT, _key(1), b"ciphertext")
    (directory / f"{1:020d}.json").unlink()  # a removal interrupted between its two files
    spool.remove(item)
    assert (spool.pending, spool.used_bytes, list(directory.iterdir())) == (0, 0, [])


def test_only_the_oldest_item_leaves(tmp_path):
    spool = ArchiveSpool(tmp_path / "spool")
    spool.submit(TENANT, _key(1), b"a")
    second = spool.submit(TENANT, _key(2), b"b")
    with pytest.raises(ValueError):
        spool.remove(second)


async def test_an_outage_delays_uploads_without_reordering_or_dropping(tmp_path, store):
    spool = ArchiveSpool(tmp_path / "spool")
    for number in (1, 2, 3):
        spool.submit(TENANT, _key(number), f"ciphertext-{number}".encode())
    writer, recorder = Outage(store), Recorder()
    uploader = ArchiveUploader(spool, writer, recorder)

    assert await uploader.flush() is False
    assert (writer.puts, spool.pending, recorder.stored) == (1, 3, [])

    writer.down = False
    assert await uploader.flush() is True
    assert [seq for seq, _ in recorder.stored] == [1, 2, 3]
    assert spool.pending == 0
    for number, (_, stored) in zip((1, 2, 3), recorder.stored):
        assert await store.get(TENANT, _key(number), stored.version_id) == (
            f"ciphertext-{number}".encode()
        )


async def test_a_lost_answer_is_recovered_from_the_stored_version(tmp_path, store):
    spool = ArchiveSpool(tmp_path / "spool")
    spool.submit(TENANT, _key(1), b"ciphertext")
    recorder = Recorder()
    recorder.fail_next = True
    uploader = ArchiveUploader(spool, store, recorder)

    assert await uploader.flush() is False  # stored, but not yet recorded
    assert spool.pending == 1
    assert await uploader.flush() is True  # the put finds the key; head returns its version
    first = await store.head(TENANT, _key(1))
    assert recorder.stored == [(1, first)]


async def test_a_key_holding_other_bytes_stops_the_spool(tmp_path, store, capsys):
    await store.put(TENANT, _key(1), b"something else")
    spool = ArchiveSpool(tmp_path / "spool")
    spool.submit(TENANT, _key(1), b"ciphertext")
    recorder = Recorder()
    assert await ArchiveUploader(spool, store, recorder).flush() is False
    assert (spool.pending, recorder.stored) == (1, [])
    logged = capsys.readouterr().err
    assert f"seq 1 tenant {tenant_ref(TENANT)} key_holds_other_bytes" in logged
    assert TENANT not in logged and "0d6c2b1a" not in logged  # no tenant ID, no conversation


async def test_a_spool_file_lost_from_disk_defers_the_upload(tmp_path, store):
    directory = tmp_path / "spool"
    spool = ArchiveSpool(directory)
    spool.submit(TENANT, _key(1), b"ciphertext")
    (directory / f"{1:020d}.bin").unlink()
    recorder = Recorder()
    assert await ArchiveUploader(spool, store, recorder).flush() is False
    assert (spool.pending, recorder.stored) == (1, [])


async def test_bytes_that_no_longer_match_their_hash_are_not_uploaded(tmp_path, store):
    directory = tmp_path / "spool"
    spool = ArchiveSpool(directory)
    spool.submit(TENANT, _key(1), b"ciphertext")
    (directory / f"{1:020d}.bin").write_bytes(b"ciphertexT")
    assert await ArchiveUploader(spool, store, Recorder()).flush() is False
    with pytest.raises(ArchiveNotFoundError):
        await store.head(TENANT, _key(1))


async def test_an_item_left_in_the_spool_is_reported_again_on_the_next_pass(
    tmp_path, store, monkeypatch
):
    spool = ArchiveSpool(tmp_path / "spool")
    spool.submit(TENANT, _key(1), b"ciphertext")
    recorder = Recorder()
    uploader = ArchiveUploader(spool, store, recorder)
    remove = spool.remove

    def read_only(item) -> None:
        raise PermissionError("read-only file system")

    monkeypatch.setattr(spool, "remove", read_only)
    assert await uploader.flush() is False
    monkeypatch.setattr(spool, "remove", remove)
    assert await uploader.flush() is True
    assert [seq for seq, _ in recorder.stored] == [1, 1]
    assert recorder.stored[0][1] == recorder.stored[1][1]


async def test_the_uploader_runs_when_notified_and_backs_off_while_failing(tmp_path, store):
    spool = ArchiveSpool(tmp_path / "spool")
    writer, recorder = Outage(store), Recorder()
    uploader = ArchiveUploader(
        spool, writer, recorder, retry_initial_seconds=0.01, retry_ceiling_seconds=0.02
    )
    task = asyncio.create_task(uploader.run())
    try:
        spool.submit(TENANT, _key(1), b"ciphertext")
        uploader.notify()
        await asyncio.sleep(0.1)
        assert writer.puts >= 2 and recorder.stored == []
        writer.down = False
        for _ in range(50):
            if recorder.stored:
                break
            await asyncio.sleep(0.01)
        assert [seq for seq, _ in recorder.stored] == [1]
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_a_notify_from_another_thread_wakes_the_idle_uploader(tmp_path, store):
    spool = ArchiveSpool(tmp_path / "spool")
    stored = asyncio.Event()

    async def on_stored(item, version) -> None:
        stored.set()

    uploader = ArchiveUploader(spool, store, on_stored)
    task = asyncio.create_task(uploader.run())
    try:
        await asyncio.sleep(0.05)  # idle, waiting to be notified

        def submit_and_notify() -> None:
            spool.submit(TENANT, _key(1), b"ciphertext")
            uploader.notify()

        threading.Thread(target=submit_and_notify).start()
        # No polling here: only a wake-up that reaches the loop gets the upload done in time.
        await asyncio.wait_for(stored.wait(), timeout=1)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def test_refusals_are_archive_errors_with_codes():
    assert ArchiveRefusedError("key_holds_other_bytes").code == "key_holds_other_bytes"
