"""#619's writers against the swap, the leaver marking, a shred and recovery (spec §10.7).

Each race is made deterministic: an owner transaction holds the contended row,
both writers queue on it in a chosen order, and the row is released. Both
orders run, so each branch is proven on every run.
"""

from __future__ import annotations

import asyncio
import uuid

import asyncpg
import pytest

from services.api_gateway.recording.leavers_repository import PostgresLeavers
from services.api_gateway.recording.recovery_requests_model import NewWrap, Refused
from services.api_gateway.recording.recovery_requests_repository import PostgresRecoveryRequests
from services.api_gateway.recording.repository import UserKeyRecord
from services.api_gateway.recording.verification_model import NotePost
from tests.integration.test_recording_archive_database import OWNER_DSN, OWNER_PASSWORD
from tests.integration.test_recording_leavers_database import _waiting
from tests.integration.test_recording_verification_database import (  # noqa: F401 - fixtures
    _ENVELOPE,
    NOW,
    SNAPSHOT,
    TENANT,
    _assignable,
    _assigned,
    _assignment,
    _consent,
    _decision,
    _ended,
    _key,
    _no_keys,
    _point,
    access,
    archive,
    owner,
    verifications,
)
from tests.recording_swap import swap_key

pytestmark = pytest.mark.integration


async def _race(owner, lock_sql: str, first, second):
    """Hold `lock_sql`'s row, queue `first` then `second` on it, release, return both results."""
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute(lock_sql)
        started = asyncio.create_task(first())
        await _waiting(owner, 1)
        queued = asyncio.create_task(second())
        await _waiting(owner, 2)
        await transaction.rollback()
        return await asyncio.gather(started, queued)
    finally:
        await holder.close()


async def _open_for(owner, sub: str) -> tuple[int, int]:
    records = await owner.fetchval(
        "SELECT count(*) FROM verifications WHERE reviewer_sub = $1"
        " AND status IN ('awaiting', 'in_review')",
        sub,
    )
    wraps = await owner.fetchval(
        "SELECT count(*) FROM key_wraps WHERE recipient_kind = 'user' AND recipient_ref = $1", sub
    )
    return records, wraps


@pytest.mark.parametrize("assign_first", [True, False])
async def test_an_assignment_racing_the_reviewers_leaver_marking_leaves_no_access(
    archive, owner, verifications, assign_first
):
    cid, key_id = await _assignable(archive, owner)
    leavers = PostgresLeavers(archive._pool)

    def assign():
        return verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)

    def mark():
        return leavers.mark(TENANT, "rita", 1, "admin", NOW)

    first, second = (assign, mark) if assign_first else (mark, assign)
    results = await _race(
        owner, "SELECT 1 FROM user_keys WHERE user_sub = 'rita' FOR UPDATE", first, second
    )

    assigned = results[0] if assign_first else results[1]
    assert await _open_for(owner, "rita") == (0, 0)
    if not assign_first:
        assert assigned == Refused("reviewer_key_changed")


@pytest.mark.parametrize("decide_first", [True, False])
async def test_a_decision_racing_the_reviewers_reenrolment_leaves_no_access(
    archive, owner, verifications, decide_first
):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    record = await verifications.start(
        TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW
    )
    new_key = UserKeyRecord(TENANT, "rita", 2, _point(9), _point(19), b"\x09" * 32, b"b", NOW)

    def decide():
        post = _decision(record, "approved", None, [])
        return verifications.decide(TENANT, "rita", row.verification_id, post, NOW)

    def swap():
        return swap_key(archive._pool, new_key, 1, NOW)

    first, second = (decide, swap) if decide_first else (swap, decide)
    results = await _race(
        owner, "SELECT 1 FROM user_keys WHERE user_sub = 'rita' FOR UPDATE", first, second
    )

    decided = results[0] if decide_first else results[1]
    status = await owner.fetchval("SELECT status FROM verifications")
    assert await _open_for(owner, "rita") == (0, 0)
    if decide_first:
        assert status == "approved"
    else:
        assert decided in (Refused("key_changed"), Refused("verification_closed"))
        assert status == "withdrawn"


async def test_an_assignment_waiting_on_a_shred_is_refused(archive, owner, verifications):
    """A shred takes the conversation first; the assignment re-checks the rule after it."""
    cid, key_id = await _assignable(archive, owner)
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR UPDATE", uuid.UUID(cid)
        )
        queued = asyncio.create_task(
            verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)
        )
        await _waiting(owner, 1)
        await holder.execute(
            "UPDATE conversations SET shredded_at = $2 WHERE conversation_id = $1",
            uuid.UUID(cid),
            NOW,
        )
        await holder.execute(
            "DELETE FROM key_wraps WHERE key_id IN (SELECT key_id FROM conversation_keys"
            " WHERE conversation_id = $1)",
            uuid.UUID(cid),
        )
        await transaction.commit()
        refused = await queued
    finally:
        await holder.close()
    assert refused == Refused("not_found")
    assert await owner.fetchval("SELECT count(*) FROM verifications") == 0


@pytest.mark.parametrize("assign_first", [True, False])
async def test_an_assignment_racing_a_recovery_never_merges_their_wraps(
    archive, owner, verifications, assign_first
):
    """M2: in either order the open request excludes the assignment, so the recovery's own
    wraps are the only ones. A filing that slips past an assignment is refused at
    store_wraps instead (test_storing_wraps_is_refused_while_the_requester_reviews_...)."""
    from tests.integration.test_recording_recovery_requests_database import (
        _approval,
        _filed,
        recovery_key,
    )

    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await _key(owner, "alice")
    requests = PostgresRecoveryRequests(archive._pool)
    await recovery_key(owner)
    request, scope = await _filed(requests, owner, [conversation])  # enrols sam as version 1

    await requests.approve(
        TENANT, "carol", request.request_id, _approval(scope), lambda *_: True, NOW
    )

    def assign():
        return verifications.assign(
            _assignment(cid, [key_id], reviewer="sam"), NOW, supervisor=False
        )

    def store():
        wraps = [NewWrap(k.conversation_id, k.key_id, "{}", bytes(64)) for k in scope]
        return requests.store_wraps(
            TENANT, "sam", request.request_id, wraps, 1, lambda *_: True, NOW, may_supervise=True
        )

    first, second = (assign, store) if assign_first else (store, assign)
    lock = f"SELECT 1 FROM conversations WHERE conversation_id = '{cid}' FOR UPDATE"
    results = await _race(owner, lock, first, second)

    assigned, stored = results if assign_first else results[::-1]
    creators = {
        r["creator_ref"]
        for r in await owner.fetch("SELECT creator_ref FROM key_wraps WHERE recipient_ref = 'sam'")
    }
    assert assigned == Refused("reviewer_not_eligible") and stored == ()
    assert creators == {"sam"}


@pytest.mark.parametrize("decide_first", [True, False])
async def test_a_draft_save_racing_the_decision_never_changes_what_was_signed(
    archive, owner, verifications, decide_first
):
    """M5: the notes after both commits are exactly the decision's, or the draft is refused."""
    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    record = await verifications.start(
        TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW
    )
    final = NotePost(str(head["entry_id"]), key_id, b"\x01" + bytes(60))
    draft = NotePost(str(head["entry_id"]), key_id, _ENVELOPE)

    def decide():
        post = _decision(record, "approved", None, [final])
        return verifications.decide(TENANT, "rita", row.verification_id, post, NOW)

    def save():
        return verifications.save_draft(TENANT, "rita", row.verification_id, None, [draft], NOW)

    first, second = (decide, save) if decide_first else (save, decide)
    lock = f"SELECT 1 FROM verifications WHERE verification_id = '{row.verification_id}' FOR UPDATE"
    results = await _race(owner, lock, first, second)

    saved = results[1] if decide_first else results[0]
    stored = [
        bytes(r["ciphertext"])
        for r in await owner.fetch("SELECT ciphertext FROM verification_notes")
    ]
    assert stored == [final.ciphertext]
    assert saved == (Refused("verification_closed") if decide_first else None)


async def test_an_assignment_waits_for_a_recovery_holding_the_conversation(
    archive, owner, verifications
):
    """The assignment takes the conversation FOR UPDATE, so it queues behind store_wraps' FOR SHARE."""
    cid, key_id = await _assignable(archive, owner)
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR SHARE", uuid.UUID(cid)
        )
        queued = asyncio.create_task(
            verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)
        )
        await _waiting(owner, 1)
        await transaction.rollback()
        assigned = await queued
    finally:
        await holder.close()
    assert not isinstance(assigned, Refused)


@pytest.mark.parametrize("assign_first", [True, False])
async def test_filing_racing_an_assignment_never_leaves_both_open(
    archive, owner, verifications, assign_first
):
    """Filing reads the conversation FOR SHARE, so it serialises with the assignment's FOR UPDATE."""
    from services.api_gateway.recording.recovery_requests_model import NewRequest
    from tests.integration.test_recording_recovery_requests_database import enrol, recovery_key

    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await _key(owner, "alice")
    await enrol(owner, "sam")
    requests = PostgresRecoveryRequests(archive._pool)
    # Built before the race: the owner connection only polls the lock queue during it.
    request = NewRequest(
        tenant_id=TENANT,
        request_id=str(uuid.uuid4()),
        kind="access",
        requester_sub="sam",
        requester_key_version=1,
        recovery_key_id=await recovery_key(owner),
        reason="Employee left.",
        conversation_ids=(cid,),
        signature=bytes(64),
        created_at=NOW,
    )

    def assign():
        return verifications.assign(
            _assignment(cid, [key_id], reviewer="sam"), NOW, supervisor=False
        )

    def file():
        return requests.file(request, lambda *_: True)

    first, second = (assign, file) if assign_first else (file, assign)
    lock = f"SELECT 1 FROM conversations WHERE conversation_id = '{cid}' FOR UPDATE"
    assigned, filed = await _race(owner, lock, first, second)
    if not assign_first:
        assigned, filed = filed, assigned

    open_requests = await owner.fetchval(
        "SELECT count(*) FROM recovery_requests WHERE status = 'open'"
    )
    open_reviews = await owner.fetchval(
        "SELECT count(*) FROM verifications WHERE status IN ('awaiting', 'in_review')"
    )
    if assign_first:
        assert filed == Refused("review_in_progress") and (open_requests, open_reviews) == (0, 1)
    else:
        assert assigned == Refused("reviewer_not_eligible") and (open_requests, open_reviews) == (
            1,
            0,
        )


@pytest.mark.parametrize("decline_first", [True, False])
async def test_a_decline_racing_the_reviewers_reenrolment_leaves_no_access(
    archive, owner, verifications, decline_first
):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    new_key = UserKeyRecord(TENANT, "rita", 2, _point(9), _point(19), b"\x09" * 32, b"b", NOW)

    def decline():
        return verifications.decline(TENANT, "rita", row.verification_id, NOW)

    def swap():
        return swap_key(archive._pool, new_key, 1, NOW)

    first, second = (decline, swap) if decline_first else (swap, decline)
    # Both take the conversation FOR SHARE; the record row is where they meet.
    lock = f"SELECT 1 FROM verifications WHERE verification_id = '{row.verification_id}' FOR UPDATE"
    await _race(owner, lock, first, second)

    assert await _open_for(owner, "rita") == (0, 0)
    assert await owner.fetchval("SELECT status FROM verifications") == (
        "declined" if decline_first else "withdrawn"
    )


@pytest.mark.parametrize("decide_first", [True, False])
async def test_a_decision_racing_the_reviewers_leaver_marking_leaves_no_access(
    archive, owner, verifications, decide_first
):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    record = await verifications.start(
        TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW
    )
    leavers = PostgresLeavers(archive._pool)

    def decide():
        return verifications.decide(
            TENANT, "rita", row.verification_id, _decision(record, "approved", None, []), NOW
        )

    def mark():
        return leavers.mark(TENANT, "rita", 1, "admin", NOW)

    first, second = (decide, mark) if decide_first else (mark, decide)
    await _race(owner, "SELECT 1 FROM user_keys WHERE user_sub = 'rita' FOR UPDATE", first, second)

    assert await _open_for(owner, "rita") == (0, 0)
    assert await owner.fetchval("SELECT status FROM verifications") == (
        "approved" if decide_first else "withdrawn"
    )


async def test_a_decision_waiting_on_a_shred_is_refused(archive, owner, verifications):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    record = await verifications.start(
        TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW
    )
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR UPDATE", uuid.UUID(cid)
        )
        queued = asyncio.create_task(
            verifications.decide(
                TENANT, "rita", row.verification_id, _decision(record, "approved", None, []), NOW
            )
        )
        await _waiting(owner, 1)
        await holder.execute(
            "UPDATE conversations SET shredded_at = $2 WHERE conversation_id = $1",
            uuid.UUID(cid),
            NOW,
        )
        await transaction.commit()
        refused = await queued
    finally:
        await holder.close()
    assert refused == Refused("verification_closed")
    assert await owner.fetchval("SELECT status FROM verifications") == "in_review"
