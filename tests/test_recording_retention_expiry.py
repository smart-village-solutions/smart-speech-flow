"""Expiry over a real filesystem archive: shred, clear a site, delete rows, sweep orphans."""

from __future__ import annotations

from datetime import timedelta

import pytest

from services.api_gateway.recording.retention.expiry import Expirer, ExpiryReport
from services.api_gateway.recording.storage.archive import (
    ArchiveNotFoundError,
    ArchiveRefusedError,
    VersionEntry,
    object_key,
)
from services.api_gateway.recording.storage.filesystem import FilesystemArchiveStore
from tests.recording_retention_fakes import (
    CONVERSATION,
    ENTRY,
    NOW,
    TENANT,
    Failing,
    FakeRetentionStore,
)

OTHER = "2f8e4d3c-1a0b-4f9e-b8c7-6b5a4f3e2d1c"


class Clock:
    def __init__(self) -> None:
        self.now = NOW - timedelta(days=40)

    def __call__(self):
        return self.now


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    archive = FilesystemArchiveStore(tmp_path, timedelta(days=31), clock=clock)
    return archive, clock, FakeRetentionStore()


async def _put(archive, conversation=CONVERSATION, object_type="record.json"):
    stored = await archive.put(TENANT, object_key(conversation, ENTRY, object_type), b"c")
    return stored.version_id


async def test_only_the_shreds_that_happened_are_counted(world):
    _, _, store = world
    store.conversation("a", due=True)
    store.conversation("b", due=True)
    store.hold_arrives = {"b"}
    report = ExpiryReport()
    await Expirer(store, None).shred_due(TENANT, NOW, report)
    assert report.shredded == 1
    assert store.shred_actors == ["retention-worker"]


async def test_an_empty_prefix_is_cleared(world):
    archive, clock, store = world
    store.conversation(CONVERSATION, shredded=True)
    await _put(archive, OTHER)
    report = ExpiryReport()
    await Expirer(store, archive).clear(TENANT, NOW, report)
    assert store.cleared == {CONVERSATION}
    assert report.cleared == 1


async def test_an_untracked_lapsed_version_is_deleted_then_the_site_cleared(world):
    archive, clock, store = world
    store.conversation(CONVERSATION, shredded=True)
    await _put(archive)
    clock.now = NOW
    report = ExpiryReport()
    await Expirer(store, archive).clear(TENANT, NOW, report)
    assert await archive.list_versions(TENANT, "") == []
    assert (report.versions_deleted, report.cleared) == (1, 1)


async def test_an_untracked_version_still_locked_waits_without_failing(world):
    archive, clock, store = world
    store.conversation(CONVERSATION, shredded=True)
    clock.now = NOW - timedelta(days=1)
    await _put(archive)
    clock.now = NOW
    report = ExpiryReport()
    await Expirer(store, archive).clear(TENANT, NOW, report)
    assert len(await archive.list_versions(TENANT, "")) == 1
    assert store.cleared == set()
    assert report == ExpiryReport()


async def test_a_held_untracked_version_is_reported_and_never_touched(world):
    archive, clock, store = world
    store.conversation(CONVERSATION, shredded=True)
    version = await _put(archive)
    await archive.set_legal_hold(
        TENANT, object_key(CONVERSATION, ENTRY, "record.json"), version, True
    )
    clock.now = NOW
    report = ExpiryReport()
    await Expirer(store, archive).clear(TENANT, NOW, report)
    assert len(await archive.list_versions(TENANT, "")) == 1
    assert store.cleared == set()
    assert report.held_orphans == 1


class WithMarker:
    """The filesystem store with one delete marker listed under the conversation."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.deleted: list[str] = []
        self.marker = VersionEntry(object_key(CONVERSATION, ENTRY, "record.json"), "m1", True)

    async def list_versions(self, tenant_id, prefix):
        listed = await self._inner.list_versions(tenant_id, prefix)
        if self.marker.version_id not in self.deleted and self.marker.key.startswith(prefix):
            listed.append(self.marker)
        return listed

    async def retention(self, *args):
        raise AssertionError("a delete marker has no lock to read")

    async def delete_version(self, tenant_id, key, version_id):
        self.deleted.append(version_id)


async def test_a_delete_marker_goes_at_once(world):
    archive, _, store = world
    store.conversation(CONVERSATION, shredded=True)
    marked = WithMarker(archive)
    report = ExpiryReport()
    await Expirer(store, marked).clear(TENANT, NOW, report)
    assert marked.deleted == ["m1"]
    assert store.cleared == {CONVERSATION}


async def test_a_refused_delete_leaves_the_site_uncleared(world):
    archive, clock, store = world
    store.conversation(CONVERSATION, shredded=True)
    await _put(archive)
    clock.now = NOW
    refusing = Failing(archive, "delete_version", ArchiveRefusedError("AccessDenied"))
    report = ExpiryReport()
    await Expirer(store, refusing).clear(TENANT, NOW, report)
    assert store.cleared == set()
    assert (report.versions_deleted, report.refused) == (0, 1)


async def test_rows_go_for_conversations_both_sites_cleared(world):
    _, _, store = world
    for conversation in ("a", "b"):
        store.conversation(conversation, shredded=True)
    store.cleared, store.cleared_elsewhere = {"a", "b"}, {"a"}
    report = ExpiryReport()
    await Expirer(store, None).delete_rows(TENANT, NOW, report)
    assert store.rows_deleted == ["a"]
    assert report.rows_deleted == 1


async def test_the_sweep_deletes_lapsed_orphans_only(world):
    archive, clock, store = world
    store.conversation(CONVERSATION)
    known = await _put(archive)
    lapsed = await _put(archive, OTHER)
    clock.now = NOW - timedelta(days=1)
    locked = await _put(archive, "3a9f5e4d-2b1c-4a0f-89d8-7c6b5a4f3e2d")
    clock.now = NOW
    report = ExpiryReport()

    await Expirer(store, archive).sweep(TENANT, NOW, report)

    remaining = {entry.version_id for entry in await archive.list_versions(TENANT, "")}
    assert remaining == {known, locked}
    assert lapsed not in remaining
    assert report.versions_deleted == 1
    # Listed before the rows were read: see Expirer.sweep.
    assert store.steps == ["known_conversations"]


async def test_a_tenant_without_a_bucket_has_nothing_to_clear_or_sweep(world):
    archive, _, store = world
    store.conversation(CONVERSATION, shredded=True)
    missing = Failing(archive, "list_versions", ArchiveNotFoundError("NoSuchBucket"))
    report = ExpiryReport()
    await Expirer(store, missing).clear(TENANT, NOW, report)
    await Expirer(store, missing).sweep(TENANT, NOW, report)
    assert store.cleared == {CONVERSATION}

    other = Failing(archive, "list_versions", ArchiveNotFoundError("NoSuchKey"))
    with pytest.raises(ArchiveNotFoundError):
        await Expirer(store, other).sweep(TENANT, NOW, ExpiryReport())
