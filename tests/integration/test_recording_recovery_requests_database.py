"""Recovery requests against a real PostgreSQL (spec §9.5; migration 006).

Same environment as test_recording_archive_database.py.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import asyncpg
import pytest

from services.api_gateway.recording.recovery_requests_model import (
    Approval,
    NewRequest,
    NewWrap,
    Refused,
    ScopeKey,
)
from services.api_gateway.recording.recovery_requests_repository import (
    PostgresRecoveryRequests,
)
from tests import recording_crypto_reference as ref
from tests.integration.test_recording_archive_access_database import _ended
from tests.integration.test_recording_archive_database import (  # noqa: F401 - fixtures
    NOW,
    TENANT,
    archive,
    owner,
)

pytestmark = pytest.mark.integration

TABLES = (
    "recovery_requests",
    "recovery_request_keys",
    "recovery_decisions",
    "recovery_partials",
    "recovery_rejections",
)


async def recovery_key(owner, *, custodians=("carol", "dave"), k=1) -> str:
    """The tenant's active recovery key, made once, with threshold `k`; recovery wraps point at it."""
    key_id = await owner.fetchval(
        "SELECT key_id FROM recovery_keys WHERE tenant_id = $1 AND status = 'active'", TENANT
    )
    if key_id is None:
        key_id = uuid.uuid4()
        await owner.execute(
            "INSERT INTO recovery_ceremonies (tenant_id, ceremony_id, k, started_by, started_at,"
            " expires_at, status, gateway_keys, transcript_hash, closed_at)"
            " VALUES ($1, $2, $3, 'admin', $4, $5, 'active', '[]', $6, $4)",
            TENANT,
            key_id,
            k,
            NOW,
            NOW + timedelta(hours=24),
            bytes(32),
        )
        for index, sub in enumerate(custodians, start=1):
            await owner.execute(
                "INSERT INTO ceremony_participants (tenant_id, ceremony_id, holder_index,"
                " holder_ref, kind, enc_pub, sig_pub, fingerprint)"
                " VALUES ($1, $2, $3, $4, 'custodian', $5, $6, $7)",
                TENANT,
                key_id,
                index,
                sub,
                ref.public_point(100 + index),
                ref.public_point(200 + index),
                bytes([index]) * 32,
            )
        await owner.execute(
            "INSERT INTO recovery_keys (tenant_id, key_id, recovery_public_key, k, n, mode,"
            " transcript_hash, canary_wrap, canary_signature, canary_signer_key_id, status,"
            " activated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, '{}', $8, 'gw', 'active', $9)",
            TENANT,
            key_id,
            ref.public_point(31),
            k,
            len(custodians),
            "standard" if k == 1 else "enhanced",
            bytes(32),
            bytes(64),
            NOW,
        )
        for index, sub in enumerate(custodians, start=1):
            await owner.execute(
                "INSERT INTO recovery_shares (tenant_id, key_id, holder_index, holder_ref,"
                " holder_public_share, encrypted_share) VALUES ($1, $2, $3, $4, $5, '{}')",
                TENANT,
                key_id,
                index,
                sub,
                ref.public_point(300 + index),
            )
    await owner.execute("UPDATE recovery_keys SET k = $2 WHERE key_id = $1", key_id, k)
    await owner.execute(
        "UPDATE key_wraps SET recipient_ref = $1 WHERE recipient_kind = 'recovery'", str(key_id)
    )
    return str(key_id)


async def enrol(owner, sub: str) -> int:
    await owner.execute(
        "INSERT INTO user_keys (tenant_id, user_sub, key_version, enc_pub, sig_pub,"
        " fingerprint, created_at) VALUES ($1, $2, 1, $3, $4, $5, $6)"
        " ON CONFLICT DO NOTHING",
        TENANT,
        sub,
        ref.public_point(400 + len(sub)),
        ref.public_point(500 + len(sub)),
        bytes(32),
        NOW,
    )
    return 1


async def file_directly(owner, conversation_id: str, key_id: str, *, requester="sam"):
    """A request row and its one scope key, as the owner: no signature is checked here."""
    request_id = uuid.uuid4()
    recovery = await recovery_key(owner)
    version = await enrol(owner, requester)
    await owner.execute(
        "INSERT INTO recovery_requests (tenant_id, request_id, kind, requester_sub,"
        " requester_key_version, recovery_key_id, reason, request_signature, status,"
        " created_at, expires_at) VALUES ($1, $2, 'access', $3, $4, $5, 'why', $6, 'open',"
        " $7, $8)",
        TENANT,
        request_id,
        requester,
        version,
        uuid.UUID(recovery),
        bytes(64),
        NOW,
        NOW + timedelta(days=7),
    )
    await owner.execute(
        "INSERT INTO recovery_request_keys VALUES ($1, $2, $3, $4)",
        TENANT,
        request_id,
        uuid.UUID(conversation_id),
        uuid.UUID(key_id),
    )
    return request_id


async def partial_directly(owner, request_id, conversation_id, key_id, *, holder=1, attempt=1):
    await owner.execute(
        "INSERT INTO recovery_decisions (tenant_id, request_id, holder_index, attempt,"
        " custodian_sub, decision, signed_partials, approval_signature, decided_at)"
        " VALUES ($1, $2, $3, $4, 'carol', 'approved', '[]', $5, $6)"
        " ON CONFLICT DO NOTHING",
        TENANT,
        request_id,
        holder,
        attempt,
        bytes(64),
        NOW,
    )
    await owner.execute(
        "INSERT INTO recovery_partials VALUES ($1, $2, $3, $4, $5, $6, '{}')",
        TENANT,
        request_id,
        holder,
        attempt,
        uuid.UUID(conversation_id),
        uuid.UUID(key_id),
    )


async def test_every_table_is_tenant_isolated(owner):
    rows = await owner.fetch(
        "SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity"
        " AND relname = ANY($1::text[])",
        list(TABLES),
    )
    assert {row["relname"] for row in rows} == set(TABLES)


async def test_the_app_may_not_rewrite_a_decision_or_a_scope(owner):
    privileges = {
        (row["table_name"], row["privilege_type"])
        for row in await owner.fetch(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants"
            " WHERE grantee = 'ssf_recording_app' AND table_name = ANY($1::text[])",
            list(TABLES),
        )
    }
    for table in ("recovery_request_keys", "recovery_decisions", "recovery_rejections"):
        assert (table, "UPDATE") not in privileges
        assert (table, "DELETE") not in privileges
    assert ("recovery_partials", "DELETE") in privileges
    assert ("recovery_requests", "DELETE") not in privileges


async def test_only_status_and_closing_time_of_a_request_may_change(owner):
    columns = {
        row["column_name"]
        for row in await owner.fetch(
            "SELECT column_name FROM information_schema.column_privileges"
            " WHERE grantee = 'ssf_recording_app' AND table_name = 'recovery_requests'"
            " AND privilege_type = 'UPDATE'"
        )
    }
    assert columns == {"status", "closed_at"}


async def test_a_partial_for_a_shredded_conversation_is_refused(archive, owner):
    conversation, key_id, _ = await _ended(archive, owner)
    request_id = await file_directly(owner, conversation.conversation_id, key_id)
    await owner.execute(
        "UPDATE conversations SET shredded_at = $1 WHERE conversation_id = $2",
        NOW,
        uuid.UUID(conversation.conversation_id),
    )
    with pytest.raises(asyncpg.RaiseError, match="conversation_shredded"):
        await partial_directly(owner, request_id, conversation.conversation_id, key_id)


@pytest.fixture
async def requests(archive):
    return PostgresRecoveryRequests(archive._pool)


def _always(*_args) -> bool:
    return True


def _never(*_args) -> bool:
    return False


async def _filed(requests, owner, conversations, *, sub="sam", verify=_always, at=NOW):
    recovery = await recovery_key(owner)
    await enrol(owner, sub)
    request = NewRequest(
        tenant_id=TENANT,
        request_id=str(uuid.uuid4()),
        requester_sub=sub,
        requester_key_version=1,
        recovery_key_id=recovery,
        reason="Employee left.",
        conversation_ids=tuple(c.conversation_id for c in conversations),
        signature=bytes(64),
        created_at=at,
    )
    return request, await requests.file(request, verify)


async def _audit(owner) -> list[tuple[str, str, str]]:
    rows = await owner.fetch(
        "SELECT actor_sub, event_type, object_ref FROM audit_events ORDER BY seq"
    )
    return [(r["actor_sub"], r["event_type"], r["object_ref"]) for r in rows]


def _approval(scope) -> Approval:
    return Approval({key.key_id: "{}" for key in scope}, bytes(64))


async def test_filing_writes_the_scope_and_its_audit_together(archive, owner, requests):
    conversation, key_id, _ = await _ended(archive, owner)

    request, scope = await _filed(requests, owner, [conversation])

    assert scope == (ScopeKey(conversation.conversation_id, key_id),)
    assert await owner.fetchval("SELECT count(*) FROM recovery_request_keys") == 1
    assert (await _audit(owner))[-1] == ("sam", "recovery.request.filed", request.request_id)


async def test_filing_refuses_and_audits_each_unrecoverable_conversation(archive, owner, requests):
    live, _, _ = await _ended(archive, owner, at=None)
    unknown = type(live)(**{**live.__dict__, "conversation_id": str(uuid.uuid4())})

    _, refused = await _filed(requests, owner, [live, unknown])

    assert refused == Refused("not_found")
    refusals = [a for a in await _audit(owner) if a[1] == "recording.archive.not_found"]
    assert refusals == [
        ("sam", "recording.archive.not_found", live.conversation_id),
        ("sam", "recording.archive.not_found", unknown.conversation_id),
    ]
    assert await owner.fetchval("SELECT count(*) FROM recovery_requests") == 0


async def test_filing_refuses_a_conversation_already_open_to_the_requester(
    archive, owner, requests
):
    own, _, _ = await _ended(archive, owner, employee="sam")
    _, refused = await _filed(requests, owner, [own])
    assert refused == Refused("already_accessible")


async def test_a_second_open_request_for_a_conversation_is_refused(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    await _filed(requests, owner, [conversation])
    _, refused = await _filed(requests, owner, [conversation])
    assert refused == Refused("request_exists")


async def test_a_bad_signature_files_nothing(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    _, refused = await _filed(requests, owner, [conversation], verify=_never)
    assert refused == Refused("signature_invalid")
    assert await owner.fetchval("SELECT count(*) FROM recovery_requests") == 0


async def test_the_requester_is_refused_as_approver_and_it_is_audited(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])
    await _make_custodian(owner, "sam", 3)

    refused = await requests.approval_context(TENANT, "sam", request.request_id, NOW)

    assert refused == Refused("requester_cannot_approve")
    assert (await _audit(owner))[-1] == ("sam", "recovery.approval.refused", request.request_id)


async def test_an_approval_context_names_the_holder_and_the_signed_scope(archive, owner, requests):
    conversation, key_id, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])

    context = await requests.approval_context(TENANT, "dave", request.request_id, NOW)

    assert (context.holder_index, context.attempt) == (2, 1)
    assert context.signed_scope == scope
    assert [key.key_id for key in context.remaining] == [key_id]
    assert context.remaining[0].employee_sub == "alice"
    assert context.requester_enc_pub == ref.public_point(400 + len("sam"))


async def test_someone_holding_no_share_is_not_found(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])
    assert await requests.approval_context(TENANT, "erin", request.request_id, NOW) == Refused(
        "not_found"
    )


async def test_an_approval_stores_its_partials_and_counts_once(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])

    first = await requests.approve(
        TENANT, "carol", request.request_id, _approval(scope), _always, NOW
    )
    second = await requests.approve(
        TENANT, "carol", request.request_id, _approval(scope), _always, NOW
    )

    assert (first, second) == (None, Refused("already_decided"))
    assert await owner.fetchval("SELECT count(*) FROM recovery_partials") == 1
    assert (await _audit(owner))[-1] == ("carol", "recovery.request.approved", request.request_id)


async def test_an_approval_short_of_the_scope_or_badly_signed_writes_nothing(
    archive, owner, requests
):
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    short = Approval({}, bytes(64))

    assert await requests.approve(
        TENANT, "carol", request.request_id, short, _always, NOW
    ) == Refused("scope_not_covered")
    assert await requests.approve(
        TENANT, "carol", request.request_id, _approval(scope), _never, NOW
    ) == Refused("signature_invalid")
    assert await owner.fetchval("SELECT count(*) FROM recovery_decisions") == 0


async def test_after_a_rejection_the_custodian_may_approve_again(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)

    rejected = await requests.reject(
        TENANT, "sam", request.request_id, (1, 1), "proof_invalid", NOW
    )
    context = await requests.approval_context(TENANT, "carol", request.request_id, NOW)

    assert rejected is None
    assert context.attempt == 2
    assert await owner.fetchval("SELECT count(*) FROM recovery_partials") == 0
    assert (await _audit(owner))[-1][1:] == (
        "recovery.partial.rejected",
        f"{request.request_id}:1:1",
    )


async def test_partials_are_served_only_with_k_valid_approvals(archive, owner, requests):
    conversation, key_id, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    await recovery_key(owner, k=2)
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)

    assert await requests.partials(TENANT, "sam", request.request_id, NOW) == Refused(
        "not_enough_approvals"
    )
    await requests.approve(TENANT, "dave", request.request_id, _approval(scope), _always, NOW)
    served = await requests.partials(TENANT, "sam", request.request_id, NOW)

    assert [w.key_id for w in served.wraps] == [key_id]
    assert [(a.holder_index, a.attempt) for a in served.approvals] == [(1, 1), (2, 1)]
    assert served.approvals[0].blobs == {key_id: "{}"}
    assert (await _audit(owner))[-1] == ("sam", "recovery.partials.served", request.request_id)


async def test_another_custodians_partials_are_never_served_to_them(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
    assert await requests.partials(TENANT, "carol", request.request_id, NOW) == Refused("not_found")


async def test_an_expired_request_closes_once_under_the_system_actor(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
    later = NOW + timedelta(days=7)

    first = await requests.progress(TENANT, "sam", request.request_id, later)
    second = await requests.progress(TENANT, "sam", request.request_id, later)

    assert (first.request.status, second.request.status) == ("expired", "expired")
    assert await owner.fetchval("SELECT count(*) FROM recovery_partials") == 0
    expiries = [a for a in await _audit(owner) if a[1] == "recovery.request.expired"]
    assert expiries == [("system", "recovery.request.expired", request.request_id)]


async def test_a_list_shows_a_lapsed_request_as_expired(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    await _filed(requests, owner, [conversation])
    [(row, conversations)] = await requests.own_requests(TENANT, "sam", NOW + timedelta(days=8))
    assert (row.status, conversations) == ("expired", 1)


async def test_a_request_whose_conversations_are_all_shredded_closes_as_scope_gone(
    archive, owner, requests
):
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])
    await owner.execute("UPDATE conversations SET shredded_at = $1", NOW)

    progress = await requests.progress(TENANT, "sam", request.request_id, NOW)

    assert progress.request.status == "scope_gone"
    assert (await _audit(owner))[-1] == (
        "system",
        "recovery.request.scope_gone",
        request.request_id,
    )


async def test_the_approvals_list_holds_what_a_custodian_may_still_decide(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    recovery = await recovery_key(owner)

    before = await requests.approvals(TENANT, "carol", recovery, NOW)
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
    after = await requests.approvals(TENANT, "carol", recovery, NOW)
    await requests.reject(TENANT, "sam", request.request_id, (1, 1), "proof_invalid", NOW)
    again = await requests.approvals(TENANT, "carol", recovery, NOW)

    assert [r.request_id for r, _ in before] == [request.request_id]
    assert after == []
    assert [r.request_id for r, _ in again] == [request.request_id]
    assert await requests.approvals(TENANT, "sam", recovery, NOW) == []


def _wrap(key: ScopeKey) -> NewWrap:
    return NewWrap(key.conversation_id, key.key_id, "{}", bytes(64))


async def test_storing_wraps_completes_the_request_atomically(archive, owner, requests):
    conversation, key_id, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)

    dropped = await requests.store_wraps(
        TENANT, "sam", request.request_id, [_wrap(k) for k in scope], 1, _always, NOW
    )

    assert dropped == ()
    wrap = await owner.fetchrow(
        "SELECT creator_ref FROM key_wraps WHERE recipient_kind = 'user' AND recipient_ref = 'sam'"
    )
    assert wrap["creator_ref"] == "sam"
    assert await owner.fetchval("SELECT status FROM recovery_requests") == "completed"
    assert await owner.fetchval("SELECT count(*) FROM recovery_partials") == 0
    assert [a[1:] for a in (await _audit(owner))[-2:]] == [
        ("recovery.wrap.stored", key_id),
        ("recovery.request.completed", request.request_id),
    ]


async def test_storing_wraps_short_of_the_scope_or_badly_signed_stores_nothing(
    archive, owner, requests
):
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])

    short = await requests.store_wraps(TENANT, "sam", request.request_id, [], 1, _always, NOW)
    unsigned = await requests.store_wraps(
        TENANT, "sam", request.request_id, [_wrap(k) for k in scope], 1, _never, NOW
    )
    newer_key = await requests.store_wraps(
        TENANT, "sam", request.request_id, [_wrap(k) for k in scope], 2, _always, NOW
    )

    assert (short, unsigned, newer_key) == (
        Refused("scope_not_covered"),
        Refused("signature_invalid"),
        Refused("signature_invalid"),
    )
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'sam'") == 0


async def test_storing_waits_for_a_shred_in_progress_and_then_drops_its_key(
    archive, owner, requests
):
    first, first_key, _ = await _ended(archive, owner)
    second, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [first, second])
    shred = owner.transaction()
    await shred.start()
    await owner.execute(
        "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR UPDATE",
        uuid.UUID(first.conversation_id),
    )
    storing = asyncio.create_task(
        requests.store_wraps(
            TENANT, "sam", request.request_id, [_wrap(k) for k in scope], 1, _always, NOW
        )
    )
    await asyncio.sleep(0.5)
    waited = not storing.done()
    await owner.execute(
        "UPDATE conversations SET shredded_at = $1 WHERE conversation_id = $2",
        NOW,
        uuid.UUID(first.conversation_id),
    )
    await shred.commit()
    dropped = await storing

    assert waited
    assert dropped == (first_key,)


async def test_cancelling_closes_the_request_and_nothing_more_is_accepted(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])

    assert await requests.cancel(TENANT, "sam", request.request_id, NOW) is None
    assert await requests.cancel(TENANT, "sam", request.request_id, NOW) == Refused("closed")
    assert await requests.approve(
        TENANT, "carol", request.request_id, _approval(scope), _always, NOW
    ) == Refused("closed")


async def test_an_integrity_report_is_audited_for_the_requester_only(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])

    assert (
        await requests.record_integrity_failure(TENANT, "sam", request.request_id, "trust", NOW)
        is None
    )
    assert await requests.record_integrity_failure(
        TENANT, "carol", request.request_id, "trust", NOW
    ) == Refused("not_found")
    assert ("sam", "recovery.integrity_failure.trust", request.request_id) in await _audit(owner)


async def test_a_request_of_another_tenant_is_not_found(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])
    assert await requests.progress("tenant-b", "sam", request.request_id, NOW) == Refused(
        "not_found"
    )


async def test_the_employees_and_candidates_cover_leavers_and_skip_the_requested(
    archive, owner, requests
):
    first, first_key, _ = await _ended(archive, owner)
    second, _, _ = await _ended(archive, owner, employee="bob")
    recovery = await recovery_key(owner)
    await enrol(owner, "sam")

    employees = await requests.employees(TENANT)
    candidates = await requests.candidates(
        TENANT, "sam", "alice", recovery, NOW - timedelta(days=1), NOW + timedelta(days=1), NOW
    )

    assert employees == ["alice", "bob"]
    assert [(c.conversation_id, c.key_ids) for c in candidates] == [
        (first.conversation_id, (first_key,))
    ]
    assert second.conversation_id not in {c.conversation_id for c in candidates}


async def _make_custodian(owner, sub: str, index: int) -> None:
    key_id = uuid.UUID(await recovery_key(owner))
    await owner.execute(
        "INSERT INTO ceremony_participants (tenant_id, ceremony_id, holder_index, holder_ref,"
        " kind, enc_pub, sig_pub, fingerprint) VALUES ($1, $2, $3, $4, 'custodian', $5, $6, $7)"
        " ON CONFLICT DO NOTHING",
        TENANT,
        key_id,
        index,
        sub,
        ref.public_point(100 + index),
        ref.public_point(200 + index),
        bytes([index]) * 32,
    )
    await owner.execute(
        "INSERT INTO recovery_shares (tenant_id, key_id, holder_index, holder_ref,"
        " holder_public_share, encrypted_share) VALUES ($1, $2, $3, $4, $5, '{}')"
        " ON CONFLICT DO NOTHING",
        TENANT,
        key_id,
        index,
        sub,
        ref.public_point(300 + index),
    )


async def test_a_reused_request_id_files_nothing_more(archive, owner, requests):
    first, _, _ = await _ended(archive, owner)
    second, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [first])
    reused = type(request)(**{**request.__dict__, "conversation_ids": (second.conversation_id,)})

    assert await requests.file(reused, _always) == Refused("request_exists")
    assert await owner.fetchval("SELECT count(*) FROM recovery_request_keys") == 1


async def test_wraps_for_part_of_the_scope_store_nothing(archive, owner, requests):
    first, _, _ = await _ended(archive, owner)
    second, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [first, second])

    partial = await requests.store_wraps(
        TENANT, "sam", request.request_id, [_wrap(scope[0])], 1, _always, NOW
    )

    assert partial == Refused("scope_not_covered")
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'sam'") == 0
    assert await owner.fetchval("SELECT status FROM recovery_requests") == "open"


async def test_filing_closes_a_lapsed_request_and_its_partials_first(archive, owner, requests):
    """Two requests' partials for one R must never sit side by side (§9.5)."""
    conversation, _, _ = await _ended(archive, owner)
    lapsed, scope = await _filed(requests, owner, [conversation])
    await requests.approve(TENANT, "carol", lapsed.request_id, _approval(scope), _always, NOW)
    later = NOW + timedelta(days=8)

    request, refiled = await _filed(requests, owner, [conversation], at=later)

    assert refiled == scope
    statuses = {
        str(r["request_id"]): r["status"]
        for r in await owner.fetch("SELECT request_id, status FROM recovery_requests")
    }
    assert statuses == {lapsed.request_id: "expired", request.request_id: "open"}
    assert await owner.fetchval("SELECT count(*) FROM recovery_partials") == 0


async def test_candidates_leave_out_conversations_already_requested(archive, owner, requests):
    first, _, _ = await _ended(archive, owner)
    second, _, _ = await _ended(archive, owner)
    _, _ = await _filed(requests, owner, [first])
    recovery = await recovery_key(owner)

    candidates = await requests.candidates(
        TENANT, "sam", "alice", recovery, NOW - timedelta(days=1), NOW + timedelta(days=1), NOW
    )

    assert [c.conversation_id for c in candidates] == [second.conversation_id]


async def test_the_requester_without_a_share_is_still_told_they_cannot_approve(
    archive, owner, requests
):
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])
    assert await requests.decline(TENANT, "sam", request.request_id, "no", NOW) == Refused(
        "requester_cannot_approve"
    )


async def test_an_integrity_report_after_closing_is_refused(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])
    await requests.cancel(TENANT, "sam", request.request_id, NOW)
    assert await requests.record_integrity_failure(
        TENANT, "sam", request.request_id, "trust", NOW
    ) == Refused("closed")


async def test_a_wrap_verified_wrong_halfway_stores_none(archive, owner, requests):
    first, _, _ = await _ended(archive, owner)
    second, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [first, second])
    seen: list[str] = []

    def second_fails(wrap) -> bool:
        seen.append(wrap.key_id)
        return len(seen) < 2

    refused = await requests.store_wraps(
        TENANT, "sam", request.request_id, [_wrap(k) for k in scope], 1, second_fails, NOW
    )

    assert refused == Refused("signature_invalid")
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'sam'") == 0


async def test_a_wrap_already_held_is_kept_and_not_audited_again(archive, owner, requests):
    conversation, key_id, _ = await _ended(archive, owner)
    second_key = await _second_key(owner, conversation)
    request, scope = await _filed(requests, owner, [conversation])
    await owner.execute(
        "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
        " creator_ref, creator_signature, granted_at) VALUES ($1, $2, 'user', 'sam', 'held',"
        " 'sam', $3, $4)",
        TENANT,
        uuid.UUID(second_key),
        bytes(64),
        NOW,
    )

    await requests.store_wraps(
        TENANT, "sam", request.request_id, [_wrap(k) for k in scope], 1, _always, NOW
    )

    held = await owner.fetchval(
        "SELECT blob FROM key_wraps WHERE recipient_ref = 'sam' AND key_id = $1",
        uuid.UUID(second_key),
    )
    stored = [a for a in await _audit(owner) if a[1] == "recovery.wrap.stored"]
    assert held == "held"
    assert stored == [("sam", "recovery.wrap.stored", key_id)]


async def _second_key(owner, conversation) -> str:
    """A second key epoch, wrapped for recovery like the first."""
    key_id = uuid.uuid4()
    await owner.execute(
        "INSERT INTO conversation_keys (tenant_id, key_id, conversation_id, epoch, created_at)"
        " VALUES ($1, $2, $3, 2, $4)",
        TENANT,
        key_id,
        uuid.UUID(conversation.conversation_id),
        NOW,
    )
    await owner.execute(
        "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
        " creator_ref, creator_signature, granted_at) VALUES ($1, $2, 'recovery', 'rk', '{}',"
        " 'gw', $3, $4)",
        TENANT,
        key_id,
        bytes(64),
        NOW,
    )
    return str(key_id)
