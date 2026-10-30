"""PostgresRecoveryRequests' own logic over a scripted connection: rows to records, refusals.

What the SQL selects is proven against a real PostgreSQL in
tests/integration/test_recording_recovery_requests_database.py; this covers how
the repository reads the answers and which refusal each one leads to.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from services.api_gateway.recording.recovery_requests_model import (
    Approval,
    Candidate,
    NewRequest,
    NewWrap,
    Refused,
    ScopeKey,
)
from services.api_gateway.recording.recovery_requests_repository import (
    PostgresRecoveryRequests,
    batched,
)
from services.api_gateway.recording.recovery_requests_sql import signed_partials
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.retention.store import (
    PostgresRetentionStore,
    _forget_spent_requests,
)
from tests.test_recording_archive_access_repository import ScriptedConnection, ScriptedPool

TENANT = "tenant-a"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
REQUEST, RECOVERY = str(uuid.uuid4()), str(uuid.uuid4())
CONVERSATION, KEY = str(uuid.uuid4()), str(uuid.uuid4())
SCOPE = ({"conversation_id": uuid.UUID(CONVERSATION), "key_id": uuid.UUID(KEY)},)

LOCK = "FOR UPDATE"
REMAINING = "FOR SHARE OF c"
HOLDER = "FROM recovery_shares s"
LATEST = "ORDER BY d.attempt DESC LIMIT 1"
VALID = "ORDER BY d.holder_index, d.attempt"
K = "SELECT k FROM recovery_keys"


def _row(status="open", requester="sam", expires=NOW + timedelta(days=7)) -> dict:
    return {
        "request_id": uuid.UUID(REQUEST),
        "kind": "access",
        "requester_sub": requester,
        "requester_key_version": 1,
        "recovery_key_id": uuid.UUID(RECOVERY),
        "reason": "why",
        "request_signature": bytes(64),
        "status": status,
        "created_at": NOW,
        "expires_at": expires,
        "closed_at": None if status == "open" else NOW,
        "conversations": 1,
    }


HOLDER_ROW = {
    "holder_index": 1,
    "encrypted_share": "{}",
    "sig_pub": b"\x04" + bytes(64),
    "fresh": True,
}


class Scripted(ScriptedConnection):
    pass


# The requester's active key, version 1, unless a test scripts another answer.
REQUESTER_KEY = "retired_at IS NULL FOR SHARE"


def repository(answers: dict[str, object]):
    connection = Scripted({REQUESTER_KEY: 1, **answers})
    return PostgresRecoveryRequests(ScriptedPool(connection)), connection


def audited(connection: ScriptedConnection) -> list[str]:
    return [call for call in connection.calls if "INSERT INTO audit_events" in call]


def _new_request(conversations=(CONVERSATION,)) -> NewRequest:
    return NewRequest(
        TENANT, REQUEST, "access", "sam", 1, RECOVERY, "why", conversations, bytes(64), NOW
    )


def _check(recoverable=True, accessible=False, requested=False) -> dict:
    return {
        "conversation_id": uuid.UUID(CONVERSATION),
        "recoverable": recoverable,
        "accessible": accessible,
        "requested": requested,
    }


def _always(*_args) -> bool:
    return True


async def test_a_driver_failure_is_storage_unavailable():
    requests = PostgresRecoveryRequests(ScriptedPool(None))
    with pytest.raises(RecordingStorageUnavailable):
        await requests.employees(TENANT)


async def test_employees_and_candidates_read_their_rows():
    requests, _ = repository(
        {
            "DISTINCT employee_sub": [{"employee_sub": "alice"}],
            "AS key_ids": [
                {
                    "conversation_id": uuid.UUID(CONVERSATION),
                    "started_at": NOW,
                    "ended_at": NOW,
                    "retention_until": NOW,
                    "legal_hold": False,
                    "incomplete": True,
                    "key_ids": [KEY],
                }
            ],
        }
    )
    assert await requests.employees(TENANT) == ["alice"]
    [candidate] = await requests.candidates(TENANT, "sam", "alice", RECOVERY, NOW, NOW, NOW)
    assert (candidate.key_ids, candidate.incomplete) == ((KEY,), True)


@pytest.mark.parametrize(
    ("check", "refused"),
    [
        (_check(recoverable=False), "not_found"),
        (_check(accessible=True), "already_accessible"),
        (_check(requested=True), "request_exists"),
    ],
)
async def test_filing_refuses_by_the_check_it_fails(check, refused):
    requests, connection = repository({"AS requested": [check]})
    assert await requests.file(_new_request(), _always) == Refused(refused)
    assert len(audited(connection)) == (1 if refused == "not_found" else 0)


async def test_filing_audits_an_unknown_conversation_too():
    requests, connection = repository({"AS requested": []})
    assert await requests.file(_new_request(), _always) == Refused("not_found")
    assert len(audited(connection)) == 1


async def test_filing_with_a_bad_signature_writes_nothing():
    requests, connection = repository({"AS requested": [_check()], "FROM conversation_keys": SCOPE})
    assert await requests.file(_new_request(), lambda scope: False) == Refused("signature_invalid")
    assert not any("INSERT INTO recovery_requests" in call for call in connection.calls)


async def test_filing_writes_the_request_its_scope_and_its_audit():
    requests, connection = repository({"AS requested": [_check()], "FROM conversation_keys": SCOPE})
    assert await requests.file(_new_request(), _always) == (ScopeKey(CONVERSATION, KEY),)
    assert any("INSERT INTO recovery_request_keys" in call for call in connection.calls)
    assert len(audited(connection)) == 1


async def test_a_reused_request_id_reads_as_an_existing_request():
    requests, _ = repository(
        {
            "AS requested": [_check()],
            "FROM conversation_keys": SCOPE,
            "INSERT INTO recovery_requests": asyncpg.UniqueViolationError("duplicate key"),
        }
    )
    assert await requests.file(_new_request(), _always) == Refused("request_exists")


async def test_lists_report_a_lapsed_open_request_as_expired():
    lapsed = _row(expires=NOW - timedelta(seconds=1))
    requests, _ = repository({"r.requester_sub = $1": [lapsed], "JOIN recovery_shares": [_row()]})
    [(own, count)] = await requests.own_requests(TENANT, "sam", NOW)
    [(approvable, _)] = await requests.approvals(TENANT, "carol", RECOVERY, NOW)
    assert (own.status, own.closed_at, count) == ("expired", NOW, 1)
    assert approvable.status == "open"


async def test_an_unknown_request_is_not_found_and_audited():
    requests, connection = repository({})
    assert await requests.progress(TENANT, "sam", REQUEST, NOW, may_supervise=True) == Refused(
        "not_found"
    )
    assert len(audited(connection)) == 1


async def test_a_lapsed_request_closes_as_expired_under_the_system_actor():
    requests, connection = repository(
        {LOCK: _row(expires=NOW), K: 1, "FROM recovery_decisions d WHERE": []}
    )
    progress = await requests.progress(TENANT, "sam", REQUEST, NOW, may_supervise=True)
    assert progress.request.status == "expired"
    assert any("DELETE FROM recovery_partials" in call for call in connection.calls)


async def test_a_request_without_remaining_scope_closes_as_scope_gone():
    requests, _ = repository({LOCK: _row(), REMAINING: [], K: 1})
    progress = await requests.progress(TENANT, "sam", REQUEST, NOW, may_supervise=True)
    assert (progress.request.status, progress.remaining) == ("scope_gone", ())


@pytest.mark.parametrize(
    ("answers", "refused"),
    [
        ({LOCK: _row()}, "not_found"),
        (
            {LOCK: _row(requester="carol"), REMAINING: SCOPE, HOLDER: HOLDER_ROW},
            "requester_cannot_approve",
        ),
        ({LOCK: _row(status="cancelled"), HOLDER: HOLDER_ROW}, "closed"),
        (
            {
                LOCK: _row(),
                REMAINING: SCOPE,
                HOLDER: HOLDER_ROW,
                LATEST: {"attempt": 1, "decision": "declined", "rejected": False},
            },
            "already_decided",
        ),
        (
            {
                LOCK: _row(),
                REMAINING: SCOPE,
                HOLDER: HOLDER_ROW,
                LATEST: {"attempt": 1, "decision": "approved", "rejected": False},
            },
            "already_decided",
        ),
    ],
)
async def test_a_decision_is_refused_by_the_rule_it_breaks(answers, refused):
    requests, _ = repository(answers)
    assert await requests.decline(TENANT, "carol", REQUEST, "no", NOW) == Refused(refused)


async def test_an_approval_context_follows_a_rejected_approval_with_the_next_attempt():
    requests, _ = repository(
        {
            LOCK: _row(),
            REMAINING: SCOPE,
            HOLDER: HOLDER_ROW,
            LATEST: {"attempt": 1, "decision": "approved", "rejected": True},
            "FROM user_keys": {"enc_pub": b"e" * 65, "sig_pub": b"s" * 65},
            "FROM recovery_request_keys WHERE": SCOPE,
            "c.employee_sub, c.started_at": [
                {
                    "conversation_id": uuid.UUID(CONVERSATION),
                    "key_id": uuid.UUID(KEY),
                    "employee_sub": "alice",
                    "started_at": NOW,
                    "ended_at": NOW,
                    "blob": "{}",
                    "creator_ref": "gw",
                    "creator_signature": bytes(64),
                }
            ],
        }
    )
    context = await requests.approval_context(TENANT, "carol", REQUEST, NOW)
    assert (context.attempt, context.holder_index) == (2, 1)
    assert context.remaining[0].recovery_blob == "{}"


def _decidable(**extra) -> dict:
    return {LOCK: _row(), REMAINING: SCOPE, HOLDER: HOLDER_ROW, **extra}


async def test_an_approval_needs_a_valid_signature_and_the_whole_scope():
    requests, _ = repository(_decidable())
    full = Approval({KEY: "{}"}, bytes(64))
    assert await requests.approve(TENANT, "carol", REQUEST, full, lambda *a: False, NOW) == Refused(
        "signature_invalid"
    )
    short = Approval({}, bytes(64))
    assert await requests.approve(TENANT, "carol", REQUEST, short, _always, NOW) == Refused(
        "scope_not_covered"
    )


async def test_an_approval_records_the_signed_hashes_of_every_posted_partial():
    requests, connection = repository(_decidable())
    approval = Approval({KEY: "{}", "gone": "{}"}, bytes(64))
    assert await requests.approve(TENANT, "carol", REQUEST, approval, _always, NOW) is None
    assert any("INSERT INTO recovery_partials" in call for call in connection.calls)
    assert len(audited(connection)) == 1


async def test_a_decline_is_recorded():
    requests, connection = repository(_decidable())
    assert await requests.decline(TENANT, "carol", REQUEST, "no", NOW) is None
    assert len(audited(connection)) == 1


async def test_partials_need_an_open_request_and_k_valid_approvals():
    closed, _ = repository({LOCK: _row(status="completed")})
    assert await closed.partials(TENANT, "sam", REQUEST, NOW, may_supervise=True) == Refused(
        "closed"
    )
    short, _ = repository({LOCK: _row(), REMAINING: SCOPE, K: 2, VALID: [{"holder_index": 1}]})
    assert await short.partials(TENANT, "sam", REQUEST, NOW, may_supervise=True) == Refused(
        "not_enough_approvals"
    )


async def test_partials_are_served_grouped_by_decision():
    approval = {
        "holder_index": 1,
        "attempt": 1,
        "signed_partials": json.dumps([[KEY, "AA"]]),
        "approval_signature": bytes(64),
    }
    requests, connection = repository(
        {
            LOCK: _row(),
            REMAINING: SCOPE,
            K: 1,
            VALID: [approval],
            "FROM key_wraps w JOIN": [
                {
                    "conversation_id": uuid.UUID(CONVERSATION),
                    "key_id": uuid.UUID(KEY),
                    "blob": "{}",
                    "creator_ref": "gw",
                    "creator_signature": bytes(64),
                }
            ],
            "SELECT holder_index, attempt, key_id, blob": [
                {"holder_index": 1, "attempt": 1, "key_id": uuid.UUID(KEY), "blob": "{p}"}
            ],
        }
    )
    served = await requests.partials(TENANT, "sam", REQUEST, NOW, may_supervise=True)
    assert served.approvals[0].blobs == {KEY: "{p}"}
    assert served.approvals[0].signed_partials == ((KEY, b"\x00"),)
    assert served.wraps[0].key_id == KEY
    assert len(audited(connection)) == 1


@pytest.mark.parametrize(
    ("answers", "refused"),
    [
        ({LOCK: _row(status="cancelled")}, Refused("closed")),
        ({LOCK: _row(), REMAINING: SCOPE, "decision = 'approved'": False}, Refused("not_found")),
        ({LOCK: _row(), REMAINING: SCOPE, "decision = 'approved'": True}, None),
    ],
)
async def test_a_rejection_needs_an_open_request_and_an_approval(answers, refused):
    requests, _ = repository(answers)
    assert (
        await requests.reject(
            TENANT, "sam", REQUEST, (1, 1), "proof_invalid", NOW, may_supervise=True
        )
        == refused
    )


async def test_an_integrity_report_is_the_requesters_alone_while_open():
    mine, connection = repository({LOCK: _row(), REMAINING: SCOPE})
    assert (
        await mine.record_integrity_failure(
            TENANT, "sam", REQUEST, "trust", NOW, may_supervise=True
        )
        is None
    )
    assert len(audited(connection)) == 1
    theirs, _ = repository({LOCK: _row(), REMAINING: SCOPE})
    assert await theirs.record_integrity_failure(
        TENANT, "carol", REQUEST, "trust", NOW, may_supervise=True
    ) == Refused("not_found")
    closed, _ = repository({LOCK: _row(status="completed")})
    assert await closed.record_integrity_failure(
        TENANT, "sam", REQUEST, "trust", NOW, may_supervise=True
    ) == Refused("closed")


async def test_filing_closes_the_requesters_lapsed_requests_first():
    requests, connection = repository(
        {
            "expires_at <= $2 ORDER BY request_id FOR UPDATE": [{"request_id": uuid.UUID(REQUEST)}],
            "AS requested": [_check()],
            "FROM conversation_keys": SCOPE,
        }
    )
    await requests.file(_new_request(), _always)
    closing = [c for c in connection.calls if "SET status = $2" in c]
    assert len(closing) == 1
    assert any("DELETE FROM recovery_partials" in c for c in connection.calls)


async def test_a_wrap_already_held_is_not_audited_again():
    requests, connection = repository(
        {
            LOCK: _row(),
            REMAINING: SCOPE,
            K: 1,
            VALID: [{"holder_index": 1}],
            "RETURNING key_id": None,
        }
    )
    await requests.store_wraps(
        TENANT, "sam", REQUEST, [_wrap()], 1, _always, NOW, may_supervise=True
    )
    # Only the completion is audited, not a wrap that was not inserted.
    assert len(audited(connection)) == 1


async def test_settling_closes_lapsed_requests_and_forgets_spent_ones():
    connection = Scripted(
        {
            "expires_at <= $1 ORDER BY request_id": [{"request_id": uuid.UUID(REQUEST)}],
            "SELECT r.request_id": [],
        }
    )
    store = PostgresRetentionStore(ScriptedPool(connection), "primary")
    await store.settle_requests(TENANT, NOW)
    closing = [c for c in connection.calls if "SET status = $2" in c]
    assert len(closing) == 1
    assert any(c.startswith("DELETE FROM recovery_partials") for c in connection.calls)
    assert len(audited(connection)) == 1


def _wrap(key_id=KEY, conversation_id=CONVERSATION) -> NewWrap:
    return NewWrap(conversation_id, key_id, "{}", bytes(64))


@pytest.mark.parametrize(
    ("answers", "wraps", "version", "refused"),
    [
        ({LOCK: _row(status="expired")}, [_wrap()], 1, "closed"),
        ({LOCK: _row(), REMAINING: SCOPE}, [_wrap()], 2, "key_changed"),
        (
            {LOCK: _row(), REMAINING: SCOPE, K: 2, VALID: [{"holder_index": 1}]},
            [_wrap()],
            1,
            "not_enough_approvals",
        ),
        (
            {LOCK: _row(), REMAINING: SCOPE, K: 1, VALID: [{"holder_index": 1}]},
            [],
            1,
            "scope_not_covered",
        ),
        (
            {LOCK: _row(), REMAINING: SCOPE, K: 1, VALID: [{"holder_index": 1}]},
            [_wrap(conversation_id="other")],
            1,
            "signature_invalid",
        ),
    ],
)
async def test_wraps_are_refused_whole(answers, wraps, version, refused):
    requests, connection = repository(answers)
    assert await requests.store_wraps(
        TENANT, "sam", REQUEST, wraps, version, _always, NOW, may_supervise=True
    ) == Refused(refused)
    assert not any("INSERT INTO key_wraps" in call for call in connection.calls)


async def test_storing_wraps_completes_and_lists_the_dropped_keys():
    requests, connection = repository(
        {LOCK: _row(), REMAINING: SCOPE, K: 1, VALID: [{"holder_index": 1}]}
    )
    dropped = await requests.store_wraps(
        TENANT, "sam", REQUEST, [_wrap(), _wrap(key_id="gone")], 1, _always, NOW, may_supervise=True
    )
    assert dropped == ("gone",)
    assert any("SET status = $2" in call for call in connection.calls)


async def test_cancel_needs_an_open_request():
    open_, _ = repository({LOCK: _row(), REMAINING: SCOPE})
    assert await open_.cancel(TENANT, "sam", REQUEST, NOW) is None
    closed, _ = repository({LOCK: _row(status="cancelled")})
    assert await closed.cancel(TENANT, "sam", REQUEST, NOW) == Refused("closed")


def test_signed_partials_read_from_text_or_json_or_nothing():
    assert signed_partials(None) == ()
    assert signed_partials('[["k", "AA"]]') == (("k", b"\x00"),)
    assert signed_partials([["k", "AA"]]) == (("k", b"\x00"),)


async def test_spent_requests_go_with_their_history_and_an_audit_event():
    connection = Scripted({"SELECT r.request_id": [{"request_id": uuid.UUID(REQUEST)}]})
    await _forget_spent_requests(connection, TENANT, NOW)
    deletes = [call for call in connection.calls if call.startswith("DELETE FROM recovery_")]
    assert len(deletes) == 5
    assert len(audited(connection)) == 1


async def test_a_scope_larger_than_one_approval_can_carry_is_refused():
    keys = [
        {"conversation_id": uuid.UUID(CONVERSATION), "key_id": uuid.uuid4()} for _ in range(501)
    ]
    requests, connection = repository({"AS requested": [_check()], "FROM conversation_keys": keys})
    assert await requests.file(_new_request(), _always) == Refused("scope_too_large")
    assert not any("INSERT INTO recovery_requests" in call for call in connection.calls)


def _candidate(keys: int, cid: str | None = None) -> Candidate:
    return Candidate(
        cid or str(uuid.uuid4()), NOW, NOW, NOW, False, False, tuple(str(i) for i in range(keys))
    )


def test_a_batch_takes_whole_conversations_and_stops_at_the_first_that_does_not_fit():
    big, small, later = _candidate(1500), _candidate(600), _candidate(10)
    too_large = _candidate(2001)

    batch, conversations, keys = batched([big, small, later, too_large])

    assert batch == [big]
    assert (conversations, keys) == (2, 610)


def test_a_batch_may_fill_to_the_limit_exactly():
    batch, conversations, _ = batched([_candidate(1999), _candidate(1)])
    assert len(batch) == 2 and conversations == 0


async def test_own_candidates_read_the_callers_conversations():
    row = {
        "conversation_id": uuid.UUID(CONVERSATION),
        "started_at": NOW,
        "ended_at": NOW,
        "retention_until": NOW,
        "legal_hold": False,
        "incomplete": False,
        "key_ids": [KEY],
    }
    requests, _ = repository({"AS key_ids": [row]})
    batch, conversations, keys = await requests.own_candidates(TENANT, "alice", RECOVERY, NOW)
    assert [c.conversation_id for c in batch] == [CONVERSATION]
    assert (conversations, keys) == (0, 0)


async def test_filing_under_another_key_version_writes_nothing():
    requests, connection = repository({REQUESTER_KEY: 2})
    assert await requests.file(_new_request(), _always) == Refused("key_changed")
    assert not any("pg_advisory_xact_lock" in call for call in connection.calls)


async def test_more_access_conversations_than_allowed_are_refused_before_any_check():
    conversations = tuple(str(uuid.uuid4()) for _ in range(51))
    requests, connection = repository({})
    assert await requests.file(_new_request(conversations), _always) == Refused("scope_too_large")
    assert not any("AS requested" in call for call in connection.calls)


def _key_recovery(conversations=(CONVERSATION,)) -> NewRequest:
    return NewRequest(
        TENANT, REQUEST, "key_recovery", "alice", 1, RECOVERY, "why", conversations, bytes(64), NOW
    )


async def test_a_key_recovery_of_someone_elses_conversation_is_not_found_and_audited():
    check = {**_check(), "employee_sub": "bob"}
    requests, connection = repository({"AS requested": [check]})
    assert await requests.file(_key_recovery(), _always) == Refused("not_found")
    assert len(audited(connection)) == 1


async def test_a_key_recovery_of_her_own_conversation_files():
    check = {**_check(), "employee_sub": "alice"}
    requests, connection = repository({"AS requested": [check], "FROM conversation_keys": SCOPE})
    assert await requests.file(_key_recovery(), _always) == (ScopeKey(CONVERSATION, KEY),)
    assert any("INSERT INTO recovery_requests" in call for call in connection.calls)


async def test_a_second_open_key_recovery_is_refused_before_any_check():
    requests, connection = repository({"kind = 'key_recovery'": True})
    assert await requests.file(_key_recovery(), _always) == Refused("request_exists")
    assert not any("AS requested" in call for call in connection.calls)


async def test_an_access_request_without_supervise_is_forbidden_and_writes_nothing():
    requests, connection = repository({LOCK: _row(), REMAINING: SCOPE})
    refused = await requests.progress(TENANT, "sam", REQUEST, NOW, may_supervise=False)
    assert refused == Refused("forbidden")
    assert audited(connection) == []


async def test_partials_under_a_changed_key_are_refused():
    requests, _ = repository({REQUESTER_KEY: 2, LOCK: _row(), REMAINING: SCOPE})
    refused = await requests.partials(TENANT, "sam", REQUEST, NOW, may_supervise=True)
    assert refused == Refused("key_changed")


async def test_own_requests_may_be_narrowed_to_a_kind():
    requests, connection = repository({"r.requester_sub = $1": [{**_row(), "conversations": 1}]})
    [(row, count)] = await requests.own_requests(TENANT, "sam", NOW, "access")
    assert (row.request_id, count) == (REQUEST, 1)


REPORTED = "FROM recovery_unrecoverable_keys WHERE request_id"


async def test_a_reported_key_is_recorded_and_audited_by_its_key():
    requests, connection = repository({LOCK: _row(), REMAINING: SCOPE})
    reported = await requests.record_integrity_failure(
        TENANT, "sam", REQUEST, "wrap_damaged", NOW, may_supervise=True, key_id=KEY
    )
    assert reported is None
    assert any("INSERT INTO recovery_unrecoverable_keys" in call for call in connection.calls)
    assert len(audited(connection)) == 1


@pytest.mark.parametrize(
    ("stage", "key_id", "signed", "answer"),
    [
        ("partial_hash", KEY, False, Refused("bad_stage")),
        ("wrap_damaged", "other", False, Refused("not_found")),
        ("wrap_damaged", "other", True, None),
    ],
)
async def test_only_a_wrap_stage_for_a_key_in_scope_is_recorded(stage, key_id, signed, answer):
    requests, connection = repository(
        {LOCK: _row(), REMAINING: SCOPE, "FROM recovery_request_keys WHERE request_id = $1": signed}
    )
    result = await requests.record_integrity_failure(
        TENANT, "sam", REQUEST, stage, NOW, may_supervise=True, key_id=key_id
    )
    assert result == answer
    assert not any("INSERT INTO recovery_unrecoverable_keys" in call for call in connection.calls)


async def test_storing_needs_no_wrap_for_a_reported_key():
    requests, connection = repository(
        {
            REPORTED: [{"key_id": uuid.UUID(KEY)}],
            LOCK: _row(),
            REMAINING: SCOPE,
            K: 1,
            VALID: [{"holder_index": 1}],
        }
    )
    dropped = await requests.store_wraps(
        TENANT, "sam", REQUEST, [], 1, _always, NOW, may_supervise=True
    )
    assert dropped == ()
    assert any("SET status = $2" in call for call in connection.calls)


async def test_a_key_recovery_may_list_more_than_fifty_conversations():
    conversations = tuple(str(uuid.uuid4()) for _ in range(51))
    checks = [
        {**_check(), "conversation_id": uuid.UUID(c), "employee_sub": "alice"}
        for c in conversations
    ]
    requests, connection = repository({"AS requested": checks, "FROM conversation_keys": SCOPE})
    assert await requests.file(_key_recovery(conversations), _always) == (
        ScopeKey(CONVERSATION, KEY),
    )


@pytest.mark.parametrize(("keys", "answer"), [(2000, "filed"), (2001, "scope_too_large")])
async def test_a_key_recovery_carries_up_to_two_thousand_keys(keys, answer):
    scope = [
        {"conversation_id": uuid.UUID(CONVERSATION), "key_id": uuid.uuid4()} for _ in range(keys)
    ]
    check = {**_check(), "employee_sub": "alice"}
    requests, _ = repository({"AS requested": [check], "FROM conversation_keys": scope})
    result = await requests.file(_key_recovery(), _always)
    assert (result if isinstance(result, Refused) else Refused("filed")) == Refused(answer)
