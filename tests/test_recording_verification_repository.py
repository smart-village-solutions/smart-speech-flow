"""PostgresVerifications' own logic over a scripted connection: rows to records, refusals.

What the SQL selects is proven against a real PostgreSQL in
tests/integration/test_recording_verification_database.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import asyncpg
import pytest

from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.verification_model import AssignWrap, NewAssignment
from services.api_gateway.recording.verification_repository import PostgresVerifications
from tests.test_recording_archive_access_repository import ScriptedConnection, ScriptedPool

TENANT = "tenant-a"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
CONVERSATION = str(uuid.uuid4())
VERIFICATION = str(uuid.uuid4())
KEY_1, KEY_2 = sorted(str(uuid.uuid4()) for _ in range(2))


def repository(answers: dict[str, object]) -> tuple[PostgresVerifications, ScriptedConnection]:
    connection = ScriptedConnection(answers)
    return PostgresVerifications(ScriptedPool(connection)), connection


def audits(connection: ScriptedConnection) -> int:
    return sum("INSERT INTO audit_events" in call for call in connection.calls)


def key_row(sub: str, version: int = 1) -> dict:
    return {
        "user_sub": sub,
        "key_version": version,
        "fingerprint": bytes([version]) * 32,
        "enc_pub": b"\x04" + bytes(64),
        "sig_pub": b"\x04" + bytes([1]) * 64,
    }


def verification_row(**changes) -> dict:
    row = {
        "verification_id": uuid.UUID(VERIFICATION),
        "conversation_id": uuid.UUID(CONVERSATION),
        "status": "awaiting",
        "requested_by": "alice",
        "requester_key_version": 1,
        "requested_at": NOW,
        "directory_read_at": NOW,
        "reviewer_sub": "rita",
        "reviewer_key_version": 1,
        "reviewer_fingerprint": bytes([1]) * 32,
        "started_at": None,
        "reviewed_head_seq": None,
        "reviewed_head": None,
        "permission_snapshot": None,
        "outcome": None,
        "overall_note": None,
        "notes_digest": None,
        "signature": None,
        "signer_key_version": None,
        "decided_at": None,
        "closed_at": None,
        "close_reason": None,
        "tsa_token": None,
    }
    row.update(changes)
    return row


def assignment(*keys: str, reviewer_version: int = 1) -> NewAssignment:
    return NewAssignment(
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        requester_sub="alice",
        requester_key_version=1,
        reviewer_sub="rita",
        reviewer_key_version=reviewer_version,
        reviewer_fingerprint=bytes([1]) * 32,
        directory_read_at=NOW,
        wraps=tuple(AssignWrap(key, "{}", bytes(64)) for key in keys),
    )


def assignable(**changes) -> dict[str, object]:
    answers: dict[str, object] = {
        "FOR SHARE": [key_row("alice"), key_row("rita")],
        "FOR UPDATE": {"conversation_id": uuid.UUID(CONVERSATION)},
        "c.employee_sub = $2": False,
        "FROM conversation_keys WHERE": [
            {"key_id": uuid.UUID(KEY_1)},
            {"key_id": uuid.UUID(KEY_2)},
        ],
        "INSERT INTO verifications": verification_row(),
    }
    answers.update(changes)
    return answers


async def test_an_assignment_inserts_the_record_the_wraps_and_its_audits():
    repo, connection = repository(assignable())

    row = await repo.assign(assignment(KEY_2, KEY_1), NOW, supervisor=False)

    assert not isinstance(row, Refused)
    assert (row.verification_id, row.ref) == (VERIFICATION, f"{VERIFICATION}:rita")
    assert any("INSERT INTO key_wraps" in call for call in connection.calls)
    assert audits(connection) == 3  # requested and one grant per key


@pytest.mark.parametrize(
    ("changes", "version", "code"),
    [
        ({"FOR SHARE": [key_row("rita")]}, 1, "key_changed"),
        ({}, 2, "reviewer_key_changed"),
        ({"FOR UPDATE": None}, 1, "not_found"),
        ({"c.employee_sub = $2": True}, 1, "reviewer_not_eligible"),
        ({"FROM conversation_keys WHERE": [{"key_id": uuid.UUID(KEY_1)}]}, 1, "scope_not_covered"),
        (
            {"INSERT INTO verifications": asyncpg.UniqueViolationError("one open")},
            1,
            "assignment_exists",
        ),
    ],
)
async def test_an_assignment_is_refused_with_its_reason(changes, version, code):
    repo, connection = repository(assignable(**changes))

    refused = await repo.assign(
        assignment(KEY_1, KEY_2, reviewer_version=version), NOW, supervisor=False
    )

    assert refused == Refused(code)
    assert audits(connection) == 0
    assert not any("INSERT INTO key_wraps" in call for call in connection.calls)


async def test_candidate_reads_map_their_rows():
    repo, _ = repository(
        {
            "unnest($2::text[])": [{"sub": "alice"}, {"sub": "sam"}],
            "FROM user_keys": [key_row("rita", 3)],
            "FROM conversation_keys WHERE": [{"key_id": uuid.UUID(KEY_1)}],
        }
    )
    assert await repo.excluded(TENANT, CONVERSATION, ["alice", "sam", "rita"]) == {"alice", "sam"}
    keys = await repo.active_keys(TENANT, ["rita"])
    assert keys["rita"].key_version == 3 and keys["rita"].fingerprint == bytes([3]) * 32
    assert await repo.conversation_keys(TENANT, CONVERSATION) == (KEY_1,)


async def test_a_database_that_cannot_answer_is_storage_unavailable():
    repo = PostgresVerifications(ScriptedPool(None))
    with pytest.raises(RecordingStorageUnavailable):
        await repo.conversation_keys(TENANT, CONVERSATION)


async def test_the_inbox_reads_rows_and_an_open_shredded_one_is_not_openable():
    rows = [
        {
            "verification_id": uuid.UUID(VERIFICATION),
            "status": "awaiting",
            "requested_at": NOW,
            "requested_by": "alice",
            "started_at": NOW,
            "ended_at": None,
            "messages": 3,
            "openable": False,
        }
    ]
    repo, _ = repository({"ORDER BY (v.status IN": rows})
    [row] = await repo.inbox(TENANT, "rita", NOW)
    assert (row.verification_id, row.messages, row.openable) == (VERIFICATION, 3, False)


async def test_a_refused_review_open_reads_nothing_and_is_audited():
    repo, connection = repository({})
    assert await repo.open_review(TENANT, "rita", VERIFICATION, NOW, reviewer=True) is None
    assert audits(connection) == 1
    assert not any("FROM chain_entries" in call for call in connection.calls)


async def test_a_review_open_carries_the_record_its_draft_and_the_requester():
    conversation = {
        "conversation_id": uuid.UUID(CONVERSATION),
        "employee_sub": "alice",
        "legal_basis": "consent",
        "started_at": NOW,
        "ended_at": NOW,
        "retention_until": NOW,
        "legal_hold": False,
        "incomplete": False,
    }
    repo, connection = repository(
        {
            "row_to_json(c.*)": verification_row(status="in_review", overall_note=b"\x01o"),
            "SELECT c.* FROM conversations c": conversation,
            "FROM verification_notes": [
                {"entry_id": uuid.UUID(KEY_1), "key_id": uuid.UUID(KEY_2), "ciphertext": b"\x01n"}
            ],
            "AND key_version = $2": key_row("alice"),
        }
    )

    opened = await repo.open_review(TENANT, "rita", VERIFICATION, NOW, reviewer=True)

    assert opened is not None and opened.record.status == "in_review"
    assert [(n.entry_id, n.ciphertext) for n in opened.draft] == [(KEY_1, b"\x01n")]
    assert opened.requester.sub == "alice" and opened.conversation.conversation_id == CONVERSATION
    assert audits(connection) == 1


def _locked(status="in_review", reviewing=True, **changes) -> dict[str, object]:
    answers: dict[str, object] = {
        "AND reviewer_sub = $2": uuid.UUID(CONVERSATION),
        "FOR SHARE": None,
        "FOR UPDATE": verification_row(
            status=status,
            reviewed_head_seq=2,
            reviewed_head=b"\x05" * 32,
            permission_snapshot=["ssf.recording.review"],
        ),
        "AS still_reviewing": reviewing,
    }
    answers.update(changes)
    return answers


@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ({"AND reviewer_sub = $2": None}, "verification_not_found"),
        (_locked(status="declined"), "verification_closed"),
        (_locked(reviewing=False), "verification_closed"),
    ],
)
async def test_review_writes_are_refused_before_any_write(answers, code):
    repo, connection = repository(answers if "FOR UPDATE" in answers else _locked(**answers))
    assert await repo.decline(TENANT, "rita", VERIFICATION, NOW) == Refused(code)
    assert not any(call.startswith(("UPDATE", "DELETE", "INSERT")) for call in connection.calls)


async def test_starting_from_awaiting_checks_the_head_and_audits():
    head = {"seq": 2, "hash": b"\x05" * 32}
    started = verification_row(status="in_review", reviewed_head_seq=2, reviewed_head=b"\x05" * 32)
    repo, connection = repository(
        _locked(status="awaiting")
        | {"ORDER BY seq DESC": head, "SET status = 'in_review'": started}
    )
    assert await repo.start(TENANT, "rita", VERIFICATION, 3, ["r"], NOW) == Refused("head_changed")
    row = await repo.start(TENANT, "rita", VERIFICATION, 2, ["r"], NOW)
    assert row.reviewed_head == b"\x05" * 32 and audits(connection) == 1


async def test_starting_again_only_resnapshots():
    repo, connection = repository(
        _locked()
        | {
            "SET permission_snapshot": verification_row(
                status="in_review", permission_snapshot=["a", "b"]
            )
        }
    )
    row = await repo.start(TENANT, "rita", VERIFICATION, 99, ["a", "b"], NOW)
    assert row.permission_snapshot == ("a", "b") and audits(connection) == 0


async def test_a_draft_is_checked_against_the_chain_and_replaces_the_saved_set():
    from services.api_gateway.recording.verification_model import NotePost

    entries = [
        {"entry_id": uuid.UUID(KEY_1), "key_id": uuid.UUID(KEY_2), "seq": 1},
        {"entry_id": uuid.UUID(KEY_2), "key_id": uuid.UUID(KEY_2), "seq": 3},
    ]
    repo, connection = repository(_locked() | {"SELECT entry_id, key_id, seq": entries})
    good = NotePost(KEY_1, KEY_2, b"\x01n")
    assert await repo.save_draft(
        TENANT, "rita", VERIFICATION, None, [NotePost(KEY_2, KEY_2, b"\x01")], NOW
    ) == Refused("bad_notes")
    assert await repo.save_draft(
        TENANT, "rita", VERIFICATION, None, [NotePost(KEY_1, KEY_1, b"\x01")], NOW
    ) == Refused("bad_notes")
    assert await repo.save_draft(TENANT, "rita", VERIFICATION, b"\x01o", [good], NOW) is None
    assert any("INSERT INTO verification_notes" in call for call in connection.calls)
    assert audits(connection) == 0
    waiting, _ = repository(_locked(status="awaiting"))
    assert await waiting.save_draft(TENANT, "rita", VERIFICATION, None, [], NOW) == Refused(
        "not_started"
    )


async def test_a_decline_closes_releases_and_audits():
    repo, connection = repository(
        _locked() | {"RETURNING w.key_id": [{"key_id": uuid.UUID(KEY_1)}]}
    )
    assert await repo.decline(TENANT, "rita", VERIFICATION, NOW) is None
    assert audits(connection) == 2
    assert connection.calls.index(
        next(c for c in connection.calls if c.startswith("DELETE FROM verification_notes"))
    ) < connection.calls.index(
        next(c for c in connection.calls if c.startswith("UPDATE verifications SET status"))
    )


def _deciding(**changes) -> dict[str, object]:
    return (
        {
            "AND retired_at IS NULL FOR SHARE": {"key_version": 1, "fingerprint": bytes([1]) * 32},
            "SELECT entry_id, key_id, seq": [],
            "RETURNING *": verification_row(status="approved", outcome="approved"),
            "RETURNING w.key_id": [{"key_id": uuid.UUID(KEY_1)}],
        }
        | _locked()
        | changes
    )


def _post(**changes):
    from services.api_gateway.recording.verification_model import DecisionPost

    values = dict(
        outcome="approved",
        overall=None,
        notes=(),
        signature=bytes(64),
        notes_digest=bytes(32),
        signed_digest=b"\xab" * 32,
        signer_key_version=1,
        signer_fingerprint=bytes([1]) * 32,
        snapshot=("ssf.recording.review",),
        reviewed_head=b"\x05" * 32,
    )
    values.update(changes)
    return DecisionPost(**values)


async def test_a_decision_writes_notes_freezes_releases_and_audits_with_its_digest():
    repo, connection = repository(_deciding())
    row = await repo.decide(TENANT, "rita", VERIFICATION, _post(), NOW)
    assert row.outcome == "approved" and audits(connection) == 2
    assert any("INSERT INTO verification_notes" in call for call in connection.calls)


async def test_a_decision_is_refused_for_a_changed_key_a_waiting_record_or_bad_notes():
    from services.api_gateway.recording.verification_model import NotePost

    other_key, _ = repository(_deciding(**{"AND retired_at IS NULL FOR SHARE": None}))
    assert await other_key.decide(TENANT, "rita", VERIFICATION, _post(), NOW) == Refused(
        "key_changed"
    )
    waiting, _ = repository(_deciding() | _locked(status="awaiting"))
    assert await waiting.decide(TENANT, "rita", VERIFICATION, _post(), NOW) == Refused(
        "not_started"
    )
    bad, connection = repository(_deciding())
    post = _post(notes=(NotePost(KEY_1, KEY_2, b"\x01"),))
    assert await bad.decide(TENANT, "rita", VERIFICATION, post, NOW) == Refused("bad_notes")
    assert audits(connection) == 0
    gone, _ = repository({})
    assert await gone.record_of(TENANT, "rita", VERIFICATION) is None


async def test_the_decision_stamp_queue_reads_saves_and_defers():
    due_row = {
        "verification_id": uuid.UUID(VERIFICATION),
        "conversation_id": uuid.UUID(CONVERSATION),
        "reviewed_head": b"\x05" * 32,
        "outcome": "approved",
        "notes_digest": b"\x06" * 32,
        "permission_snapshot": ["ssf.recording.review"],
        "signature": b"\x07" * 64,
        "stamp_attempts": 1,
        "timestamp_authority_url": "https://tsa.test/tsr",
    }
    repo, connection = repository({"v.stamp_next_attempt_at <= $1": [due_row]})
    [due] = await repo.pending_decision_stamps(TENANT, NOW)
    await repo.save_decision_stamp(TENANT, due, b"t", NOW)
    await repo.defer_decision_stamp(TENANT, due, NOW)
    assert (due.attempts, due.url) == (1, "https://tsa.test/tsr")
    assert sum("tsa_token IS NULL" in call for call in connection.calls) == 3


async def test_read_records_serve_content_of_decided_records_only():
    from services.api_gateway.recording.archive_access_repository import read_records

    decided = verification_row(
        status="approved",
        outcome="approved",
        signer_key_version=1,
        overall_note=b"\x01o",
        verification_id=uuid.UUID(KEY_1),
    )
    drafting = verification_row(status="in_review", overall_note=b"\x01draft")
    connection = ScriptedConnection(
        {
            "FROM verification_notes n": [
                {
                    "verification_id": uuid.UUID(KEY_1),
                    "entry_id": uuid.UUID(KEY_2),
                    "key_id": uuid.UUID(KEY_2),
                    "ciphertext": b"\x01n",
                }
            ],
            "FROM user_keys u": [key_row("rita")],
            "FROM verifications WHERE conversation_id": [decided, drafting],
        }
    )

    first, second = await read_records(connection, uuid.UUID(CONVERSATION))

    assert first.row.overall_note == b"\x01o" and len(first.notes) == 1
    assert first.reviewer_key is not None and first.reviewer_key.sub == "rita"
    assert second.row.overall_note is None and second.notes == () and second.reviewer_key is None


async def test_a_decision_signed_over_another_snapshot_or_head_is_refused_under_the_lock():
    """A start from another tab may re-snapshot between the signature check and the write."""
    for change in (
        {"snapshot": ("ssf.recording.review", "ssf.recording.review.sworn")},
        {"reviewed_head": b"\x06" * 32},
    ):
        repo, connection = repository(_deciding())
        assert await repo.decide(TENANT, "rita", VERIFICATION, _post(**change), NOW) == Refused(
            "permissions_changed"
        )
        assert not any("INSERT INTO verification_notes" in call for call in connection.calls)
