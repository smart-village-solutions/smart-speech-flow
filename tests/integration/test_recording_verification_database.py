"""The verification tables enforce what the gateway assumes (spec §10.7; migration 011)."""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import asyncpg
import pytest

from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.verification_model import AssignWrap, NewAssignment
from services.api_gateway.recording.verification_repository import PostgresVerifications
from services.api_gateway.recording.verification_sql import LIVE_REASON
from tests.integration.test_recording_archive_access_database import (
    _ended,
    _recovered,
    access,  # noqa: F401 - fixture
)
from tests.integration.test_recording_archive_database import (
    _BIND,
    APP_DSN,
    APP_PASSWORD,
    NOW,
    TENANT,
    _opened,
    archive,  # noqa: F401 - fixture
    owner,  # noqa: F401 - fixture
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _no_keys(owner):
    await owner.execute("TRUNCATE user_keys CASCADE")
    yield


RETENTION_DSN = os.environ.get("SSF_RECORDING_RETENTION_DATABASE_URL", "")
RETENTION_PASSWORD = os.environ.get("SSF_RECORDING_RETENTION_DATABASE_PASSWORD") or None
_ENVELOPE = b"\x01" + bytes(40)


async def _as(dsn, password, statements, tenant=TENANT):
    connection = await asyncpg.connect(dsn, password=password)
    try:
        async with connection.transaction():
            await connection.execute(_BIND, tenant)
            for statement, *args in statements:
                await connection.execute(statement, *args)
    finally:
        await connection.close()


def _app(*statements, tenant=TENANT):
    return _as(APP_DSN, APP_PASSWORD, statements, tenant)


_INSERT = (
    "INSERT INTO verifications (tenant_id, verification_id, conversation_id, status,"
    " requested_by, requester_key_version, requested_at, directory_read_at, reviewer_sub,"
    " reviewer_key_version, reviewer_fingerprint) VALUES ($1, $2, $3, $4, 'alice', 1, $5, $5,"
    " $6, 1, $7)"
)


async def _verification(conversation_id, status="awaiting", reviewer="rita"):
    verification_id = str(uuid.uuid4())
    await _app(
        (_INSERT, TENANT, verification_id, conversation_id, status, NOW, reviewer, b"\x07" * 32)
    )
    return verification_id


async def _decide(verification_id, entry_id, key_id):
    await _app(
        (
            "UPDATE verifications SET status = 'in_review', started_at = $2, reviewed_head_seq = 1,"
            " reviewed_head = $3, permission_snapshot = ARRAY['ssf.recording.review']"
            " WHERE verification_id = $1",
            verification_id,
            NOW,
            b"\x01" * 32,
        ),
        (
            "INSERT INTO verification_notes VALUES ($1, $2, $3, $4, $5)",
            TENANT,
            verification_id,
            entry_id,
            key_id,
            _ENVELOPE,
        ),
        (
            "UPDATE verifications SET status = 'approved', outcome = 'approved', notes_digest = $2,"
            " signature = $3, signer_key_version = 1, decided_at = $4, stamp_requested_at = $4,"
            " stamp_next_attempt_at = $4 WHERE verification_id = $1",
            verification_id,
            b"\x02" * 32,
            b"\x03" * 64,
            NOW,
        ),
    )


async def test_one_open_assignment_per_reviewer_and_conversation(archive, owner):
    conversation, *_ = await _opened(archive)
    await _verification(conversation.conversation_id)
    with pytest.raises(asyncpg.UniqueViolationError):
        await _verification(conversation.conversation_id)
    await _verification(conversation.conversation_id, reviewer="ralf")


async def test_a_closed_assignment_does_not_block_a_new_one(archive, owner):
    conversation, *_ = await _opened(archive)
    first = await _verification(conversation.conversation_id)
    await _app(
        (
            "UPDATE verifications SET status = 'declined', closed_at = $2, close_reason = 'declined'"
            " WHERE verification_id = $1",
            first,
            NOW,
        )
    )
    await _verification(conversation.conversation_id)


async def test_a_reviewer_cannot_be_the_requester(archive, owner):
    conversation, *_ = await _opened(archive)
    with pytest.raises(asyncpg.CheckViolationError):
        await _verification(conversation.conversation_id, reviewer="alice")


async def test_a_decided_record_is_frozen_except_its_stamp(archive, owner):
    conversation, key_id, _, consent = await _opened(archive)
    verification_id = await _verification(conversation.conversation_id)
    await _decide(verification_id, consent.entry_id, key_id)

    await _app(
        (
            "UPDATE verifications SET tsa_token = $2, stamped_at = $3, stamp_attempts = 1"
            " WHERE verification_id = $1",
            verification_id,
            b"tok",
            NOW,
        )
    )
    for change in ("outcome = 'not_approved', status = 'not_approved'", "notes_digest = $2"):
        args = (verification_id, b"\x09" * 32) if "$2" in change else (verification_id,)
        with pytest.raises(asyncpg.CheckViolationError, match="frozen"):
            await _app((f"UPDATE verifications SET {change} WHERE verification_id = $1", *args))


async def test_a_closed_record_is_frozen(archive, owner):
    conversation, *_ = await _opened(archive)
    verification_id = await _verification(conversation.conversation_id)
    await _app(
        (
            "UPDATE verifications SET status = 'withdrawn', closed_at = $2,"
            " close_reason = 'key_retired' WHERE verification_id = $1",
            verification_id,
            NOW,
        )
    )
    with pytest.raises(asyncpg.CheckViolationError, match="frozen"):
        await _app(
            (
                "UPDATE verifications SET status = 'awaiting' WHERE verification_id = $1",
                verification_id,
            )
        )


async def test_notes_change_only_while_in_review(archive, owner):
    conversation, key_id, _, consent = await _opened(archive)
    verification_id = await _verification(conversation.conversation_id)
    note = (
        "INSERT INTO verification_notes VALUES ($1, $2, $3, $4, $5)",
        TENANT,
        verification_id,
        consent.entry_id,
        key_id,
        _ENVELOPE,
    )
    with pytest.raises(asyncpg.CheckViolationError, match="not in review"):
        await _app(note)
    await _decide(verification_id, consent.entry_id, key_id)
    with pytest.raises(asyncpg.CheckViolationError, match="not in review"):
        await _app(("DELETE FROM verification_notes WHERE verification_id = $1", verification_id))


async def test_retention_role_deletes_decided_records_and_notes(archive, owner):
    if not RETENTION_DSN:
        pytest.skip("SSF_RECORDING_RETENTION_DATABASE_URL is not set")
    conversation, key_id, _, consent = await _opened(archive)
    verification_id = await _verification(conversation.conversation_id)
    await _decide(verification_id, consent.entry_id, key_id)
    await _as(
        RETENTION_DSN,
        RETENTION_PASSWORD,
        (
            ("DELETE FROM verification_notes WHERE verification_id = $1", verification_id),
            ("DELETE FROM verifications WHERE verification_id = $1", verification_id),
        ),
    )
    assert await owner.fetchval("SELECT count(*) FROM verifications") == 0


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM verifications",
        "UPDATE verification_notes SET ciphertext = ciphertext",
        "DELETE FROM revocation_runs",
    ],
)
async def test_the_app_cannot_delete_records_or_rewrite_notes(archive, owner, statement):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _app((statement,))


async def test_verifications_are_confined_to_their_tenant(archive, owner):
    conversation, *_ = await _opened(archive)
    await _verification(conversation.conversation_id)
    connection = await asyncpg.connect(APP_DSN, password=APP_PASSWORD)
    try:
        async with connection.transaction():
            await connection.execute(_BIND, "tenant-b")
            assert await connection.fetchval("SELECT count(*) FROM verifications") == 0
    finally:
        await connection.close()


async def test_the_app_claims_a_revocation_run_once(archive, owner):
    claim = (
        "INSERT INTO revocation_runs (tenant_id, run_date, started_at) VALUES ($1, $2, $3)",
        TENANT,
        date(2026, 11, 3),
        NOW,
    )
    await _app(claim)
    with pytest.raises(asyncpg.UniqueViolationError):
        await _app(claim)
    await _app(
        (
            "UPDATE revocation_runs SET finished_at = $2, outcome = 'done' WHERE run_date = $1",
            date(2026, 11, 3),
            NOW + timedelta(minutes=1),
        )
    )


async def _granted(owner, key_id, recipient, creator):
    await owner.execute(
        "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
        " creator_ref, creator_signature, granted_at) VALUES ($1, $2, 'user', $3, '{}', $4, $5, $6)",
        TENANT,
        uuid.UUID(key_id),
        recipient,
        creator,
        bytes(64),
        NOW,
    )


async def _reasons(owner, conversation_id):
    rows = await owner.fetch(
        "SELECT w.recipient_ref, w.creator_ref, " + LIVE_REASON + " AS live FROM key_wraps w"
        " JOIN conversation_keys k ON k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
        " JOIN conversations c ON c.tenant_id = k.tenant_id AND c.conversation_id = k.conversation_id"
        " WHERE c.conversation_id = $1 AND w.recipient_kind = 'user'",
        uuid.UUID(conversation_id),
    )
    return {(r["recipient_ref"], r["creator_ref"]): r["live"] for r in rows}


async def test_live_reason_counts_each_kind_of_wrap(archive, owner):
    conversation, key_id, _ = await _ended(archive, owner)  # alice's own, gateway-made
    cid = conversation.conversation_id
    await _recovered(owner, conversation, key_id, requester="sam")  # self-made, completed
    await _recovered(owner, conversation, key_id, requester="olga", status="open")  # not completed
    await _granted(owner, key_id, "rita", "alice")  # assigned below
    await _granted(owner, key_id, "ralf", "alice")  # no assignment
    await _granted(owner, key_id, "rosa", "sam")  # an assignment by someone else
    await _verification(cid, reviewer="rita")
    await _verification(cid, reviewer="rosa")  # requested_by alice, but sam made the wrap

    reasons = await _reasons(owner, cid)

    assert {who: live for (who, _), live in reasons.items()} == {
        "alice": True,
        "sam": True,
        "olga": False,
        "rita": True,
        "ralf": False,
        "rosa": False,
    }


async def test_a_closed_assignment_leaves_its_wrap_without_a_reason(archive, owner):
    conversation, key_id, _ = await _ended(archive, owner)
    await _granted(owner, key_id, "rita", "alice")
    verification_id = await _verification(conversation.conversation_id, reviewer="rita")
    await _app(
        (
            "UPDATE verifications SET status = 'declined', closed_at = $2, close_reason = 'declined'"
            " WHERE verification_id = $1",
            verification_id,
            NOW,
        )
    )
    assert (await _reasons(owner, conversation.conversation_id))[("rita", "alice")] is False


async def test_a_supervisor_cannot_open_through_a_reviewer_grant(archive, owner, access):
    """M1: a completed request must not turn reviewer wraps into supervisor access."""
    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await _recovered(owner, conversation, key_id, requester="sam")
    await owner.execute("DELETE FROM key_wraps WHERE recipient_ref = 'sam'")  # re-enrolled
    await _granted(owner, key_id, "sam", "alice")

    assert await access.open(TENANT, "sam", cid, NOW, supervisor=True) is None
    assert not await access.openable(TENANT, "sam", cid, NOW, supervisor=True)
    listed = await access.own_conversations(
        TENANT, "sam", NOW, limit=50, started_before=None, before_id=None, supervisor=True
    )
    assert listed == []
    location = await access.object_location(
        TENANT,
        "sam",
        cid,
        "00000000-0000-4000-8000-000000000000",
        "record.json",
        NOW,
        supervisor=True,
    )
    assert location is None


async def test_the_employee_still_opens_with_a_self_made_wrap(archive, owner, access):
    conversation, key_id, _ = await _ended(archive, owner, wrapped=False)
    await _granted(owner, key_id, "alice", "alice")  # key recovery (§9.6)
    assert await access.open(TENANT, "alice", conversation.conversation_id, NOW) is not None


def _point(seed: int) -> bytes:
    return b"\x04" + bytes([seed]) * 64


async def _key(owner, sub, version=1, *, retired=False):
    await owner.execute(
        "INSERT INTO user_keys (tenant_id, user_sub, key_version, enc_pub, sig_pub, fingerprint,"
        " encrypted_private, created_at, retired_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        TENANT,
        sub,
        version,
        _point(version),
        _point(version + 100),
        bytes([version]) * 32,
        b"blob",
        NOW,
        NOW if retired else None,
    )


@pytest.fixture
async def verifications(archive):
    return PostgresVerifications(archive._pool)


def _assignment(
    conversation_id, key_ids, *, reviewer="rita", reviewer_version=1, requester="alice"
):
    return NewAssignment(
        tenant_id=TENANT,
        conversation_id=conversation_id,
        requester_sub=requester,
        requester_key_version=1,
        reviewer_sub=reviewer,
        reviewer_key_version=reviewer_version,
        reviewer_fingerprint=bytes([reviewer_version]) * 32,
        directory_read_at=NOW,
        wraps=tuple(AssignWrap(key_id, '{"w":1}', bytes(64)) for key_id in key_ids),
    )


async def _assignable(archive, owner, reviewer="rita"):
    conversation, key_id, consent = await _ended(archive, owner)
    await _key(owner, "alice")
    await _key(owner, reviewer)
    return conversation.conversation_id, key_id


async def test_an_assignment_inserts_assigner_made_wraps_and_audits(archive, owner, verifications):
    cid, key_id = await _assignable(archive, owner)

    row = await verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)

    assert not isinstance(row, Refused)
    assert (row.status, row.reviewer_sub, row.requested_by) == ("awaiting", "rita", "alice")
    wrap = await owner.fetchrow("SELECT * FROM key_wraps WHERE recipient_ref = 'rita'")
    assert (wrap["recipient_kind"], wrap["creator_ref"], str(wrap["key_id"])) == (
        "user",
        "alice",
        key_id,
    )
    audit = await owner.fetch(
        "SELECT actor_sub, event_type, object_ref FROM audit_events ORDER BY seq"
    )
    assert [(r["actor_sub"], r["event_type"], r["object_ref"]) for r in audit[-2:]] == [
        ("alice", "recording.verification.requested", f"{row.verification_id}:rita"),
        ("alice", "key_wrap.granted", f"{key_id}:rita"),
    ]


@pytest.mark.parametrize("who", ["alice", "sam", "olga", "wrapped"])
async def test_nobody_who_can_or_tries_to_read_it_can_be_assigned(
    archive, owner, verifications, who
):
    """The employee, a recovered or recovering supervisor, or any wrapped user (§10.7)."""
    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await _key(owner, "alice")
    requester, supervisor = "alice", False
    if who == "alice":
        # A recovered supervisor tries to assign the employee herself.
        await _recovered(owner, conversation, key_id, requester="sam")
        requester, supervisor = "sam", True
    elif who == "sam":
        await _recovered(owner, conversation, key_id, requester="sam")
    elif who == "olga":
        await _recovered(owner, conversation, key_id, requester="olga", status="open")
        await owner.execute("DELETE FROM key_wraps WHERE recipient_ref = 'olga'")
    else:
        await _granted(owner, key_id, "wrapped", "someone")
        await _key(owner, "wrapped")

    refused = await verifications.assign(
        _assignment(cid, [key_id], reviewer=who, requester=requester), NOW, supervisor=supervisor
    )

    assert refused == Refused("reviewer_not_eligible")


async def test_a_second_open_assignment_is_refused(archive, owner, verifications):
    cid, key_id = await _assignable(archive, owner)
    await verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)
    await owner.execute("DELETE FROM key_wraps WHERE recipient_ref = 'rita'")  # past the exclusion

    refused = await verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)

    assert refused == Refused("assignment_exists")


async def test_stale_keys_and_a_short_scope_are_refused(archive, owner, verifications):
    cid, key_id = await _assignable(archive, owner)
    assert await verifications.assign(
        _assignment(cid, [key_id], reviewer_version=2), NOW, supervisor=False
    ) == Refused("reviewer_key_changed")
    assert await verifications.assign(_assignment(cid, []), NOW, supervisor=False) == Refused(
        "scope_not_covered"
    )
    await owner.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'alice'", NOW)
    assert await verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False) == Refused(
        "key_changed"
    )
    assert await owner.fetchval("SELECT count(*) FROM verifications") == 0


async def test_another_employees_conversation_is_not_found(archive, owner, verifications):
    cid, key_id = await _assignable(archive, owner)
    await _key(owner, "bob")
    refused = await verifications.assign(
        _assignment(cid, [key_id], requester="bob"), NOW, supervisor=False
    )
    assert refused == Refused("not_found")


async def test_candidates_exclude_and_keys_are_read(archive, owner, verifications):
    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await _recovered(owner, conversation, key_id, requester="sam")
    for sub in ("rita", "ralf"):
        await _key(owner, sub)
    await _key(owner, "gone", retired=True)
    await _verification(cid, reviewer="ralf")

    excluded = await verifications.excluded(TENANT, cid, ["alice", "sam", "rita", "ralf"], NOW)
    keys = await verifications.active_keys(TENANT, ["rita", "gone"])

    assert excluded == frozenset({"alice", "sam", "ralf"})
    assert set(keys) == {"rita"} and keys["rita"].key_version == 1
    assert await verifications.conversation_keys(TENANT, cid) == (key_id,)


async def _assigned(archive, owner, verifications, reviewer="rita"):
    cid, key_id = await _assignable(archive, owner, reviewer)
    row = await verifications.assign(
        _assignment(cid, [key_id], reviewer=reviewer), NOW, supervisor=False
    )
    return cid, key_id, row


async def test_a_reviewer_opens_only_their_open_assignment(archive, owner, verifications):
    """AC1: wrapped for them under an open assignment, and nothing else."""
    cid, key_id, row = await _assigned(archive, owner, verifications)
    await _key(owner, "ralf")

    opened = await verifications.open_review(
        TENANT, "rita", row.verification_id, NOW, reviewer=True
    )
    other = await verifications.open_review(TENANT, "ralf", row.verification_id, NOW, reviewer=True)
    unpermitted = await verifications.open_review(
        TENANT, "rita", row.verification_id, NOW, reviewer=False
    )

    assert opened is not None and opened.conversation.conversation_id == cid
    assert opened.record.verification_id == row.verification_id and opened.draft == ()
    assert opened.conversation.verifications == ()  # never another reviewer's record
    assert opened.requester is not None and opened.requester.sub == "alice"
    assert [k.wrap.creator_ref for k in opened.conversation.keys] == ["alice"]
    assert other is None and unpermitted is None
    audit = await owner.fetch(
        "SELECT actor_sub, event_type, object_ref FROM audit_events ORDER BY seq"
    )
    assert [(r["actor_sub"], r["event_type"]) for r in audit[-3:]] == [
        ("rita", "recording.archive.opened"),
        ("ralf", "recording.verification.not_found"),
        ("rita", "recording.verification.not_found"),
    ]

    await _app(
        (
            "UPDATE verifications SET status = 'withdrawn', closed_at = $2, close_reason = 'key_retired'"
            " WHERE verification_id = $1",
            row.verification_id,
            NOW,
        )
    )
    assert (
        await verifications.open_review(TENANT, "rita", row.verification_id, NOW, reviewer=True)
        is None
    )


async def test_a_reviewer_never_opens_through_the_archive(archive, owner, verifications, access):
    cid, key_id, row = await _assigned(archive, owner, verifications)

    assert await access.open(TENANT, "rita", cid, NOW, supervisor=True) is None
    listed = await access.own_conversations(
        TENANT, "rita", NOW, limit=50, started_before=None, before_id=None, supervisor=True
    )
    assert listed == []
    consent = await owner.fetchval(
        "SELECT entry_id FROM chain_entries WHERE conversation_id = $1", uuid.UUID(cid)
    )
    args = (TENANT, "rita", cid, str(consent), "record.json", NOW)
    assert await access.object_location(*args) is None
    assert await access.object_location(*args, reviewer=True) is not None
    assert await access.openable(TENANT, "rita", cid, NOW, reviewer=True)
    assert not await access.openable(TENANT, "rita", cid, NOW)


async def test_the_inbox_lists_open_assignments_first(archive, owner, verifications):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    other, _, _ = await _ended(archive, owner)
    closed = await _verification(other.conversation_id, reviewer="rita")
    await _app(
        (
            "UPDATE verifications SET status = 'declined', closed_at = $2, close_reason = 'declined'"
            " WHERE verification_id = $1",
            closed,
            NOW,
        )
    )

    inbox = await verifications.inbox(TENANT, "rita", NOW)

    assert [(r.verification_id, r.status, r.openable) for r in inbox] == [
        (row.verification_id, "awaiting", True),
        (closed, "declined", False),
    ]
    assert inbox[0].requested_by == "alice" and inbox[0].messages == 0
    assert await verifications.inbox(TENANT, "ralf", NOW) == []


SNAPSHOT = ("ssf.recording.review",)
SWORN = ("ssf.recording.review", "ssf.recording.review.sworn")


async def _consent(owner, cid):
    return await owner.fetchrow(
        "SELECT entry_id, key_id, seq, hash FROM chain_entries WHERE conversation_id = $1"
        " ORDER BY seq DESC LIMIT 1",
        uuid.UUID(cid),
    )


async def test_starting_records_the_head_and_again_refreshes_only_the_snapshot(
    archive, owner, verifications
):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    vid = row.verification_id

    assert await verifications.start(
        TENANT, "rita", vid, head["seq"] + 1, SNAPSHOT, NOW
    ) == Refused("head_changed")
    started = await verifications.start(TENANT, "rita", vid, head["seq"], SNAPSHOT, NOW)
    again = await verifications.start(TENANT, "rita", vid, 999, SWORN, NOW + timedelta(hours=1))

    assert (started.status, started.reviewed_head_seq, started.reviewed_head) == (
        "in_review",
        head["seq"],
        bytes(head["hash"]),
    )
    assert (again.permission_snapshot, again.reviewed_head_seq, again.started_at) == (
        SWORN,
        head["seq"],
        NOW,
    )
    events = [r["event_type"] for r in await owner.fetch("SELECT event_type FROM audit_events")]
    assert events.count("recording.verification.started") == 1
    assert await verifications.start(TENANT, "ralf", vid, head["seq"], SNAPSHOT, NOW) == Refused(
        "verification_not_found"
    )


async def test_drafts_are_saved_only_in_review_and_only_for_reviewed_entries(
    archive, owner, verifications
):
    from services.api_gateway.recording.verification_model import NotePost

    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    vid = row.verification_id
    note = NotePost(str(head["entry_id"]), key_id, _ENVELOPE)

    assert await verifications.save_draft(TENANT, "rita", vid, None, [note], NOW) == Refused(
        "not_started"
    )
    await verifications.start(TENANT, "rita", vid, head["seq"], SNAPSHOT, NOW)
    foreign = NotePost(str(head["entry_id"]), str(uuid.uuid4()), _ENVELOPE)
    assert await verifications.save_draft(TENANT, "rita", vid, None, [foreign], NOW) == Refused(
        "bad_notes"
    )
    unknown = NotePost(str(uuid.uuid4()), key_id, _ENVELOPE)
    assert await verifications.save_draft(TENANT, "rita", vid, None, [unknown], NOW) == Refused(
        "bad_notes"
    )

    assert (
        await verifications.save_draft(TENANT, "rita", vid, b"\x01" + bytes(30), [note], NOW)
        is None
    )
    assert await verifications.save_draft(TENANT, "rita", vid, None, [note], NOW) is None
    opened = await verifications.open_review(TENANT, "rita", vid, NOW, reviewer=True)
    assert opened.draft == (note,) and opened.record.overall_note is None
    events = [r["event_type"] for r in await owner.fetch("SELECT event_type FROM audit_events")]
    assert not any("draft" in event for event in events)


async def test_declining_releases_the_grant_but_keeps_other_reasons(archive, owner, verifications):
    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await _key(owner, "alice")
    await _key(owner, "rita")
    row = await verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)
    head = await _consent(owner, cid)
    await verifications.start(TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW)
    await _app(
        (
            "INSERT INTO verification_notes VALUES ($1, $2, $3, $4, $5)",
            TENANT,
            row.verification_id,
            head["entry_id"],
            key_id,
            _ENVELOPE,
        )
    )

    assert await verifications.decline(TENANT, "rita", row.verification_id, NOW) is None
    assert await verifications.decline(TENANT, "rita", row.verification_id, NOW) == Refused(
        "verification_closed"
    )

    assert await owner.fetchval("SELECT status FROM verifications") == "declined"
    assert await owner.fetchval("SELECT count(*) FROM verification_notes") == 0
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'rita'") == 0
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'alice'") == 1
    audit = await owner.fetch(
        "SELECT actor_sub, event_type, object_ref FROM audit_events ORDER BY seq"
    )
    assert [(r["event_type"], r["object_ref"]) for r in audit[-2:]] == [
        ("recording.verification.declined", f"{row.verification_id}:rita"),
        ("key_wrap.released", f"{key_id}:rita"),
    ]


async def test_releasing_never_takes_a_wrap_with_another_reason(archive, owner, verifications):
    """The live-reason rule at release: a second open assignment by the same assigner stays."""
    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await _key(owner, "alice")
    await _key(owner, "rita")
    row = await verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)
    # A second record for the same reviewer cannot be open (unique index); fake another reason:
    await owner.execute(
        "UPDATE conversations SET employee_sub = 'rita' WHERE conversation_id = $1", uuid.UUID(cid)
    )

    assert await verifications.decline(TENANT, "rita", row.verification_id, NOW) is None
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'rita'") == 1


def _decision(record, outcome, overall, notes, signature=bytes(64), digest=b"\x02" * 32):
    from services.api_gateway.recording.verification_model import DecisionPost

    return DecisionPost(
        outcome=outcome,
        overall=overall,
        notes=tuple(notes),
        signature=signature,
        notes_digest=digest,
        signed_digest=b"\x0a" * 32,
        signer_key_version=1,
        signer_fingerprint=record.reviewer_fingerprint,
        snapshot=record.permission_snapshot or (),
        reviewed_head=record.reviewed_head or b"",
    )


async def _started(archive, owner, verifications, reviewer="rita"):
    cid, key_id, row = await _assigned(archive, owner, verifications, reviewer)
    head = await _consent(owner, cid)
    started = await verifications.start(
        TENANT, reviewer, row.verification_id, head["seq"], SNAPSHOT, NOW
    )
    return cid, key_id, head, started


async def test_a_decision_freezes_the_record_queues_its_stamp_and_releases_the_grant(
    archive, owner, verifications
):
    from services.api_gateway.recording.verification_model import NotePost

    cid, key_id, head, record = await _started(archive, owner, verifications)
    note = NotePost(str(head["entry_id"]), key_id, _ENVELOPE)

    decided = await verifications.decide(
        TENANT, "rita", record.verification_id, _decision(record, "not_approved", None, [note]), NOW
    )

    assert (decided.status, decided.outcome, decided.decided_at) == (
        "not_approved",
        "not_approved",
        NOW,
    )
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'rita'") == 0
    assert await owner.fetchval("SELECT stamp_next_attempt_at FROM verifications") == NOW
    audit = await owner.fetch("SELECT event_type, object_ref FROM audit_events ORDER BY seq")
    assert [(r["event_type"], r["object_ref"]) for r in audit[-2:]] == [
        ("recording.verification.decided.not_approved", f"{record.ref}:{'0a' * 32}"),
        ("key_wrap.released", f"{key_id}:rita"),
    ]
    again = await verifications.decide(
        TENANT, "rita", record.verification_id, _decision(record, "approved", None, []), NOW
    )
    assert again == Refused("verification_closed")
    assert (
        await verifications.open_review(TENANT, "rita", record.verification_id, NOW, reviewer=True)
        is None
    )


async def test_a_decision_is_refused_for_a_changed_key_or_a_record_not_started(
    archive, owner, verifications
):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    assert await verifications.decide(
        TENANT, "rita", row.verification_id, _decision(row, "approved", None, []), NOW
    ) == Refused("not_started")
    head = await _consent(owner, cid)
    record = await verifications.start(
        TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW
    )
    await owner.execute(
        "UPDATE user_keys SET fingerprint = $1 WHERE user_sub = 'rita'", b"\x09" * 32
    )
    assert await verifications.decide(
        TENANT, "rita", record.verification_id, _decision(record, "approved", None, []), NOW
    ) == Refused("key_changed")


async def test_a_decision_verifies_against_the_reviewers_key_and_the_exact_head(
    archive, owner, verifications
):
    """AC2 at database level: what is stored verifies, and any change is detected."""
    from services.api_gateway.recording.crypto import tags
    from services.api_gateway.recording.crypto.signatures import verify_fields
    from services.api_gateway.recording.crypto.verification import notes_digest, verification_fields
    from services.api_gateway.recording.verification_model import NotePost
    from tests.recording_verification_world import decision_signature, person

    rita = person("rita", 2)
    cid, key_id, head, record = await _started(archive, owner, verifications)
    await owner.execute(
        "UPDATE user_keys SET sig_pub = $1, enc_pub = $2, fingerprint = $3 WHERE user_sub = 'rita'",
        rita.key.sig_pub,
        rita.key.enc_pub,
        record.reviewer_fingerprint,
    )
    note = NotePost(str(head["entry_id"]), key_id, b"\x01" + bytes(50))
    overall = b"\x01" + bytes(31)
    signature, signed = decision_signature(
        rita,
        cid,
        record.verification_id,
        bytes(head["hash"]),
        "approved",
        overall,
        [note],
        SNAPSHOT,
    )
    digest = notes_digest(overall, [(note.entry_id, note.key_id, note.ciphertext)])
    post = _decision(record, "approved", overall, [note], signature, digest)
    await verifications.decide(TENANT, "rita", record.verification_id, post, NOW)

    stored = await owner.fetchrow("SELECT * FROM verifications")
    notes = await owner.fetch("SELECT entry_id, key_id, ciphertext FROM verification_notes")
    sig_pub = await owner.fetchval("SELECT sig_pub FROM user_keys WHERE user_sub = 'rita'")

    def verifies(head_hash=None, outcome=None, ciphertext=None, snapshot=None):
        stored_notes = [
            (str(n["entry_id"]), str(n["key_id"]), ciphertext or bytes(n["ciphertext"]))
            for n in notes
        ]
        fields = verification_fields(
            TENANT,
            str(stored["verification_id"]),
            str(stored["conversation_id"]),
            head_hash or bytes(stored["reviewed_head"]),
            outcome or stored["outcome"],
            notes_digest(bytes(stored["overall_note"]), stored_notes),
            snapshot or stored["permission_snapshot"],
        )
        return verify_fields(
            bytes(sig_pub), bytes(stored["signature"]), tags.VERIFICATION_SIG, *fields
        )

    assert verifies()
    assert not verifies(head_hash=b"\x00" * 32)
    assert not verifies(outcome="not_approved")
    assert not verifies(ciphertext=b"\x01" + bytes(51))
    assert not verifies(snapshot=list(SWORN))


async def test_two_reviewers_disagree_and_both_records_stay(archive, owner, verifications):
    """AC3 at database level: two decided records side by side."""
    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    for sub in ("alice", "rita", "ralf"):
        await _key(owner, sub)
    head = await _consent(owner, cid)
    for reviewer, outcome in (("rita", "approved"), ("ralf", "not_approved")):
        row = await verifications.assign(
            _assignment(cid, [key_id], reviewer=reviewer), NOW, supervisor=False
        )
        record = await verifications.start(
            TENANT, reviewer, row.verification_id, head["seq"], SNAPSHOT, NOW
        )
        await verifications.decide(
            TENANT, reviewer, row.verification_id, _decision(record, outcome, None, []), NOW
        )

    rows = await owner.fetch(
        "SELECT reviewer_sub, outcome FROM verifications ORDER BY reviewer_sub"
    )
    assert [(r["reviewer_sub"], r["outcome"]) for r in rows] == [
        ("ralf", "not_approved"),
        ("rita", "approved"),
    ]


async def test_decision_stamps_are_queued_saved_and_deferred(archive, owner, verifications):
    cid, key_id, head, record = await _started(archive, owner, verifications)
    await verifications.decide(
        TENANT, "rita", record.verification_id, _decision(record, "approved", None, []), NOW
    )

    [due] = await verifications.pending_decision_stamps(TENANT, NOW)
    assert (due.verification_id, due.url, due.attempts) == (
        record.verification_id,
        "https://tsa.test/tsr",
        0,
    )
    await verifications.defer_decision_stamp(TENANT, due, NOW + timedelta(minutes=5))
    assert await verifications.pending_decision_stamps(TENANT, NOW) == []
    [later] = await verifications.pending_decision_stamps(TENANT, NOW + timedelta(minutes=5))
    await verifications.save_decision_stamp(TENANT, later, b"token", NOW)
    assert await verifications.pending_decision_stamps(TENANT, NOW + timedelta(days=1)) == []
    assert bytes(await owner.fetchval("SELECT tsa_token FROM verifications")) == b"token"


async def test_results_carry_decided_notes_and_never_drafts(archive, owner, verifications, access):
    from services.api_gateway.recording.verification_model import NotePost

    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    for sub in ("alice", "rita", "ralf"):
        await _key(owner, sub)
    head = await _consent(owner, cid)
    note = NotePost(str(head["entry_id"]), key_id, _ENVELOPE)
    decided = await verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)
    record = await verifications.start(
        TENANT, "rita", decided.verification_id, head["seq"], SNAPSHOT, NOW
    )
    await verifications.decide(
        TENANT, "rita", decided.verification_id, _decision(record, "approved", None, [note]), NOW
    )
    drafting = await verifications.assign(
        _assignment(cid, [key_id], reviewer="ralf"), NOW, supervisor=False
    )
    await verifications.start(TENANT, "ralf", drafting.verification_id, head["seq"], SNAPSHOT, NOW)
    await verifications.save_draft(TENANT, "ralf", drafting.verification_id, _ENVELOPE, [note], NOW)

    opened = await access.open(TENANT, "alice", cid, NOW)
    [listed] = await access.own_conversations(
        TENANT, "alice", NOW, limit=50, started_before=None, before_id=None
    )

    by_reviewer = {r.row.reviewer_sub: r for r in opened.verifications}
    assert by_reviewer["rita"].notes == (note,) and by_reviewer["rita"].reviewer_key.sub == "rita"
    assert by_reviewer["ralf"].notes == () and by_reviewer["ralf"].row.overall_note is None
    assert by_reviewer["ralf"].reviewer_key is None
    assert (listed.open_reviews, listed.approved, listed.not_approved) == (1, 1, 0)
    assert listed.public("alice")["verification"] == {
        "status": "in_review",
        "approved": 1,
        "not_approved": 0,
    }


async def _assignment_in_review(archive, owner, verifications):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    await verifications.start(TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW)
    await _app(
        (
            "INSERT INTO verification_notes VALUES ($1, $2, $3, $4, $5)",
            TENANT,
            row.verification_id,
            head["entry_id"],
            key_id,
            _ENVELOPE,
        )
    )
    return cid, key_id, row


async def test_a_leaver_marking_withdraws_the_reviewers_open_assignment(
    archive, owner, verifications
):
    from services.api_gateway.recording.leavers_repository import PostgresLeavers

    cid, key_id, row = await _assignment_in_review(archive, owner, verifications)

    await PostgresLeavers(archive._pool).mark(TENANT, "rita", 1, "admin", NOW)

    stored = await owner.fetchrow("SELECT status, close_reason FROM verifications")
    assert (stored["status"], stored["close_reason"]) == ("withdrawn", "key_retired")
    assert await owner.fetchval("SELECT count(*) FROM verification_notes") == 0
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'rita'") == 0
    events = {
        (r["actor_sub"], r["event_type"], r["object_ref"])
        for r in await owner.fetch("SELECT actor_sub, event_type, object_ref FROM audit_events")
    }
    assert ("admin", "recording.verification.withdrawn.key_retired", row.ref) in events


async def test_a_reenrolment_withdraws_the_reviewers_open_assignment(archive, owner, verifications):
    from services.api_gateway.recording.repository import UserKeyRecord
    from tests.recording_swap import swap_key

    cid, key_id, row = await _assignment_in_review(archive, owner, verifications)
    record = UserKeyRecord(
        tenant_id=TENANT,
        user_sub="rita",
        key_version=2,
        enc_pub=_point(9),
        sig_pub=_point(19),
        fingerprint=b"\x09" * 32,
        encrypted_private=b"blob",
        created_at=NOW,
    )

    assert await swap_key(archive._pool, record, 1, NOW) is None

    assert await owner.fetchval("SELECT status FROM verifications") == "withdrawn"
    events = {
        (r["actor_sub"], r["event_type"])
        for r in await owner.fetch("SELECT actor_sub, event_type FROM audit_events")
    }
    assert ("rita", "recording.verification.withdrawn.key_retired") in events


async def test_a_completed_request_keeps_only_the_wraps_its_requester_made(archive, owner):
    """A wrap someone else made for a recovering supervisor has no reason without an assignment."""
    conversation, key_id, _ = await _ended(archive, owner)
    await _recovered(owner, conversation, key_id, requester="sam")
    await owner.execute("DELETE FROM key_wraps WHERE recipient_ref = 'sam'")
    await _granted(owner, key_id, "sam", "alice")
    assert (await _reasons(owner, conversation.conversation_id))[("sam", "alice")] is False


async def test_a_draft_note_on_an_entry_after_the_reviewed_head_is_refused(
    archive, owner, verifications
):
    from services.api_gateway.recording.verification_model import NotePost

    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    await verifications.start(TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW)
    later = uuid.uuid4()
    await owner.execute(
        "INSERT INTO chain_entries (tenant_id, conversation_id, seq, entry_id, kind, window_id,"
        " key_id, objects, prev_hash, hash, signer_key_id, signature, created_at)"
        " SELECT tenant_id, conversation_id, seq + 1, $2, 'amendment', NULL, key_id, objects,"
        " hash, $3, signer_key_id, signature, created_at FROM chain_entries WHERE entry_id = $1",
        head["entry_id"],
        later,
        b"\x0b" * 32,
    )
    note = NotePost(str(later), key_id, _ENVELOPE)
    assert await verifications.save_draft(
        TENANT, "rita", row.verification_id, None, [note], NOW
    ) == Refused("bad_notes")


async def test_a_record_cannot_be_decided_without_its_proof(archive, owner):
    conversation, *_ = await _opened(archive)
    verification_id = await _verification(conversation.conversation_id)
    with pytest.raises(asyncpg.CheckViolationError):
        await _app(
            (
                "UPDATE verifications SET status = 'approved', outcome = 'approved'"
                " WHERE verification_id = $1",
                verification_id,
            )
        )


async def test_an_outcome_must_match_its_status(archive, owner):
    conversation, key_id, _, consent = await _opened(archive)
    verification_id = await _verification(conversation.conversation_id)
    await _decide(verification_id, consent.entry_id, key_id)
    await owner.execute("ALTER TABLE verifications DISABLE TRIGGER verifications_freeze")
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await owner.execute(
                "UPDATE verifications SET status = 'not_approved' WHERE verification_id = $1",
                uuid.UUID(verification_id),
            )
    finally:
        await owner.execute("ALTER TABLE verifications ENABLE TRIGGER verifications_freeze")


async def test_closing_a_record_drops_its_overall_draft_too(archive, owner, verifications):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    await verifications.start(TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW)
    await verifications.save_draft(TENANT, "rita", row.verification_id, _ENVELOPE, [], NOW)
    assert await owner.fetchval("SELECT overall_note FROM verifications") is not None

    await verifications.decline(TENANT, "rita", row.verification_id, NOW)

    assert await owner.fetchval("SELECT overall_note FROM verifications") is None


async def test_an_old_record_does_not_open_beside_a_newer_open_one(archive, owner, verifications):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    await verifications.decline(TENANT, "rita", row.verification_id, NOW)
    newer = await verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)
    assert not isinstance(newer, Refused)

    old = await verifications.open_review(TENANT, "rita", row.verification_id, NOW, reviewer=True)
    current = await verifications.open_review(
        TENANT, "rita", newer.verification_id, NOW, reviewer=True
    )

    assert old is None and current is not None


async def test_a_decision_after_a_resnapshot_is_refused(archive, owner, verifications):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    signed_over = await verifications.start(
        TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW
    )
    await verifications.start(TENANT, "rita", row.verification_id, head["seq"], SWORN, NOW)

    refused = await verifications.decide(
        TENANT, "rita", row.verification_id, _decision(signed_over, "approved", None, []), NOW
    )

    assert refused == Refused("permissions_changed")
    assert await owner.fetchval("SELECT status FROM verifications") == "in_review"


async def test_a_review_write_after_a_shred_answers_closed(archive, owner, verifications):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    await owner.execute(
        "UPDATE conversations SET shredded_at = $2 WHERE conversation_id = $1", uuid.UUID(cid), NOW
    )
    assert await verifications.start(
        TENANT, "rita", row.verification_id, 1, SNAPSHOT, NOW
    ) == Refused("verification_closed")


async def test_a_closed_record_reaches_no_object_even_with_its_wrap_left(
    archive, owner, verifications, access
):
    """The reviewer branch needs an open assignment, not just a wrap (an unswept one here)."""
    cid, key_id, row = await _assigned(archive, owner, verifications)
    await owner.execute(
        "UPDATE verifications SET status = 'declined', closed_at = $2, close_reason = 'declined'"
        " WHERE verification_id = $1",
        uuid.UUID(row.verification_id),
        NOW,
    )
    consent = await owner.fetchval(
        "SELECT entry_id FROM chain_entries WHERE conversation_id = $1", uuid.UUID(cid)
    )
    args = (TENANT, "rita", cid, str(consent), "record.json", NOW)
    assert await access.object_location(*args, reviewer=True) is None
    assert not await access.openable(TENANT, "rita", cid, NOW, reviewer=True)


async def test_an_old_record_cannot_be_written_beside_a_newer_open_one(
    archive, owner, verifications
):
    cid, key_id, row = await _assigned(archive, owner, verifications)
    await verifications.decline(TENANT, "rita", row.verification_id, NOW)
    newer = await verifications.assign(_assignment(cid, [key_id]), NOW, supervisor=False)
    assert not isinstance(newer, Refused)
    assert await verifications.decline(TENANT, "rita", row.verification_id, NOW) == Refused(
        "verification_closed"
    )
    assert await verifications.save_draft(
        TENANT, "rita", row.verification_id, None, [], NOW
    ) == Refused("verification_closed")


async def test_an_expired_request_no_longer_excludes_its_requester(archive, owner, verifications):
    """Review finding 2: a lapsed request stays 'open' until the next retention pass."""
    conversation, key_id, _ = await _ended(archive, owner)
    cid = conversation.conversation_id
    await _key(owner, "alice")
    await _recovered(owner, conversation, key_id, requester="olga", status="open")
    await owner.execute("DELETE FROM key_wraps WHERE recipient_ref = 'olga'")
    assert await verifications.excluded(TENANT, cid, ["olga"], NOW) == {"olga"}
    await owner.execute(
        "UPDATE recovery_requests SET expires_at = $1 WHERE requester_sub = 'olga'",
        NOW - timedelta(minutes=1),
    )
    assert await verifications.excluded(TENANT, cid, ["olga"], NOW) == frozenset()


async def test_a_reviewer_can_decline_a_record_whose_conversation_is_gone(
    archive, owner, verifications
):
    """Review finding 8: nothing else can be written, but the inbox can always be cleared."""
    cid, key_id, row = await _assigned(archive, owner, verifications)
    await owner.execute(
        "UPDATE conversations SET shredded_at = $2 WHERE conversation_id = $1", uuid.UUID(cid), NOW
    )
    assert await verifications.save_draft(
        TENANT, "rita", row.verification_id, None, [], NOW
    ) == Refused("verification_closed")
    assert await verifications.decline(TENANT, "rita", row.verification_id, NOW) is None
    assert await owner.fetchval("SELECT status FROM verifications") == "declined"
