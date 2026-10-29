"""PostgresArchiveAccess's own logic over a scripted connection: rows to records, refusals.

What the SQL selects is proven against a real PostgreSQL in
tests/integration/test_recording_archive_access_database.py; this covers how
the repository reads the answers.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
import pytest

from services.api_gateway.recording.archive_access_repository import (
    ArchiveAccessRefusedError,
    PostgresArchiveAccess,
)
from services.api_gateway.recording.chain import GENESIS, ChainObject, seal_entry
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from tests import recording_crypto_reference as ref

TENANT = "tenant-a"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
CONVERSATION = str(uuid.uuid4())
KEY_1, KEY_2 = str(uuid.uuid4()), str(uuid.uuid4())
ENTRY = str(uuid.uuid4())


class ScriptedConnection:
    """Answers each query by the first scripted fragment it contains; records every call."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def _answer(self, query: str) -> object:
        self.calls.append(query)
        for fragment, answer in self.answers.items():
            if fragment in query:
                if isinstance(answer, BaseException):
                    raise answer
                return answer
        return None

    async def execute(self, query, *args):
        return self._answer(query)

    async def fetchrow(self, query, *args):
        return self._answer(query)

    async def fetch(self, query, *args):
        return self._answer(query) or []

    async def fetchval(self, query, *args):
        return self._answer(query)

    @asynccontextmanager
    async def transaction(self):
        yield


class ScriptedPool:
    def __init__(self, connection: ScriptedConnection | None) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self, timeout=None):
        if self.connection is None:
            raise OSError("database down")
        yield self.connection


def access(answers: dict[str, object]) -> tuple[PostgresArchiveAccess, ScriptedConnection]:
    connection = ScriptedConnection(answers)
    return PostgresArchiveAccess(ScriptedPool(connection)), connection


def audited(connection: ScriptedConnection) -> int:
    return sum("INSERT INTO audit_events" in call for call in connection.calls)


def _conversation_row() -> dict:
    return {
        "conversation_id": uuid.UUID(CONVERSATION),
        "employee_sub": "alice",
        "legal_basis": "consent",
        "started_at": NOW,
        "ended_at": NOW,
        "retention_until": NOW,
        "legal_hold": False,
        "incomplete": True,
    }


def _entry(seq=1, entry_id=ENTRY, kind="consent") -> dict:
    sealed = seal_entry(
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        seq=seq,
        entry_id=entry_id,
        kind=kind,
        window_id=None,
        key_id=KEY_1,
        objects=(
            ChainObject("consent.json", f"{CONVERSATION}/{entry_id}/consent.json", 9, "aa" * 32),
        ),
        prev_hash=GENESIS,
        created_at=NOW,
        signing_key=ref.private_key(7),
        signer_key_id="gk-1",
    )
    return {
        "tenant_id": TENANT,
        "conversation_id": uuid.UUID(CONVERSATION),
        "seq": sealed.seq,
        "entry_id": uuid.UUID(sealed.entry_id),
        "kind": sealed.kind,
        "window_id": None,
        "key_id": uuid.UUID(KEY_1),
        "objects": sealed.objects,
        "prev_hash": sealed.prev_hash,
        "hash": sealed.hash,
        "signer_key_id": sealed.signer_key_id,
        "signature": sealed.signature,
        "created_at": NOW,
    }


def _wrap(key_id, epoch, kind, ref_="rk-1") -> dict:
    return {
        "key_id": uuid.UUID(key_id),
        "epoch": epoch,
        "recipient_kind": kind,
        "recipient_ref": ref_,
        "blob": "{}",
        "creator_ref": "gk-1",
        "creator_signature": bytes(64),
    }


async def test_the_list_reads_counts_and_clear_metadata():
    row = _conversation_row() | {"messages": 3, "amendments": 1}
    repository, _ = access({"FROM conversations c WHERE": [row]})
    [own] = await repository.own_conversations(
        TENANT, "alice", NOW, limit=50, started_before=None, before_id=None
    )
    assert (own.conversation_id, own.messages, own.amendments, own.incomplete) == (
        CONVERSATION,
        3,
        1,
        True,
    )
    assert own.public("alice")["verification"] == "not_verified"
    assert (own.employee_sub, own.public("alice")["recovered"]) == ("alice", False)


async def test_a_refused_open_reads_nothing_and_is_audited_as_not_found():
    repository, connection = access({})
    assert await repository.open(TENANT, "bob", CONVERSATION, NOW) is None
    assert audited(connection) == 1
    assert not any("FROM chain_entries" in call for call in connection.calls)


async def test_an_open_groups_stored_types_and_merges_wraps_by_key():
    window = {
        "window_id": uuid.uuid4(),
        "opened_at": NOW,
        "closed_at": None,
        "close_reason": None,
        "pauses": '[{"at": "x", "reason": "liveness", "resumed_at": null}]',
    }
    stored = [
        {"entry_id": uuid.UUID(ENTRY), "object_type": "consent.json"},
        {"entry_id": uuid.UUID(ENTRY), "object_type": "record.json"},
    ]
    stamps = [
        {"head_seq": 1, "head_hash": b"\x01" * 32, "tsa_token": None},
        {"head_seq": 2, "head_hash": b"\x02" * 32, "tsa_token": b"\x30\x00"},
    ]
    wraps = [
        _wrap(KEY_2, 2, "recovery"),
        _wrap(KEY_1, 1, "recovery"),
        _wrap(KEY_1, 1, "user", "alice"),
    ]
    repository, connection = access(
        {
            "SELECT c.* FROM conversations c": _conversation_row(),
            "FROM recording_windows": [window],
            "SELECT * FROM chain_entries": [_entry()],
            "FROM stored_objects o JOIN chain_entries": stored,
            "FROM chain_stamps": stamps,
            "FROM conversation_keys k JOIN key_wraps": wraps,
        }
    )
    opened = await repository.open(TENANT, "alice", CONVERSATION, NOW)

    assert opened.windows[0].pauses[0]["reason"] == "liveness"
    assert opened.stored == {ENTRY: frozenset({"consent.json", "record.json"})}
    assert [stamp.token for stamp in opened.stamps] == [None, b"\x30\x00"]
    assert [(key.key_id, key.epoch) for key in opened.keys] == [(KEY_1, 1), (KEY_2, 2)]
    assert opened.keys[0].wrap.recipient_ref == "alice"
    assert opened.keys[0].recovery_wrapped
    assert opened.keys[1].wrap is None
    assert opened.entries[0].entry_id == ENTRY
    assert audited(connection) == 1


async def test_openable_says_whether_the_rule_holds():
    allowed, connection = access({"SELECT c.* FROM conversations c": _conversation_row()})
    refused, _ = access({})
    assert await allowed.openable(TENANT, "alice", CONVERSATION, NOW)
    assert not await refused.openable(TENANT, "bob", CONVERSATION, NOW)
    assert audited(connection) == 0


async def test_an_object_is_located_by_its_listed_type():
    objects = f'[{{"key": "{CONVERSATION}/{ENTRY}/record.json", "type": "record.json"}}]'
    repository, _ = access({"SELECT e.objects": {"objects": objects, "version_id": "v1"}})
    located = await repository.object_location(
        TENANT, "alice", CONVERSATION, ENTRY, "record.json", NOW
    )
    assert (located.key, located.version_id) == (f"{CONVERSATION}/{ENTRY}/record.json", "v1")
    unlisted = await repository.object_location(
        TENANT, "alice", CONVERSATION, ENTRY, "original.wav", NOW
    )
    assert unlisted is None
    nothing, _ = access({})
    assert (
        await nothing.object_location(TENANT, "alice", CONVERSATION, ENTRY, "record.json", NOW)
        is None
    )


async def test_an_existing_amendment_reports_whether_it_is_stored():
    repository, _ = access(
        {"SELECT e.* FROM chain_entries e": _entry(kind="amendment"), "stored_objects": True}
    )
    found = await repository.existing_amendment(TENANT, "alice", CONVERSATION, ENTRY, NOW)
    assert found.entry.entry_id == ENTRY
    assert found.stored
    nothing, _ = access({})
    assert await nothing.existing_amendment(TENANT, "alice", CONVERSATION, ENTRY, NOW) is None


def _sealer(seen: list):
    def seal(seq, prev_hash):
        seen.append((seq, prev_hash))
        return seal_entry(
            tenant_id=TENANT,
            conversation_id=CONVERSATION,
            seq=seq,
            entry_id=ENTRY,
            kind="amendment",
            window_id=None,
            key_id=KEY_1,
            objects=(
                ChainObject(
                    "amendment.json", f"{CONVERSATION}/{ENTRY}/amendment.json", 9, "bb" * 32
                ),
            ),
            prev_hash=prev_hash,
            created_at=NOW,
            signing_key=ref.private_key(7),
            signer_key_id="gk-1",
        )

    return seal


async def _append(answers: dict[str, object]):
    repository, connection = access(answers)
    seen: list = []
    entry = await repository.append_amendment(
        TENANT, "alice", CONVERSATION, KEY_1, NOW, _sealer(seen), NOW
    )
    return entry, seen, connection


async def test_an_amendment_follows_the_head_and_is_stamped_and_audited():
    locked = {"FOR UPDATE": _conversation_row(), "count(DISTINCT": True}
    head = {"seq": 4, "hash": b"\x04" * 32}
    entry, seen, connection = await _append(locked | {"ORDER BY seq DESC LIMIT 1": head})
    assert seen == [(5, b"\x04" * 32)]
    assert entry.seq == 5
    assert any("INSERT INTO chain_stamps" in call for call in connection.calls)
    assert audited(connection) == 1

    _, first, _ = await _append(locked)
    assert first == [(1, bytes(32))]


@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ({}, "no_conversation"),
        ({"FOR UPDATE": {"x": 1}, "count(DISTINCT": False}, "key_not_usable"),
        (
            {
                "FOR UPDATE": {"x": 1},
                "count(DISTINCT": True,
                "INSERT INTO chain_entries": asyncpg.UniqueViolationError("duplicate"),
            },
            "entry_exists",
        ),
    ],
)
async def test_an_amendment_is_refused_with_its_reason(answers, code):
    with pytest.raises(ArchiveAccessRefusedError) as refused:
        await _append(answers)
    assert refused.value.code == code


async def test_bookkeeping_writes_and_audits():
    repository, connection = access({})
    await repository.mark_incomplete(TENANT, CONVERSATION)
    await repository.record_not_found(TENANT, "bob", CONVERSATION, NOW)
    await repository.record_integrity_failure(TENANT, "alice", CONVERSATION, "chain", NOW)
    assert any("SET incomplete = TRUE" in call for call in connection.calls)
    assert audited(connection) == 2


async def test_a_database_that_cannot_answer_is_storage_unavailable():
    repository = PostgresArchiveAccess(ScriptedPool(None))
    with pytest.raises(RecordingStorageUnavailable):
        await repository.openable(TENANT, "alice", CONVERSATION, NOW)
