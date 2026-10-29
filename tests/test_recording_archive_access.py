"""The employee's archive above the database: recent opens, objects, amendments (§10.6)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.archive_access import (
    MAX_AMENDMENT_BYTES,
    RECENT_OPEN,
    ArchiveAccess,
    ArchiveAccessError,
)
from services.api_gateway.recording.archive_access_repository import (
    ArchiveAccessRefusedError,
    ExistingAmendment,
    ObjectLocation,
    OpenedConversation,
)
from services.api_gateway.recording.archive_service import stored_recorder
from services.api_gateway.recording.chain import GENESIS
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.storage.spool import ArchiveSpool, SpoolFullError
from services.api_gateway.recording.storage.filesystem import FilesystemArchiveStore
from services.api_gateway.recording.storage.tenant_spools import TenantSpools
from tests.recording_archive_fakes import MemoryArchiveRepository, gateway_secrets

TENANT = "tenant-a"
CONVERSATION = str(uuid.uuid4())
KEY = str(uuid.uuid4())
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


class FakeAccess:
    def __init__(self) -> None:
        self.openable_pairs = {("alice", CONVERSATION)}
        self.audit: list[tuple[str, str, str]] = []
        self.entries: list = []
        self.locations: dict[tuple[str, str], ObjectLocation] = {}
        self.key_usable = True
        self.stored: set[str] = set()
        self.incomplete: list[str] = []
        self.audit_down = False

    def _ok(self, sub, conversation_id):
        return (sub, conversation_id) in self.openable_pairs

    async def open(self, tenant_id, sub, conversation_id, now):
        if not self._ok(sub, conversation_id):
            self.audit.append((sub, "not_found", conversation_id))
            return None
        self.audit.append((sub, "opened", conversation_id))
        return OpenedConversation(
            CONVERSATION,
            sub,
            "consent",
            NOW,
            NOW,
            NOW + timedelta(days=30),
            False,
            False,
            (),
            tuple(self.entries),
            {},
            (),
            (),
        )

    async def openable(self, tenant_id, sub, conversation_id, now):
        return self._ok(sub, conversation_id)

    async def object_location(self, tenant_id, sub, conversation_id, entry_id, object_type, now):
        if not self._ok(sub, conversation_id):
            return None
        return self.locations.get((entry_id, object_type))

    async def existing_amendment(self, tenant_id, sub, conversation_id, entry_id, now):
        if not self._ok(sub, conversation_id):
            return None
        for entry in self.entries:
            if entry.entry_id == entry_id:
                return ExistingAmendment(entry, entry_id in self.stored)
        return None

    async def append_amendment(self, tenant_id, sub, conversation_id, key_id, now, seal, at):
        if not self._ok(sub, conversation_id):
            raise ArchiveAccessRefusedError("no_conversation")
        if not self.key_usable:
            raise ArchiveAccessRefusedError("key_not_usable")
        previous = self.entries[-1].hash if self.entries else GENESIS
        entry = seal(len(self.entries) + 1, previous)
        self.entries.append(entry)
        self.audit.append((sub, "amendment", entry.entry_id))
        return entry

    async def record_not_found(self, tenant_id, sub, conversation_ref, at):
        self.audit.append((sub, "not_found", conversation_ref))

    async def record_integrity_failure(self, tenant_id, sub, conversation_id, stage, at):
        if self.audit_down:
            raise RecordingStorageUnavailable("down")
        self.audit.append((sub, f"integrity.{stage}", conversation_id))

    async def mark_incomplete(self, tenant_id, conversation_id):
        self.incomplete.append(conversation_id)


@pytest.fixture
def rig(tmp_path):
    clock = {"now": NOW}
    store = FilesystemArchiveStore(tmp_path / "store", timedelta(days=2))
    spools = TenantSpools(tmp_path / "spool", store, stored_recorder(MemoryArchiveRepository()))
    access = FakeAccess()
    service = ArchiveAccess(
        repository=access,
        reader=store,
        spools=spools,
        secrets=gateway_secrets(),
        clock=lambda: clock["now"],
    )
    return service, access, store, spools, clock


def _envelope(size=64) -> bytes:
    return b"\x01" + bytes(size - 1)


async def test_an_object_needs_a_recent_open_by_the_same_caller(rig):
    service, access, store, _, clock = rig
    key = f"{CONVERSATION}/{KEY}/record.json"
    stored = await store.put(TENANT, key, b"cipher")
    access.locations[(KEY, "record.json")] = ObjectLocation(key, stored.version_id)
    with pytest.raises(ArchiveAccessError) as error:
        await service.object(TENANT, "alice", CONVERSATION, KEY, "record.json")
    assert error.value.code == "not_found"

    await service.open(TENANT, "alice", CONVERSATION)
    assert await service.object(TENANT, "alice", CONVERSATION, KEY, "record.json") == b"cipher"

    clock["now"] = NOW + RECENT_OPEN + timedelta(seconds=1)
    with pytest.raises(ArchiveAccessError):
        await service.object(TENANT, "alice", CONVERSATION, KEY, "record.json")


async def test_an_unstored_object_is_its_own_answer(rig):
    service, access, _, _, _ = rig
    access.locations[(KEY, "record.json")] = ObjectLocation("k", None)
    await service.open(TENANT, "alice", CONVERSATION)
    with pytest.raises(ArchiveAccessError) as error:
        await service.object(TENANT, "alice", CONVERSATION, KEY, "record.json")
    assert error.value.code == "not_stored"


async def test_another_callers_open_does_not_count(rig):
    service, access, store, _, _ = rig
    key = f"{CONVERSATION}/{KEY}/record.json"
    stored = await store.put(TENANT, key, b"cipher")
    access.locations[(KEY, "record.json")] = ObjectLocation(key, stored.version_id)
    access.openable_pairs.add(("bob", CONVERSATION))
    await service.open(TENANT, "bob", CONVERSATION)
    with pytest.raises(ArchiveAccessError) as error:
        await service.object(TENANT, "alice", CONVERSATION, KEY, "record.json")
    assert error.value.code == "not_found"


async def test_a_refused_open_is_not_found(rig):
    service, access, _, _, _ = rig
    with pytest.raises(ArchiveAccessError) as error:
        await service.open(TENANT, "bob", CONVERSATION)
    assert error.value.code == "not_found"
    assert access.audit == [("bob", "not_found", CONVERSATION)]


async def test_an_amendment_is_signed_chained_spooled_and_never_changes_an_entry(rig):
    service, access, _, spools, _ = rig
    entry_id = str(uuid.uuid4())

    entry, created = await service.amend(TENANT, "alice", CONVERSATION, entry_id, KEY, _envelope())

    assert created
    assert (entry.kind, entry.window_id, entry.key_id, entry.seq) == ("amendment", None, KEY, 1)
    assert f"{CONVERSATION}/{entry_id}/amendment.json" in entry.objects
    assert spools.spool(TENANT).pending == 1
    before = list(access.entries)
    await service.amend(TENANT, "alice", CONVERSATION, str(uuid.uuid4()), KEY, _envelope())
    assert access.entries[:1] == before


async def test_an_amendment_refused_by_the_database_keeps_its_code(rig):
    service, access, _, spools, _ = rig
    access.key_usable = False
    entry_id = str(uuid.uuid4())
    ciphertext = _envelope()
    with pytest.raises(ArchiveAccessError) as error:
        await service.amend(TENANT, "alice", CONVERSATION, entry_id, KEY, ciphertext)
    assert error.value.code == "key_not_usable"
    entry_id = str(uuid.uuid4())
    ciphertext = _envelope()
    with pytest.raises(ArchiveAccessError) as error:
        await service.amend(TENANT, "bob", CONVERSATION, entry_id, KEY, ciphertext)
    assert error.value.code == "not_found"
    assert spools.spool(TENANT).pending == 0


@pytest.mark.parametrize(
    "ciphertext", [b"", b"\x02" + bytes(63), b"\x01" + bytes(MAX_AMENDMENT_BYTES)]
)
async def test_a_malformed_or_oversized_envelope_is_refused(rig, ciphertext):
    service, access, _, _, _ = rig
    entry_id = str(uuid.uuid4())
    with pytest.raises(ArchiveAccessError) as error:
        await service.amend(TENANT, "alice", CONVERSATION, entry_id, KEY, ciphertext)
    assert error.value.code == "bad_ciphertext"
    assert access.entries == []


async def test_a_re_post_of_the_same_bytes_answers_the_same_entry(rig):
    service, access, _, spools, _ = rig
    entry_id = str(uuid.uuid4())
    data = _envelope()
    first, _ = await service.amend(TENANT, "alice", CONVERSATION, entry_id, KEY, data)

    again, created = await service.amend(TENANT, "alice", CONVERSATION, entry_id, KEY, data)
    assert (again, created) == (first, False)
    assert spools.spool(TENANT).pending == 2  # unstored: spooled once more

    access.stored.add(entry_id)
    stored, created = await service.amend(TENANT, "alice", CONVERSATION, entry_id, KEY, data)
    assert (stored, created) == (first, False)
    assert spools.spool(TENANT).pending == 2  # stored: nothing to send
    assert len(access.entries) == 1

    for other in (_envelope(65), b"\x01" + bytes(62) + b"\x01"):
        with pytest.raises(ArchiveAccessError) as error:
            await service.amend(TENANT, "alice", CONVERSATION, entry_id, KEY, other)
        assert error.value.code == "entry_exists"


async def test_an_amendment_the_spool_refuses_after_its_commit_marks_the_conversation(
    rig, monkeypatch
):
    service, access, _, _, _ = rig

    def full(self, tenant_id, key, data):
        raise SpoolFullError()

    monkeypatch.setattr(ArchiveSpool, "submit", full)
    entry_id = str(uuid.uuid4())
    ciphertext = _envelope()
    with pytest.raises(ArchiveAccessError) as error:
        await service.amend(TENANT, "alice", CONVERSATION, entry_id, KEY, ciphertext)
    assert error.value.code == "write_failed"
    assert len(access.entries) == 1
    assert access.incomplete == [CONVERSATION]


async def test_every_refusal_is_audited_as_not_found(rig):
    service, access, _, _, _ = rig
    for attempt in (
        service.object(TENANT, "bob", CONVERSATION, KEY, "record.json"),
        service.amend(TENANT, "bob", CONVERSATION, str(uuid.uuid4()), KEY, _envelope()),
        service.report(TENANT, "bob", CONVERSATION, "chain"),
    ):
        with pytest.raises(ArchiveAccessError) as error:
            await attempt
        assert error.value.code == "not_found"
    await service.open(TENANT, "alice", CONVERSATION)
    with pytest.raises(ArchiveAccessError):
        await service.object(TENANT, "alice", CONVERSATION, KEY, "record.json")
    refusals = [event for event in access.audit if event[1] == "not_found"]
    assert refusals == [("bob", "not_found", CONVERSATION)] * 3 + [
        ("alice", "not_found", CONVERSATION)
    ]


async def test_a_report_whose_audit_failed_is_tried_again(rig):
    service, access, _, _, _ = rig
    access.audit_down = True
    with pytest.raises(ArchiveAccessError):
        await service.report(TENANT, "alice", CONVERSATION, "chain")
    access.audit_down = False
    await service.report(TENANT, "alice", CONVERSATION, "chain")
    assert access.audit == [("alice", "integrity.chain", CONVERSATION)]


async def test_integrity_reports_are_accepted_for_openable_conversations_once_a_while(rig):
    service, access, _, _, clock = rig
    await service.report(TENANT, "alice", CONVERSATION, "chain")
    await service.report(TENANT, "alice", CONVERSATION, "chain")
    clock["now"] = NOW + timedelta(minutes=11)
    await service.report(TENANT, "alice", CONVERSATION, "chain")
    with pytest.raises(ArchiveAccessError):
        await service.report(TENANT, "bob", CONVERSATION, "chain")
    integrity = [event for event in access.audit if event[1].startswith("integrity")]
    assert integrity == [
        ("alice", "integrity.chain", CONVERSATION),
        ("alice", "integrity.chain", CONVERSATION),
    ]
