"""Employee key recovery in Postgres (spec §9.6; migration 007)."""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import timedelta

import asyncpg
import pytest

from services.api_gateway.recording.archive_access_repository import PostgresArchiveAccess
from services.api_gateway.recording.archive_repository import NewKey
from services.api_gateway.recording.audit import AuditEvent, chain_is_intact
from services.api_gateway.recording.conversation_keys import (
    Recipient,
    new_conversation_key,
    wrap_key,
)
from services.api_gateway.recording.recovery_requests_model import (
    NewRequest,
    Refused,
    UnrecoverableKey,
)
from services.api_gateway.recording.recovery_requests_sql import USABLE_SHARES
from services.api_gateway.recording.reenrolment_repository import PostgresKeyReenrolment
from services.api_gateway.recording.repository import (
    PostgresRecordingRepository,
    UserKeyRecord,
    append_audit,
    append_audits,
)
from tests import recording_crypto_reference as ref
from tests.integration.test_recording_archive_access_database import _ended
from tests.integration.test_recording_archive_database import (  # noqa: F401 - fixtures
    _ARCHIVE_TABLES,
    GATEWAY,
    GATEWAY_ID,
    NOW,
    OWNER_DSN,
    OWNER_PASSWORD,
    RECOVERY,
    TENANT,
    _entry,
    _opened,
    archive,
    owner,
)
from tests.integration.test_recording_recovery_requests_database import (  # noqa: F401
    _always,
    _approval,
    _audit,
    _filed,
    _wrap,
    enrol,
    file_directly,
    recovery_key,
    requests,
)

pytestmark = pytest.mark.integration

DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
async def _fresh_keys(owner):
    """The archive fixture keeps user_keys; these tests retire and replace keys."""
    await owner.execute("DELETE FROM user_keys")
    yield
    await owner.execute(f"TRUNCATE {_ARCHIVE_TABLES}")
    await owner.execute("DELETE FROM user_keys")


async def unrecoverable_directly(owner, request_id, conversation_id: str, key_id: str):
    await owner.execute(
        "INSERT INTO recovery_unrecoverable_keys VALUES ($1, $2, $3, $4, 'wrap_damaged', $5)",
        TENANT,
        request_id,
        uuid.UUID(conversation_id),
        uuid.UUID(key_id),
        NOW,
    )


async def test_the_app_deletes_user_wraps_but_never_recovery_wraps(archive, owner):
    await _ended(archive, owner)
    await recovery_key(owner)
    async with archive._pool.acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
            users = await connection.execute("DELETE FROM key_wraps WHERE recipient_kind = 'user'")
            recoveries = await connection.execute(
                "DELETE FROM key_wraps WHERE recipient_kind = 'recovery'"
            )
        finally:
            await transaction.rollback()
    assert users == "DELETE 1"
    # The restrictive policy hides the row from the delete: nothing goes, nothing fails.
    assert recoveries == "DELETE 0"


async def test_a_request_may_be_a_key_recovery_and_nothing_else(archive, owner):
    conversation, key_id, _ = await _ended(archive, owner)
    request_id = await file_directly(owner, conversation.conversation_id, key_id)
    await owner.execute(
        "UPDATE recovery_requests SET kind = 'key_recovery' WHERE request_id = $1", request_id
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute("UPDATE recovery_requests SET kind = 'other'")


async def test_an_unrecoverable_key_for_a_shredded_conversation_is_refused(archive, owner):
    conversation, key_id, _ = await _ended(archive, owner)
    request_id = await file_directly(owner, conversation.conversation_id, key_id)
    await owner.execute("UPDATE conversations SET shredded_at = $1", NOW)
    with pytest.raises(asyncpg.RaiseError, match="conversation_shredded"):
        await unrecoverable_directly(owner, request_id, conversation.conversation_id, key_id)


async def test_unrecoverable_keys_are_tenant_isolated(owner):
    row = await owner.fetchrow(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
        " WHERE relname = 'recovery_unrecoverable_keys'"
    )
    assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True)


async def test_two_thousand_events_in_one_append_keep_the_chain_intact(archive, owner):
    events = [AuditEvent(TENANT, "alice", "key_wrap.deleted", str(i), NOW) for i in range(2000)]
    async with archive._pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
            await append_audit(connection, AuditEvent(TENANT, "alice", "first", "0", NOW))
            await append_audits(connection, events)

    rows = await PostgresRecordingRepository(archive._pool).audit_rows(TENANT)
    assert len(rows) == 2001 and chain_is_intact(rows)


async def _key_recovery(requests, owner, conversations, *, sub="alice"):
    recovery = await recovery_key(owner)
    await enrol(owner, sub)
    request = NewRequest(
        tenant_id=TENANT,
        request_id=str(uuid.uuid4()),
        kind="key_recovery",
        requester_sub=sub,
        requester_key_version=1,
        recovery_key_id=recovery,
        reason="Forgot my passphrase.",
        conversation_ids=tuple(c.conversation_id for c in conversations),
        signature=bytes(64),
        created_at=NOW,
    )
    return request, await requests.file(request, _always)


async def test_a_key_recovery_files_only_the_callers_own_conversations(archive, owner, requests):
    mine, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    theirs, _, _ = await _ended(archive, owner, employee="bob", wrapped=False)

    _, refused = await _key_recovery(requests, owner, [mine, theirs])

    assert refused == Refused("not_found")
    assert ("alice", "recording.archive.not_found", theirs.conversation_id) in await _audit(owner)
    assert await owner.fetchval("SELECT count(*) FROM recovery_requests") == 0


async def test_a_key_recovery_is_filed_with_its_kind(archive, owner, requests):
    mine, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)

    _, scope = await _key_recovery(requests, owner, [mine])

    assert len(scope) == 1
    assert await owner.fetchval("SELECT kind FROM recovery_requests") == "key_recovery"


async def test_a_second_open_key_recovery_is_refused(archive, owner, requests):
    first, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    second, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    await _key_recovery(requests, owner, [first])

    _, refused = await _key_recovery(requests, owner, [second])

    assert refused == Refused("request_exists")


async def test_own_candidates_are_the_newest_batch_and_count_the_rest(archive, owner, requests):
    older, _, _ = await _ended(archive, owner, employee="alice", wrapped=False, at=NOW - DAY)
    newer, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    await _ended(archive, owner, employee="alice")  # wrapped for her: not a candidate
    await _ended(archive, owner, employee="bob", wrapped=False)
    await owner.execute(
        "UPDATE conversations SET started_at = $1 WHERE conversation_id = $2",
        NOW - 2 * DAY,
        uuid.UUID(older.conversation_id),
    )
    recovery = await recovery_key(owner)

    batch, conversations, keys = await requests.own_candidates(TENANT, "alice", recovery, NOW)

    assert [c.conversation_id for c in batch] == [newer.conversation_id, older.conversation_id]
    assert (conversations, keys) == (0, 0)


async def test_an_access_request_without_supervise_is_forbidden_but_may_be_cancelled(
    archive, owner, requests
):
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])
    before = len(await _audit(owner))

    progress = await requests.progress(TENANT, "sam", request.request_id, NOW, may_supervise=False)

    assert progress == Refused("forbidden")
    assert len(await _audit(owner)) == before
    assert await requests.cancel(TENANT, "sam", request.request_id, NOW) is None


async def test_a_key_recovery_needs_no_supervise(archive, owner, requests):
    mine, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    request, _ = await _key_recovery(requests, owner, [mine])

    progress = await requests.progress(
        TENANT, "alice", request.request_id, NOW, may_supervise=False
    )

    assert progress.request.kind == "key_recovery"


async def test_filing_under_a_retired_key_is_refused(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    await enrol(owner, "sam")
    await owner.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'sam'", NOW)

    _, refused = await _filed(requests, owner, [conversation])

    assert refused == Refused("key_changed")


async def test_storing_under_a_retired_key_is_refused(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
    await owner.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'sam'", NOW)

    refused = await requests.store_wraps(
        TENANT,
        "sam",
        request.request_id,
        [_wrap(k) for k in scope],
        1,
        _always,
        NOW,
        may_supervise=True,
    )

    assert refused == Refused("key_changed")


async def test_a_store_waits_for_a_key_change_and_then_refuses(archive, owner, requests):
    """The re-enrolment race (review M1): the key row orders the two writers."""
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
    swapper = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = swapper.transaction()
        await transaction.start()
        await swapper.execute("SELECT 1 FROM user_keys WHERE user_sub = 'sam' FOR UPDATE")

        storing = asyncio.create_task(
            requests.store_wraps(
                TENANT,
                "sam",
                request.request_id,
                [_wrap(k) for k in scope],
                1,
                _always,
                NOW,
                may_supervise=True,
            )
        )
        await asyncio.sleep(0.3)
        assert not storing.done()
        await swapper.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'sam'", NOW)
        await transaction.commit()

        assert await storing == Refused("key_changed")
    finally:
        await swapper.close()


async def _store_with_lost(requests, request, scope, lost: dict[str, str]):
    return await requests.store_wraps(
        TENANT,
        "alice",
        request.request_id,
        [_wrap(k) for k in scope if k.key_id not in lost],
        1,
        _always,
        NOW,
        may_supervise=False,
        unrecoverable=[UnrecoverableKey(key_id, stage) for key_id, stage in lost.items()],
    )


async def test_a_damaged_wrap_is_recorded_with_the_others_and_never_offered_again(
    archive, owner, requests
):
    first, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    second, bad_key, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    request, scope = await _key_recovery(requests, owner, [first, second])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)

    dropped = await _store_with_lost(requests, request, scope, {bad_key: "wrap_damaged"})
    recovery = await recovery_key(owner)
    batch, _, _ = await requests.own_candidates(TENANT, "alice", recovery, NOW)

    assert dropped == ()
    assert await owner.fetchval("SELECT status FROM recovery_requests") == "completed"
    assert batch == []  # `first` is open to her now; `second` is damaged for good
    events = [a[1:] for a in await _audit(owner)]
    assert ("recovery.integrity_failure.wrap_damaged", bad_key) in events
    assert events[-1] == ("recovery.request.completed", request.request_id)


async def test_a_damaged_conversation_cannot_be_filed_again(archive, owner, requests):
    first, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    second, bad_key, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    request, scope = await _key_recovery(requests, owner, [first, second])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
    await _store_with_lost(requests, request, scope, {bad_key: "wrap_damaged"})

    _, refused = await _key_recovery(requests, owner, [second])

    assert refused == Refused("not_found")


async def test_a_wrap_that_failed_its_signature_is_offered_again(archive, owner, requests):
    """Review point 1: a later transcript may certify the key that signed it."""
    conversation, bad_key, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    request, scope = await _key_recovery(requests, owner, [conversation])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)

    await _store_with_lost(requests, request, scope, {bad_key: "wrap_signature"})
    recovery = await recovery_key(owner)
    batch, _, _ = await requests.own_candidates(TENANT, "alice", recovery, NOW)

    assert await owner.fetchval("SELECT status FROM recovery_requests") == "completed"
    assert [c.conversation_id for c in batch] == [conversation.conversation_id]


async def test_a_refused_store_records_no_unrecoverable_key(archive, owner, requests):
    first, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    second, bad_key, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    request, scope = await _key_recovery(requests, owner, [first, second])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)

    refused = await requests.store_wraps(
        TENANT,
        "alice",
        request.request_id,
        [],
        1,
        _always,
        NOW,
        may_supervise=False,
        unrecoverable=[UnrecoverableKey(bad_key, "wrap_damaged")],
    )

    assert refused == Refused("scope_not_covered")
    assert await owner.fetchval("SELECT count(*) FROM recovery_unrecoverable_keys") == 0
    assert await owner.fetchval("SELECT status FROM recovery_requests") == "open"


async def test_a_lost_key_that_left_the_scope_needs_no_record(archive, owner, requests):
    first, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    second, gone_key, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    request, scope = await _key_recovery(requests, owner, [first, second])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
    await owner.execute(
        "UPDATE conversations SET shredded_at = $1 WHERE conversation_id = $2",
        NOW,
        uuid.UUID(second.conversation_id),
    )

    dropped = await _store_with_lost(requests, request, scope, {gone_key: "wrap_damaged"})

    assert dropped == ()
    assert await owner.fetchval("SELECT count(*) FROM recovery_unrecoverable_keys") == 0


async def test_a_custodian_whose_key_changed_is_stale(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])
    recovery = await recovery_key(owner)
    await owner.execute(
        "UPDATE user_keys SET fingerprint = $1 WHERE user_sub = 'carol'", b"\x09" * 32
    )

    listed = await requests.approvals(TENANT, "carol", recovery, NOW)
    stale = await requests.share_stale(TENANT, "carol", recovery)
    detail = await requests.approval_context(TENANT, "carol", request.request_id, NOW)
    declined = await requests.decline(TENANT, "carol", request.request_id, "no", NOW)
    approved = await requests.approve(
        TENANT, "carol", request.request_id, _approval(()), _always, NOW
    )

    assert listed == [] and stale is True
    assert detail == declined == approved == Refused("share_stale")
    assert await owner.fetchval("SELECT count(*) FROM recovery_decisions") == 0


async def test_a_custodian_without_an_active_key_is_stale_and_others_are_not(
    archive, owner, requests
):
    recovery = await recovery_key(owner)
    await owner.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'dave'", NOW)

    assert await requests.share_stale(TENANT, "dave", recovery) is True
    assert await requests.share_stale(TENANT, "carol", recovery) is False
    assert await requests.share_stale(TENANT, "erin", recovery) is False  # holds no share


async def test_the_requester_hears_cannot_approve_before_stale(archive, owner, requests):
    conversation, _, _ = await _ended(archive, owner)
    await recovery_key(owner)
    request, _ = await _filed(requests, owner, [conversation], sub="carol")
    await owner.execute(
        "UPDATE user_keys SET fingerprint = $1 WHERE user_sub = 'carol'", b"\x09" * 32
    )

    answer = await requests.approval_context(TENANT, "carol", request.request_id, NOW)

    assert answer == Refused("requester_cannot_approve")


async def test_usable_shares_count_fresh_custodians_only(archive, owner):
    await recovery_key(owner, k=2)
    await owner.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'dave'", NOW)
    async with archive._pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
            row = await connection.fetchrow(USABLE_SHARES)
    assert (row["k"], row["usable"]) == (2, 1)


def _new_key(sub="alice", version=2, at=NOW) -> UserKeyRecord:
    return UserKeyRecord(
        tenant_id=TENANT,
        user_sub=sub,
        key_version=version,
        enc_pub=ref.public_point(700),
        sig_pub=ref.public_point(701),
        fingerprint=b"\x07" * 32,
        encrypted_private=b"sealed",
        created_at=at,
    )


async def _reenrol(archive, sub="alice", *, replaces=1):
    return await PostgresKeyReenrolment(archive._pool).swap(
        _new_key(sub, replaces + 1), replaces, NOW
    )


async def test_the_swap_retires_the_key_and_deletes_its_wraps_and_requests(
    archive, owner, requests
):
    _, wrapped_key, _ = await _ended(archive, owner, employee="alice")
    locked, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    await enrol(owner, "alice")
    await owner.execute("UPDATE user_keys SET encrypted_private = 'x' WHERE user_sub = 'alice'")
    request, scope = await _key_recovery(requests, owner, [locked])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)

    assert await _reenrol(archive) is None

    keys = await owner.fetch(
        "SELECT key_version, retired_at, encrypted_private FROM user_keys"
        " WHERE user_sub = 'alice' ORDER BY key_version"
    )
    assert (keys[0]["retired_at"], keys[0]["encrypted_private"]) == (NOW, None)
    assert (keys[1]["key_version"], keys[1]["retired_at"]) == (2, None)
    assert (
        await owner.fetchval(
            "SELECT count(*) FROM key_wraps WHERE recipient_kind = 'user' AND recipient_ref = 'alice'"
        )
        == 0
    )
    assert (
        await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_kind = 'recovery'")
        == 2
    )
    assert await owner.fetchval("SELECT status FROM recovery_requests") == "cancelled"
    assert await owner.fetchval("SELECT count(*) FROM recovery_partials") == 0
    events = [a[1:] for a in await _audit(owner)]
    assert ("recovery.request.cancelled", request.request_id) in events
    assert ("key_wrap.deleted", wrapped_key) in events
    assert events[-1] == ("key_reenrolled", "user-key:2")
    rows = await PostgresRecordingRepository(archive._pool).audit_rows(TENANT)
    assert chain_is_intact(rows)


async def test_another_users_wraps_and_requests_are_untouched(archive, owner, requests):
    await _ended(archive, owner, employee="bob")
    theirs, _, _ = await _ended(archive, owner, employee="bob", wrapped=False)
    await _key_recovery(requests, owner, [theirs], sub="bob")
    await enrol(owner, "alice")

    assert await _reenrol(archive) is None

    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'bob'") == 1
    assert await owner.fetchval("SELECT status FROM recovery_requests") == "open"


async def test_a_stale_replaces_version_or_no_key_changes_nothing(archive, owner):
    assert await _reenrol(archive) == Refused("key_not_enrolled")
    await enrol(owner, "alice")
    assert await _reenrol(archive, replaces=2) == Refused("key_changed")
    assert await owner.fetchval("SELECT count(*) FROM user_keys WHERE user_sub = 'alice'") == 1


async def test_a_custodian_keeps_the_retired_blob_and_the_staleness_is_audited(archive, owner):
    recovery = await recovery_key(owner)
    await owner.execute("UPDATE user_keys SET encrypted_private = 'x' WHERE user_sub = 'carol'")

    assert await _reenrol(archive, "carol") is None

    assert (
        await owner.fetchval(
            "SELECT encrypted_private FROM user_keys WHERE user_sub = 'carol' AND key_version = 1"
        )
        == b"x"
    )
    assert ("recovery.share.stale", recovery) in [a[1:] for a in await _audit(owner)]


async def test_a_participant_of_a_running_ceremony_cannot_re_enrol(archive, owner):
    await enrol(owner, "alice")
    ceremony = uuid.uuid4()
    await owner.execute(
        "INSERT INTO recovery_ceremonies (tenant_id, ceremony_id, k, started_by, started_at,"
        " expires_at, status, gateway_keys) VALUES ($1, $2, 1, 'admin', $3, $4, 'dealing', '[]')",
        TENANT,
        ceremony,
        NOW,
        NOW + timedelta(hours=24),
    )
    try:
        await owner.execute(
            "INSERT INTO ceremony_participants (tenant_id, ceremony_id, holder_index, holder_ref,"
            " kind, enc_pub, sig_pub, fingerprint)"
            " VALUES ($1, $2, 1, 'alice', 'custodian', $3, $4, $5)",
            TENANT,
            ceremony,
            ref.public_point(1),
            ref.public_point(2),
            bytes(32),
        )
        assert await _reenrol(archive) == Refused("ceremony_in_progress")
    finally:
        await owner.execute("DELETE FROM ceremony_participants WHERE ceremony_id = $1", ceremony)
        await owner.execute("DELETE FROM recovery_ceremonies WHERE ceremony_id = $1", ceremony)


async def test_a_wraps_store_racing_the_swap_leaves_no_wrap_for_the_retired_key(
    archive, owner, requests
):
    """Review M1: the swap holds the key row; a store queued behind it is refused after it."""
    conversation, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    request, scope = await _key_recovery(requests, owner, [conversation])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM user_keys WHERE user_sub = 'alice' FOR UPDATE")
        storing = asyncio.create_task(
            requests.store_wraps(
                TENANT,
                "alice",
                request.request_id,
                [_wrap(k) for k in scope],
                1,
                _always,
                NOW,
                may_supervise=False,
            )
        )
        swapping = asyncio.create_task(_reenrol(archive))
        await asyncio.sleep(0.3)
        assert not storing.done() and not swapping.done()
        await transaction.rollback()
        results = await asyncio.gather(storing, swapping)
    finally:
        await holder.close()

    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_kind = 'user'") == 0
    assert results[1] is None


async def test_the_impact_names_a_custodian_and_the_shares_left_after(archive, owner):
    await recovery_key(owner, k=2)
    await enrol(owner, "alice")
    store = PostgresKeyReenrolment(archive._pool)

    carol = await store.impact(TENANT, "carol")
    alice = await store.impact(TENANT, "alice")

    assert (carol.custodian, carol.k, carol.usable_after) == (True, 2, 1)
    # The share count is for custodians and admins only (§9.6).
    assert (alice.custodian, alice.k, alice.usable_after) == (False, None, None)


async def _second_epoch_for(archive, fingerprint_: bytes, *, unnamed: bool = False):
    """A conversation armed before a key change, whose next key is first stored after it."""
    conversation, key_id, window_id, consent = await _opened(archive)
    key = new_conversation_key(2)
    alice = Recipient("user", "alice", ref.public_point(405), fingerprint_)
    wraps = tuple(
        wrap_key(
            key,
            recipient,
            tenant_id=TENANT,
            conversation_id=conversation.conversation_id,
            signing_key=GATEWAY,
            signer_key_id=GATEWAY_ID,
        )
        for recipient in (RECOVERY, alice)
    )
    if unnamed:
        wraps = (wraps[0], dataclasses.replace(wraps[1], recipient_fingerprint=None))
    entry = _entry(conversation, 2, consent.hash, key.key_id, window_id=window_id)
    await archive.append_entry(entry, NewKey(key.key_id, 2, NOW, wraps))


async def _user_wraps(owner) -> int:
    return await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_kind = 'user'")


async def test_a_user_wrap_for_the_active_key_is_stored(archive, owner):
    await enrol(owner, "alice")
    await _second_epoch_for(archive, bytes(32))
    assert await _user_wraps(owner) == 1


async def test_a_user_wrap_for_a_retired_or_missing_key_is_skipped(archive, owner):
    await _second_epoch_for(archive, bytes(32))  # no key at all
    await enrol(owner, "alice")
    await owner.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'alice'", NOW)
    await _second_epoch_for(archive, bytes(32))  # re-enrolled since the wrap was made

    assert await _user_wraps(owner) == 0
    assert (
        await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_kind = 'recovery'")
        == 4
    )


async def test_a_user_wrap_sealed_to_a_replaced_key_is_skipped_at_insert(archive, owner):
    """Review M2: re-enrolled, so the active key's fingerprint is not the wrap's."""
    await enrol(owner, "alice")
    await owner.execute(
        "UPDATE user_keys SET fingerprint = $1 WHERE user_sub = 'alice'", b"\x07" * 32
    )

    await _second_epoch_for(archive, bytes(32))

    assert await _user_wraps(owner) == 0


async def test_employee_key_recovery_restores_access_to_all_their_conversations(
    archive, owner, requests
):
    """The acceptance criterion of #617: enrol, record, re-enrol, recover, open (§9.6)."""
    await enrol(owner, "alice")
    first, _, _ = await _ended(archive, owner, employee="alice")
    second, _, _ = await _ended(archive, owner, employee="alice")
    access = PostgresArchiveAccess(archive._pool)

    async def listed() -> set[str]:
        rows = await access.own_conversations(
            TENANT, "alice", NOW, limit=50, started_before=None, before_id=None
        )
        return {row.conversation_id for row in rows}

    assert await listed() == {first.conversation_id, second.conversation_id}
    assert await _reenrol(archive) is None
    assert await listed() == set()

    recovery = await recovery_key(owner)
    batch, _, _ = await requests.own_candidates(TENANT, "alice", recovery, NOW)
    request = NewRequest(
        tenant_id=TENANT,
        request_id=str(uuid.uuid4()),
        kind="key_recovery",
        requester_sub="alice",
        requester_key_version=2,
        recovery_key_id=recovery,
        reason="Forgot my passphrase.",
        conversation_ids=tuple(c.conversation_id for c in batch),
        signature=bytes(64),
        created_at=NOW,
    )
    scope = await requests.file(request, _always)
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
    served = await requests.partials(TENANT, "alice", request.request_id, NOW, may_supervise=False)
    dropped = await requests.store_wraps(
        TENANT,
        "alice",
        request.request_id,
        [_wrap(k) for k in scope],
        2,
        _always,
        NOW,
        may_supervise=False,
    )

    assert len(served.wraps) == 2 and dropped == ()
    assert await listed() == {first.conversation_id, second.conversation_id}


async def test_a_second_concurrent_re_enrolment_hears_the_key_changed(archive, owner):
    await enrol(owner, "alice")
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM user_keys WHERE user_sub = 'alice' FOR UPDATE")
        first = asyncio.create_task(_reenrol(archive))
        await asyncio.sleep(0.2)
        second = asyncio.create_task(
            PostgresKeyReenrolment(archive._pool).swap(
                UserKeyRecord(
                    TENANT,
                    "alice",
                    2,
                    ref.public_point(800),
                    ref.public_point(801),
                    b"\x08" * 32,
                    b"sealed",
                    NOW,
                ),
                1,
                NOW,
            )
        )
        await asyncio.sleep(0.2)
        await transaction.rollback()
        answers = await asyncio.gather(first, second)
    finally:
        await holder.close()

    assert answers == [None, Refused("key_changed")]


async def test_filing_queued_behind_a_swap_files_nothing_under_the_retired_key(
    archive, owner, requests
):
    """Review minor 13: filing reads the key shared, so it waits for the swap and refuses."""
    mine, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    await recovery_key(owner)
    await enrol(owner, "alice")
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM user_keys WHERE user_sub = 'alice' FOR UPDATE")
        filing = asyncio.create_task(_key_recovery(requests, owner, [mine]))
        await asyncio.sleep(0.3)
        await holder.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'alice'", NOW)
        await transaction.commit()
        _, answer = await filing
    finally:
        await holder.close()

    assert answer == Refused("key_changed")
    assert await owner.fetchval("SELECT count(*) FROM recovery_requests") == 0


async def test_the_swap_waits_for_a_shred_holding_one_of_its_conversations(archive, owner):
    """Review minor 1: conversations are locked in order before the swap deletes anything."""
    conversation, _, _ = await _ended(archive, owner, employee="alice")
    await enrol(owner, "alice")
    shredder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = shredder.transaction()
        await transaction.start()
        await shredder.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR UPDATE",
            uuid.UUID(conversation.conversation_id),
        )
        swapping = asyncio.create_task(_reenrol(archive))
        await asyncio.sleep(0.3)
        assert not swapping.done()
        await transaction.rollback()
        assert await swapping is None
    finally:
        await shredder.close()


async def test_a_swap_closes_a_lapsed_request_as_expired(archive, owner, requests):
    mine, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    request, _ = await _key_recovery(requests, owner, [mine])
    await owner.execute("UPDATE recovery_requests SET expires_at = $1", NOW - DAY)

    assert await _reenrol(archive) is None

    assert await owner.fetchval("SELECT status FROM recovery_requests") == "expired"
    assert ("system", "recovery.request.expired", request.request_id) in await _audit(owner)


async def test_a_lapsed_access_request_read_without_supervise_changes_nothing(
    archive, owner, requests
):
    """Review minor 6: the permission check comes before the lapse closes anything."""
    conversation, _, _ = await _ended(archive, owner)
    request, _ = await _filed(requests, owner, [conversation])
    await owner.execute("UPDATE recovery_requests SET expires_at = $1", NOW - DAY)
    before = len(await _audit(owner))

    answer = await requests.progress(TENANT, "sam", request.request_id, NOW, may_supervise=False)

    assert answer == Refused("forbidden")
    assert await owner.fetchval("SELECT status FROM recovery_requests") == "open"
    assert len(await _audit(owner)) == before


async def test_a_user_wrap_that_names_no_key_is_refused_not_skipped(archive, owner):
    """Review point 8: a wrap the gateway cannot check against the active key is a bug."""
    await enrol(owner, "alice")
    with pytest.raises(ValueError, match="must name the key"):
        await _second_epoch_for(archive, bytes(32), unnamed=True)
