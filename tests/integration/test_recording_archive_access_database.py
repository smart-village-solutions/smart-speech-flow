"""The employee's archive against a real PostgreSQL (spec §10.6; migration 005).

Same environment as test_recording_archive_database.py.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest

from services.api_gateway.recording.archive_access_repository import (
    ArchiveAccessRefusedError,
    PostgresArchiveAccess,
)
from services.api_gateway.recording.chain import ChainObject, seal_entry
from tests.integration.test_recording_archive_database import (  # noqa: F401 - fixtures
    GATEWAY,
    GATEWAY_ID,
    NOW,
    TENANT,
    _entry,
    _new_key,
    _opened,
    archive,
    owner,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def access(archive):
    return PostgresArchiveAccess(archive._pool)


async def _ended(archive, owner, *, employee="alice", wrapped=True, at=NOW):
    """An ended conversation of `employee`, wrapped for them unless `wrapped` is False.

    `_opened` wraps for recovery only; the user wrap's blob is never opened here.
    """
    conversation, key_id, _, consent = await _opened(archive)
    await owner.execute(
        "UPDATE conversations SET employee_sub = $1, ended_at = $2 WHERE conversation_id = $3",
        employee,
        at,
        uuid.UUID(conversation.conversation_id),
    )
    if wrapped:
        await owner.execute(
            "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
            " creator_ref, creator_signature, granted_at)"
            " VALUES ($1, $2, 'user', $3, '{}', $4, $5, $6)",
            TENANT,
            uuid.UUID(key_id),
            employee,
            GATEWAY_ID,
            bytes(64),
            NOW,
        )
    return conversation, key_id, consent


async def _audit(owner) -> list[tuple[str, str, str]]:
    rows = await owner.fetch(
        "SELECT actor_sub, event_type, object_ref FROM audit_events ORDER BY seq"
    )
    return [(r["actor_sub"], r["event_type"], r["object_ref"]) for r in rows]


def _sealer(conversation, key_id, entry_id):
    def seal(seq, prev_hash):
        return seal_entry(
            tenant_id=TENANT,
            conversation_id=conversation.conversation_id,
            seq=seq,
            entry_id=entry_id,
            kind="amendment",
            window_id=None,
            key_id=key_id,
            objects=(
                ChainObject(
                    "amendment.json",
                    f"{conversation.conversation_id}/{entry_id}/amendment.json",
                    64,
                    "bb" * 32,
                ),
            ),
            prev_hash=prev_hash,
            created_at=NOW,
            signing_key=GATEWAY,
            signer_key_id=GATEWAY_ID,
        )

    return seal


async def test_the_list_is_served_by_its_indexes(owner):
    names = {
        row["indexname"]
        for row in await owner.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename IN ('key_wraps', 'conversations')"
        )
    }
    assert {"key_wraps_user_recipient", "conversations_employee_started"} <= names


async def test_the_list_holds_only_the_callers_ended_wrapped_conversations(archive, owner, access):
    mine, _, _ = await _ended(archive, owner)
    await _ended(archive, owner, employee="bob")
    await _ended(archive, owner, wrapped=False)
    await _ended(archive, owner, at=None)  # live, though wrapped for the caller

    rows = await access.own_conversations(
        TENANT, "alice", NOW, limit=50, started_before=None, before_id=None
    )

    assert [row.conversation_id for row in rows] == [mine.conversation_id]
    assert rows[0].messages == 0
    assert rows[0].amendments == 0


async def test_past_its_date_a_conversation_is_gone_unless_held(archive, owner, access):
    conversation, _, _ = await _ended(archive, owner)
    later = conversation.retention_until + timedelta(seconds=1)
    assert await access.open(TENANT, "alice", conversation.conversation_id, later) is None
    await owner.execute("UPDATE conversations SET legal_hold = TRUE")
    assert await access.open(TENANT, "alice", conversation.conversation_id, later) is not None


async def test_an_open_is_audited_with_the_read_and_a_refusal_as_not_found(archive, owner, access):
    conversation, key_id, consent = await _ended(archive, owner)

    opened = await access.open(TENANT, "alice", conversation.conversation_id, NOW)
    refused = await access.open(TENANT, "bob", conversation.conversation_id, NOW)

    assert refused is None
    assert [entry.entry_id for entry in opened.entries] == [consent.entry_id]
    assert [k.key_id for k in opened.keys] == [key_id]
    assert opened.keys[0].wrap is not None
    assert opened.keys[0].recovery_wrapped
    assert await _audit(owner) == [
        ("guest", "recording.arming", opened.windows[0].window_id),
        ("alice", "recording.archive.opened", conversation.conversation_id),
        ("bob", "recording.archive.not_found", conversation.conversation_id),
    ]


async def test_openable_reads_the_rule_without_an_audit_event(archive, owner, access):
    conversation, _, _ = await _ended(archive, owner)
    before = await _audit(owner)
    assert await access.openable(TENANT, "alice", conversation.conversation_id, NOW)
    assert not await access.openable(TENANT, "bob", conversation.conversation_id, NOW)
    assert await _audit(owner) == before


async def test_an_object_is_located_only_through_a_wrap_of_its_entry(archive, owner, access):
    conversation, _, consent = await _ended(archive, owner)
    assert (
        await access.object_location(
            TENANT, "alice", conversation.conversation_id, consent.entry_id, "record.json", NOW
        )
    ).version_id is None
    await archive.record_stored(TENANT, consent.entry_id, "record.json", "v1", NOW)
    located = await access.object_location(
        TENANT, "alice", conversation.conversation_id, consent.entry_id, "record.json", NOW
    )
    assert located.version_id == "v1"
    assert located.key == f"{conversation.conversation_id}/{consent.entry_id}/record.json"
    for sub, kind in (("bob", "record.json"), ("alice", "original.wav")):
        assert (
            await access.object_location(
                TENANT, sub, conversation.conversation_id, consent.entry_id, kind, NOW
            )
            is None
        )


async def test_an_entry_under_a_key_without_the_callers_wrap_is_not_served(archive, owner, access):
    conversation, _, consent = await _ended(archive, owner)
    later_key, later_key_id = _new_key(conversation, epoch=2)
    later = _entry(conversation, 2, consent.hash, later_key_id)
    await archive.append_entry(later, later_key)
    await archive.record_stored(TENANT, later.entry_id, "record.json", "v2", NOW)

    assert (
        await access.object_location(
            TENANT, "alice", conversation.conversation_id, later.entry_id, "record.json", NOW
        )
        is None
    )
    opened = await access.open(TENANT, "alice", conversation.conversation_id, NOW)
    assert [(k.epoch, k.wrap is None) for k in opened.keys] == [(1, False), (2, True)]


async def test_an_amendment_extends_the_chain_requests_a_stamp_and_is_audited(
    archive, owner, access
):
    conversation, key_id, consent = await _ended(archive, owner)
    entry_id = str(uuid.uuid4())

    entry = await access.append_amendment(
        TENANT,
        "alice",
        conversation.conversation_id,
        key_id,
        NOW,
        _sealer(conversation, key_id, entry_id),
        NOW,
    )

    assert (entry.seq, entry.prev_hash) == (2, consent.hash)
    stamps = await owner.fetch("SELECT head_seq FROM chain_stamps ORDER BY head_seq")
    assert [row["head_seq"] for row in stamps][-1] == 2
    assert (await _audit(owner))[-1] == ("alice", "recording.amendment.added", entry_id)
    found = await access.existing_amendment(
        TENANT, "alice", conversation.conversation_id, entry_id, NOW
    )
    assert found.entry == entry
    assert not found.stored


async def test_an_amendment_waits_for_the_conversation_row(archive, owner, access):
    """The head is read under the row lock, so two amendments never take the same seq.

    The blocker holds only a share lock, as the shred trigger does during any
    chain insert: share locks do not wait for each other, the amendment's must.
    """
    conversation, key_id, _ = await _ended(archive, owner)
    blocker = owner.transaction()
    await blocker.start()
    await owner.execute(
        "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR SHARE",
        uuid.UUID(conversation.conversation_id),
    )
    appending = asyncio.create_task(
        access.append_amendment(
            TENANT,
            "alice",
            conversation.conversation_id,
            key_id,
            NOW,
            _sealer(conversation, key_id, str(uuid.uuid4())),
            NOW,
        )
    )
    await asyncio.sleep(0.5)
    waited = not appending.done()
    await blocker.rollback()
    entry = await appending

    assert waited
    assert entry.seq == 2


async def test_an_amendment_needs_the_opening_rule_and_a_key_wrapped_for_both(
    archive, owner, access
):
    conversation, key_id, _ = await _ended(archive, owner)
    seal = _sealer(conversation, key_id, str(uuid.uuid4()))
    with pytest.raises(ArchiveAccessRefusedError) as refused:
        await access.append_amendment(
            TENANT, "bob", conversation.conversation_id, key_id, NOW, seal, NOW
        )
    assert refused.value.code == "no_conversation"
    await owner.execute("DELETE FROM key_wraps WHERE recipient_kind = 'recovery'")
    with pytest.raises(ArchiveAccessRefusedError) as refused:
        await access.append_amendment(
            TENANT, "alice", conversation.conversation_id, key_id, NOW, seal, NOW
        )
    assert refused.value.code == "key_not_usable"
    assert len(await owner.fetch("SELECT 1 FROM chain_entries")) == 1


async def test_an_existing_amendment_is_found_only_by_its_caller_and_reports_its_store(
    archive, owner, access
):
    conversation, key_id, consent = await _ended(archive, owner)
    entry_id = str(uuid.uuid4())
    await access.append_amendment(
        TENANT,
        "alice",
        conversation.conversation_id,
        key_id,
        NOW,
        _sealer(conversation, key_id, entry_id),
        NOW,
    )
    conversation_id = conversation.conversation_id

    assert await access.existing_amendment(TENANT, "bob", conversation_id, entry_id, NOW) is None
    assert (
        await access.existing_amendment(TENANT, "alice", conversation_id, consent.entry_id, NOW)
        is None
    )
    await archive.record_stored(TENANT, entry_id, "amendment.json", "v-a", NOW)
    found = await access.existing_amendment(TENANT, "alice", conversation_id, entry_id, NOW)
    assert found.stored


async def test_a_shredded_conversation_is_gone_even_with_wraps_left(archive, owner, access):
    conversation, _, _ = await _ended(archive, owner)
    await owner.execute("UPDATE conversations SET shredded_at = $1", NOW)
    assert await access.open(TENANT, "alice", conversation.conversation_id, NOW) is None


async def test_an_amendment_left_unstored_marks_its_conversation(archive, owner, access):
    conversation, _, _ = await _ended(archive, owner)
    await access.mark_incomplete(TENANT, conversation.conversation_id)
    assert await owner.fetchval("SELECT incomplete FROM conversations") is True


async def test_a_reused_entry_id_is_refused(archive, owner, access):
    conversation, key_id, consent = await _ended(archive, owner)
    seal = _sealer(conversation, key_id, consent.entry_id)
    with pytest.raises(ArchiveAccessRefusedError) as refused:
        await access.append_amendment(
            TENANT, "alice", conversation.conversation_id, key_id, NOW, seal, NOW
        )
    assert refused.value.code == "entry_exists"


async def _recovered(
    owner, conversation, key_id, *, requester="sam", status="completed", approved=True
):
    """A request of `requester` covering the conversation, approved by k = 1, and their wrap."""
    from tests.integration.test_recording_recovery_requests_database import (
        file_directly,
        partial_directly,
    )

    request_id = await file_directly(
        owner, conversation.conversation_id, key_id, requester=requester
    )
    if approved:
        await partial_directly(owner, request_id, conversation.conversation_id, key_id)
    await owner.execute(
        "UPDATE recovery_requests SET status = $2, closed_at = $3 WHERE request_id = $1",
        request_id,
        status,
        None if status == "open" else NOW,
    )
    await owner.execute(
        "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
        " creator_ref, creator_signature, granted_at)"
        " VALUES ($1, $2, 'user', $3, '{}', $3, $4, $5)",
        TENANT,
        uuid.UUID(key_id),
        requester,
        bytes(64),
        NOW,
    )


async def test_a_supervisor_with_a_completed_request_opens_the_conversation(archive, owner, access):
    conversation, key_id, _ = await _ended(archive, owner)
    await _recovered(owner, conversation, key_id)

    opened = await access.open(TENANT, "sam", conversation.conversation_id, NOW, supervisor=True)

    assert opened is not None and opened.employee_sub == "alice"
    assert await access.openable(TENANT, "sam", conversation.conversation_id, NOW, supervisor=True)


async def test_without_supervise_or_a_completed_request_it_stays_closed(archive, owner, access):
    conversation, key_id, _ = await _ended(archive, owner)
    await _recovered(owner, conversation, key_id, status="cancelled")
    cid = conversation.conversation_id
    assert await access.open(TENANT, "sam", cid, NOW, supervisor=True) is None
    await owner.execute("UPDATE recovery_requests SET status = 'completed'")
    assert await access.open(TENANT, "sam", cid, NOW, supervisor=False) is None
    assert await access.open(TENANT, "sam", cid, NOW, supervisor=True) is not None


async def test_a_supervisor_cannot_amend_a_recovered_conversation(archive, owner, access):
    conversation, key_id, _ = await _ended(archive, owner)
    await _recovered(owner, conversation, key_id)
    with pytest.raises(ArchiveAccessRefusedError, match="no_conversation"):
        await access.append_amendment(
            TENANT,
            "sam",
            conversation.conversation_id,
            key_id,
            NOW,
            _sealer(conversation, key_id, str(uuid.uuid4())),
            NOW,
        )


async def test_the_list_carries_each_rows_employee(archive, owner, access):
    conversation, key_id, _ = await _ended(archive, owner)
    await _recovered(owner, conversation, key_id)
    rows = await access.own_conversations(
        TENANT, "sam", NOW, limit=50, started_before=None, before_id=None, supervisor=True
    )
    assert [(r.conversation_id, r.employee_sub) for r in rows] == [
        (conversation.conversation_id, "alice")
    ]
    assert rows[0].public("sam")["recovered"] is True


async def test_a_supervisor_fetches_objects_of_a_recovered_conversation_only(
    archive, owner, access
):
    conversation, key_id, consent = await _ended(archive, owner)
    await _recovered(owner, conversation, key_id)
    args = (TENANT, "sam", conversation.conversation_id, consent.entry_id, "record.json", NOW)
    assert await access.object_location(*args, supervisor=True) is not None
    assert await access.object_location(*args, supervisor=False) is None


async def test_another_supervisors_completed_request_opens_nothing_for_the_caller(
    archive, owner, access
):
    conversation, key_id, _ = await _ended(archive, owner)
    await _recovered(owner, conversation, key_id, requester="zoe")
    await owner.execute(
        "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
        " creator_ref, creator_signature, granted_at) VALUES ($1, $2, 'user', 'sam', '{}',"
        " 'sam', $3, $4)",
        TENANT,
        uuid.UUID(key_id),
        bytes(64),
        NOW,
    )
    cid = conversation.conversation_id
    assert await access.open(TENANT, "sam", cid, NOW, supervisor=True) is None


async def test_a_completed_request_without_k_approvals_opens_nothing(archive, owner, access):
    """`completed` is a status the requester's own call sets; the approvals are not (§9.5)."""
    conversation, key_id, _ = await _ended(archive, owner)
    await _recovered(owner, conversation, key_id, approved=False)
    cid = conversation.conversation_id
    assert await access.open(TENANT, "sam", cid, NOW, supervisor=True) is None
