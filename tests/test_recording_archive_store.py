"""Archive names, and the filesystem store's S3 semantics (spec §12.1-§12.2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.storage.archive import (
    ArchiveKeyExistsError,
    ArchiveNotFoundError,
    ArchiveRefusedError,
    bucket_for,
    object_key,
)
from services.api_gateway.recording.storage.filesystem import FilesystemArchiveStore
from services.api_gateway.session_pseudonym import tenant_ref

CONVERSATION = "0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a"
ENTRY = "1e7d3c2b-0f9e-4e8d-a7b6-5a4f3e2d1c0b"
TENANT = "tenant-kassel"
START = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def test_a_bucket_is_named_by_the_tenant_reference():
    assert bucket_for(TENANT) == f"ssf-rec-{tenant_ref(TENANT)}"
    assert TENANT not in bucket_for(TENANT)


def test_an_object_key_is_conversation_entry_and_type():
    assert object_key(CONVERSATION, ENTRY, "original.wav") == f"{CONVERSATION}/{ENTRY}/original.wav"


@pytest.mark.parametrize(
    ("conversation", "entry", "object_type"),
    [
        ("../escape", ENTRY, "record.json"),
        (CONVERSATION.upper(), ENTRY, "record.json"),
        (CONVERSATION, "Frau Müller", "record.json"),
        (CONVERSATION, ENTRY, "notes.txt"),
    ],
)
def test_an_object_key_admits_only_ids_and_known_types(conversation, entry, object_type):
    with pytest.raises(ValueError):
        object_key(conversation, entry, object_type)


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    return FilesystemArchiveStore(tmp_path, timedelta(days=3), clock=clock), clock


KEY = object_key(CONVERSATION, ENTRY, "record.json")


async def test_a_key_is_written_once_and_read_by_version(world):
    store, _ = world
    stored = await store.put(TENANT, KEY, b"ciphertext")
    with pytest.raises(ArchiveKeyExistsError):
        await store.put(TENANT, KEY, b"other")
    assert await store.head(TENANT, KEY) == stored
    assert await store.get(TENANT, KEY, stored.version_id) == b"ciphertext"
    with pytest.raises(ArchiveNotFoundError):
        await store.get(TENANT, KEY, "0" * 32)


async def test_every_version_is_locked_for_the_default_and_only_extended(world):
    store, _ = world
    stored = await store.put(TENANT, KEY, b"ciphertext")
    state = await store.retention(TENANT, KEY, stored.version_id)
    assert (state.mode, state.retain_until) == ("COMPLIANCE", START + timedelta(days=3))
    await store.extend_retention(TENANT, KEY, stored.version_id, START + timedelta(days=9))
    with pytest.raises(ArchiveRefusedError):
        await store.extend_retention(TENANT, KEY, stored.version_id, START + timedelta(days=4))
    assert (await store.retention(TENANT, KEY, stored.version_id)).retain_until == (
        START + timedelta(days=9)
    )


async def test_a_version_is_deleted_only_after_its_lock_and_without_a_hold(world):
    store, clock = world
    stored = await store.put(TENANT, KEY, b"ciphertext")
    with pytest.raises(ArchiveRefusedError):
        await store.delete_version(TENANT, KEY, stored.version_id)
    clock.now = START + timedelta(days=4)
    await store.set_legal_hold(TENANT, KEY, stored.version_id, True)
    with pytest.raises(ArchiveRefusedError):
        await store.delete_version(TENANT, KEY, stored.version_id)
    await store.set_legal_hold(TENANT, KEY, stored.version_id, False)
    await store.delete_version(TENANT, KEY, stored.version_id)
    with pytest.raises(ArchiveNotFoundError):
        await store.get(TENANT, KEY, stored.version_id)
    with pytest.raises(ArchiveNotFoundError):
        await store.head(TENANT, KEY)
    again = await store.put(TENANT, KEY, b"new ciphertext")  # as S3: no current version is left
    assert await store.head(TENANT, KEY) == again


async def test_tenants_have_separate_buckets(world):
    store, _ = world
    stored = await store.put(TENANT, KEY, b"kassel")
    other = await store.put("tenant-other", KEY, b"other")
    assert await store.get(TENANT, KEY, stored.version_id) == b"kassel"
    with pytest.raises(ArchiveNotFoundError):
        await store.get("tenant-other", KEY, stored.version_id)
    assert other.version_id != stored.version_id


async def test_versions_are_listed_by_prefix_until_deleted(world):
    store, clock = world
    other = "2f8e4d3c-1a0b-4f9e-b8c7-6b5a4f3e2d1c"
    first = await store.put(TENANT, KEY, b"a")
    second = await store.put(TENANT, object_key(CONVERSATION, ENTRY, "original.wav"), b"b")
    third = await store.put(TENANT, object_key(other, ENTRY, "record.json"), b"c")

    listed = await store.list_versions(TENANT, f"{CONVERSATION}/")
    everything = await store.list_versions(TENANT, "")

    assert {(entry.key, entry.version_id) for entry in listed} == {
        (KEY, first.version_id),
        (object_key(CONVERSATION, ENTRY, "original.wav"), second.version_id),
    }
    assert {entry.version_id for entry in everything} == {
        first.version_id,
        second.version_id,
        third.version_id,
    }
    assert not any(entry.is_marker for entry in everything)
    clock.now = START + timedelta(days=4)
    await store.delete_version(TENANT, KEY, first.version_id)
    assert first.version_id not in {e.version_id for e in await store.list_versions(TENANT, "")}
    assert await store.list_versions("tenant-without-bucket", "") == []
