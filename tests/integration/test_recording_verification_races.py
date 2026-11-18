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
    assert status == "approved" and decided.signer_key_version == 1


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


async def _transfer(archive, owner):
    import hmac
    import json
    from dataclasses import replace
    from types import SimpleNamespace

    from services.api_gateway.recording.access_transfer import AccessTransfer
    from services.api_gateway.recording.crypto import ecies, tags
    from services.api_gateway.recording.crypto.encoding import b64url, from_b64url
    from services.api_gateway.recording.crypto.lifecycle import transfer_transcript, wraps_digest
    from tests import recording_crypto_reference as ref
    from tests.integration.test_recording_recovery_requests_database import enrol
    from tests.recording_archive_fakes import gateway_secrets

    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await enrol(owner, "sam")

    class Directory:
        async def snapshot(self, tenant, correlation):
            return SimpleNamespace(
                users=[SimpleNamespace(sub="sam")], holders_of=lambda _: {"admin": True}
            )

    transfer = AccessTransfer(archive._pool, gateway_secrets(), Directory(), lambda: NOW)
    org = "00000000-0000-4000-8000-000000000031"

    async def prepare():
        p = await transfer.prepare(
            TENANT, "admin", [cid], org, "sam", 1, b64url(bytes(32)), "review transfer"
        )
        pid, expiry = p["transferId"], p["expiresAt"]
        challenge = ecies.Sealed.from_json(
            json.dumps(p["challengeEnvelope"]), expected_type=tags.ORG_POSSESSION
        )
        nonce = ecies.open_with_private_key(
            challenge, ref.private_key(31), (TENANT, "admin", pid, "transfer", org, 1, expiry)
        )
        source = ecies.Sealed.from_json(
            json.dumps(p["keys"][0]["sourceWrap"]["envelope"]), expected_type=tags.CK_WRAP_V2
        )
        ck = ecies.open_with_private_key(
            source,
            ref.private_key(31),
            (TENANT, cid, key_id, "organisation", org, 1, bytes([31]) * 32),
        )
        wraps = {
            (cid, key_id): ecies.seal(
                tags.CK_WRAP_V2,
                from_b64url(p["targetKey"]["encPub"]),
                ck,
                (TENANT, cid, key_id, "user", "sam", 1, bytes(32)),
            )
        }
        transcript = transfer_transcript(
            TENANT,
            "admin",
            pid,
            p["organisationKey"],
            p["targetKey"],
            from_b64url(p["scopeDigest"]),
            "review transfer",
            wraps_digest(wraps),
            expiry,
        )
        return lambda: transfer.commit(
            TENANT, "admin", pid, hmac.digest(nonce, transcript, "sha256"), wraps
        )

    return (
        cid,
        replace(_assignment(cid, [key_id], reviewer="sam"), reviewer_fingerprint=bytes(32)),
        prepare,
    )


@pytest.mark.parametrize("assign_first", [True, False])
async def test_transfer_and_assignment_race_preserves_independent_grants(
    archive, owner, verifications, assign_first
):
    cid, assignment, prepare = await _transfer(archive, owner)
    commit = await prepare()

    def assign():
        return verifications.assign(assignment, NOW, supervisor=False)

    order = (assign, commit) if assign_first else (commit, assign)
    results = await _race(
        owner, f"SELECT 1 FROM conversations WHERE conversation_id='{cid}' FOR UPDATE", *order
    )
    assigned, receipt = results if assign_first else results[::-1]
    assert receipt["status"] == "committed"
    if assign_first:
        assert sorted(
            await owner.fetchval("SELECT array_agg(reason) FROM key_grants WHERE user_sub='sam'")
        ) == ["review", "transfer"]
        assert await verifications.decline(TENANT, "sam", assigned.verification_id, NOW) is None
    else:
        assert assigned == Refused("reviewer_not_eligible")
    assert await owner.fetchval(
        "SELECT array_agg(reason) FROM key_grants WHERE user_sub='sam'"
    ) == ["transfer"]
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref='sam'") == 1


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


@pytest.mark.parametrize("prepare_first", [True, False])
async def test_transfer_preview_racing_assignment_grants_nothing(
    archive, owner, verifications, prepare_first
):
    cid, assignment, prepare = await _transfer(archive, owner)

    def assign():
        return verifications.assign(assignment, NOW, supervisor=False)

    order = (prepare, assign) if prepare_first else (assign, prepare)
    await _race(
        owner, f"SELECT 1 FROM conversations WHERE conversation_id='{cid}' FOR UPDATE", *order
    )
    assert await owner.fetchval(
        "SELECT array_agg(reason) FROM key_grants WHERE user_sub='sam'"
    ) == ["review"]
    assert await owner.fetchval("SELECT count(*) FROM verifications WHERE status='awaiting'") == 1


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
    # Supersession acts only on the user's key. A decline still releases its own grant.
    await asyncio.gather(first(), second())
    assert await _open_for(owner, "rita") == (0, 0)
    assert await owner.fetchval("SELECT status FROM verifications") == "declined"


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


async def test_an_assignment_waiting_on_a_revocation_sees_the_wraps_it_removed(
    archive, owner, verifications
):
    """Review finding 1: the opening rule is read after the lock, not from before the wait."""
    from tests.integration.test_recording_archive_access_database import _recovered

    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await _recovered(owner, conversation, key_id, requester="sam")  # sam's key is version 1
    await _key(owner, "rita")
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        # What the nightly check does to a supervisor who lost `supervise`.
        await holder.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR SHARE", uuid.UUID(cid)
        )
        await holder.execute("DELETE FROM key_wraps WHERE recipient_ref = 'sam'")
        queued = asyncio.create_task(
            verifications.assign(_assignment(cid, [key_id], requester="sam"), NOW, supervisor=True)
        )
        await _waiting(owner, 1)
        await transaction.commit()
        refused = await queued
    finally:
        await holder.close()
    assert refused == Refused("not_found")
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'rita'") == 0
