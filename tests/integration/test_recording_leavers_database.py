"""Leavers in Postgres (spec §9.8; migration 009)."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import timedelta

import asyncpg
import pytest

from services.api_gateway.recording.audit import chain_is_intact
from services.api_gateway.recording.ceremony_repository import PostgresCeremonyRepository
from services.api_gateway.recording.leavers import MarkedLeaver
from services.api_gateway.recording.leavers_repository import PostgresLeavers
from services.api_gateway.recording.crypto import ecies, tags
from services.api_gateway.recording.crypto.curve import decode_point, encode_point, multiply
from services.api_gateway.recording.crypto.encoding import b64url, from_b64url
from services.api_gateway.recording.leavers import Leavers
from services.api_gateway.recording.recovery_requests_model import Approval, NewRequest, Refused
from services.api_gateway.recording.recovery_requests_repository import PostgresRecoveryRequests
from services.api_gateway.recording.recovery_requests_sql import USABLE_SHARES
from services.api_gateway.recording.repository import PostgresRecordingRepository
from services.api_gateway.recording.resharing_model import ResharingStart
from tests import recording_crypto_reference as ref
from tests.recording_ceremony_actors import ANNA, DORA, ORG_ADMIN, reshare_dealing
from tests.integration.test_recording_archive_access_database import _ended
from tests.integration.test_recording_archive_database import (  # noqa: F401 - fixtures
    NOW,
    OWNER_DSN,
    OWNER_PASSWORD,
    TENANT,
    archive,
    owner,
)
from tests.integration.test_recording_key_recovery_database import _key_recovery, _new_key, _reenrol
from tests.integration.test_recording_resharing_database import (  # noqa: F401 - fixtures
    _clean,
    _confirm_all,
    _file,
    _first_generation,
    _services,
    store,
)
from tests.integration.test_recording_recovery_requests_database import (  # noqa: F401
    _always,
    _approval,
    _audit,
    _filed,
    enrol,
    recovery_key,
    requests,
)

pytestmark = pytest.mark.integration

ADMIN = "admin-anna"


@pytest.fixture(autouse=True)
async def _fresh(owner):
    """The archive fixture keeps user_keys and ceremonies; these tests retire keys and reshare."""
    await _clean(owner)
    yield
    await _clean(owner)


@pytest.fixture
async def leavers(archive):
    return PostgresLeavers(archive._pool)


async def _mark(leavers, sub="alice", version=1):
    return await leavers.mark(TENANT, sub, version, ADMIN, NOW)


async def _keys(owner, sub):
    return await owner.fetch(
        "SELECT key_version, retired_at, left_at, encrypted_private, enc_pub FROM user_keys"
        " WHERE user_sub = $1 ORDER BY key_version",
        sub,
    )


async def _running_ceremony(owner, *, started_by="admin"):
    ceremony = uuid.uuid4()
    await owner.execute(
        "INSERT INTO recovery_ceremonies (tenant_id, ceremony_id, k, started_by, started_at,"
        " expires_at, status, gateway_keys) VALUES ($1, $2, 1, $3, $4, $5, 'dealing', '[]')",
        TENANT,
        ceremony,
        started_by,
        NOW,
        NOW + timedelta(hours=24),
    )
    return ceremony


async def test_left_at_needs_a_retired_key(archive, owner):
    await enrol(owner, "alice")
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute("UPDATE user_keys SET left_at = $1 WHERE user_sub = 'alice'", NOW)


async def test_holders_lists_active_keys_with_activity_and_custodianship(archive, owner, leavers):
    await recovery_key(owner)
    await owner.execute("UPDATE ceremony_participants SET display_name = 'Carol C.'")
    await enrol(owner, "alice")
    await _ended(archive, owner, employee="alice")
    shredded, _, _ = await _ended(archive, owner, employee="alice")
    await owner.execute(
        "UPDATE conversations SET shredded_at = $1 WHERE conversation_id = $2",
        NOW,
        uuid.UUID(shredded.conversation_id),
    )
    await owner.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'dave'", NOW)

    holders = {h.sub: h for h in await leavers.holders(TENANT)}

    assert sorted(holders) == ["alice", "carol"]
    assert await leavers.holder_subs(TENANT) == frozenset({"alice", "carol"})
    alice, carol = holders["alice"], holders["carol"]
    assert (alice.conversations, alice.custodian, alice.display_name) == (1, False, None)
    assert alice.last_conversation_at is not None and alice.key_version == 1
    assert (carol.conversations, carol.last_conversation_at) == (0, None)
    assert (carol.custodian, carol.display_name) == (True, "Carol C.")


async def test_marking_retires_the_key_and_deletes_wraps_blob_and_requests(
    archive, owner, requests, leavers
):
    _, wrapped_key, _ = await _ended(archive, owner, employee="alice")
    locked, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    await enrol(owner, "alice")
    await owner.execute("UPDATE user_keys SET encrypted_private = 'x' WHERE user_sub = 'alice'")
    request, scope = await _key_recovery(requests, owner, [locked])
    await requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)

    marked = await _mark(leavers)

    assert marked == MarkedLeaver("alice", 1, False, 1)
    [key] = await _keys(owner, "alice")
    assert (key["retired_at"], key["left_at"], key["encrypted_private"]) == (NOW, NOW, None)
    assert key["enc_pub"] is not None  # old signatures still verify
    user_wraps = "SELECT count(*) FROM key_wraps WHERE recipient_kind = $1"
    assert await owner.fetchval(user_wraps, "user") == 0
    assert await owner.fetchval(user_wraps, "recovery") == 2
    assert await owner.fetchval("SELECT status FROM recovery_requests") == "cancelled"
    assert await owner.fetchval("SELECT count(*) FROM recovery_partials") == 0
    events = await _audit(owner)
    assert (ADMIN, "recovery.request.cancelled", request.request_id) in events
    assert (ADMIN, "key_wrap.deleted", wrapped_key) in events
    assert events[-1] == (ADMIN, "user_left", "user-key:alice:1")
    assert not any(e[1] == "recovery.share.stale" for e in events)
    assert chain_is_intact(await PostgresRecordingRepository(archive._pool).audit_rows(TENANT))


async def test_another_users_wraps_and_requests_are_untouched(archive, owner, requests, leavers):
    await _ended(archive, owner, employee="bob")
    theirs, _, _ = await _ended(archive, owner, employee="bob", wrapped=False)
    await _key_recovery(requests, owner, [theirs], sub="bob")
    await enrol(owner, "alice")

    assert isinstance(await _mark(leavers), MarkedLeaver)

    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'bob'") == 1
    assert await owner.fetchval("SELECT status FROM recovery_requests") == "open"
    assert (await _keys(owner, "bob"))[0]["retired_at"] is None


async def test_a_listed_custodian_keeps_the_blob_and_the_share_goes_stale(archive, owner, leavers):
    recovery = await recovery_key(owner)
    await owner.execute("UPDATE user_keys SET encrypted_private = 'x' WHERE user_sub = 'carol'")

    marked = await _mark(leavers, "carol")

    assert marked == MarkedLeaver("carol", 1, True, 0)
    [key] = await _keys(owner, "carol")
    assert (key["left_at"], key["encrypted_private"]) == (NOW, b"x")
    assert (ADMIN, "recovery.share.stale", recovery) in await _audit(owner)


async def test_a_custodian_who_re_enrolled_earlier_keeps_the_older_blob(archive, owner, leavers):
    await recovery_key(owner)
    await owner.execute("UPDATE user_keys SET encrypted_private = 'x' WHERE user_sub = 'carol'")
    assert await _reenrol(archive, "carol") is None

    marked = await _mark(leavers, "carol", 2)

    assert marked.custodian is True
    listed, active = await _keys(owner, "carol")
    assert listed["encrypted_private"] == b"x" and listed["left_at"] is None
    assert active["encrypted_private"] is None and active["left_at"] == NOW
    # The share went stale at the re-enrolment, not again now.
    assert sum(e[1] == "recovery.share.stale" for e in await _audit(owner)) == 1


async def test_marking_refuses_no_key_a_stale_version_and_an_already_left_user(
    archive, owner, leavers
):
    assert await _mark(leavers) == Refused("key_not_enrolled")
    await enrol(owner, "alice")
    assert await _mark(leavers, version=2) == Refused("key_changed")
    assert isinstance(await _mark(leavers), MarkedLeaver)
    assert await _mark(leavers) == Refused("already_left")
    assert [e[1] for e in await _audit(owner)] == ["user_left"]


@pytest.mark.parametrize("role", ["participant", "dealer", "starter"])
async def test_marking_refuses_a_running_ceremonys_participant_dealer_or_starter(
    archive, owner, leavers, role
):
    await enrol(owner, "alice")
    ceremony = await _running_ceremony(owner, started_by="alice" if role == "starter" else "x")
    if role == "participant":
        await owner.execute(
            "INSERT INTO ceremony_participants (tenant_id, ceremony_id, holder_index, holder_ref,"
            " kind, enc_pub, sig_pub, fingerprint)"
            " VALUES ($1, $2, 1, 'alice', 'custodian', $3, $4, $5)",
            TENANT,
            ceremony,
            (await _keys(owner, "alice"))[0]["enc_pub"],
            (await _keys(owner, "alice"))[0]["enc_pub"],
            bytes(32),
        )
    if role == "dealer":
        await owner.execute(
            "INSERT INTO ceremony_dealers (tenant_id, ceremony_id, dealer_index, holder_ref, kind)"
            " VALUES ($1, $2, 1, 'alice', 'custodian')",
            TENANT,
            ceremony,
        )
    try:
        assert await _mark(leavers) == Refused("ceremony_in_progress")
        assert (await _keys(owner, "alice"))[0]["retired_at"] is None
    finally:
        await owner.execute("DELETE FROM ceremony_dealers WHERE ceremony_id = $1", ceremony)
        await owner.execute("DELETE FROM ceremony_participants WHERE ceremony_id = $1", ceremony)
        await owner.execute("DELETE FROM recovery_ceremonies WHERE ceremony_id = $1", ceremony)


async def test_a_lapsed_ceremony_started_by_them_does_not_block(archive, owner, leavers):
    await enrol(owner, "alice")
    ceremony = await _running_ceremony(owner, started_by="alice")
    await owner.execute(
        "UPDATE recovery_ceremonies SET expires_at = $2 WHERE ceremony_id = $1",
        ceremony,
        NOW - timedelta(seconds=1),
    )
    try:
        assert isinstance(await _mark(leavers), MarkedLeaver)
    finally:
        await owner.execute("DELETE FROM recovery_ceremonies WHERE ceremony_id = $1", ceremony)


async def _waiting(owner, count: int) -> None:
    """Until `count` backends wait on a lock: the order they queued in is the order they run."""
    for _ in range(100):
        if await owner.fetchval("SELECT count(*) FROM pg_locks WHERE NOT granted") >= count:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("nobody queued on the lock")


@pytest.mark.parametrize("filing_first", [True, False])
async def test_a_filing_racing_the_marking_leaves_no_open_request(
    archive, owner, requests, leavers, filing_first
):
    """Review: both orders, made deterministic, so each branch is proven on every run."""
    conversation, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    await enrol(owner, "alice")
    request = NewRequest(
        tenant_id=TENANT,
        request_id=str(uuid.uuid4()),
        kind="key_recovery",
        requester_sub="alice",
        requester_key_version=1,
        recovery_key_id=await recovery_key(owner),
        reason="Lost my passphrase.",
        conversation_ids=(conversation.conversation_id,),
        signature=bytes(64),
        created_at=NOW,
    )
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM user_keys WHERE user_sub = 'alice' FOR UPDATE")
        first, second = (
            (lambda: requests.file(request, _always), lambda: _mark(leavers))
            if filing_first
            else (lambda: _mark(leavers), lambda: requests.file(request, _always))
        )
        started = asyncio.create_task(first())
        await _waiting(owner, 1)
        queued = asyncio.create_task(second())
        await _waiting(owner, 2)
        await transaction.rollback()
        results = await asyncio.gather(started, queued)
    finally:
        await holder.close()

    filed, marked = results if filing_first else results[::-1]
    assert isinstance(marked, MarkedLeaver)
    status = await owner.fetchval(
        "SELECT status FROM recovery_requests WHERE request_id = $1", uuid.UUID(request.request_id)
    )
    if filing_first:
        assert not isinstance(filed, Refused)
        assert status == "cancelled"
    else:
        assert filed == Refused("key_changed")
        assert status is None


async def test_a_marking_that_waited_on_a_re_enrolment_says_the_key_changed(
    archive, owner, leavers
):
    """Review: the row it waited on is retired, and the newer key was not the one shown."""
    await enrol(owner, "alice")
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM user_keys WHERE user_sub = 'alice' FOR UPDATE")
        swap = asyncio.create_task(_reenrol(archive))
        await _waiting(owner, 1)
        marking = asyncio.create_task(_mark(leavers))
        await _waiting(owner, 2)
        await transaction.rollback()
        swapped, marked = await asyncio.gather(swap, marking)
    finally:
        await holder.close()

    assert swapped is None
    assert marked == Refused("key_changed")
    assert [(k["key_version"], k["left_at"]) for k in await _keys(owner, "alice")] == [
        (1, None),
        (2, None),
    ]


async def test_a_leaver_with_5000_wraps_is_marked_within_four_seconds(archive, owner, leavers):
    """The audit lock is taken last and held to the commit, so this bounds its hold (§9.8)."""
    await enrol(owner, "alice")
    await owner.execute(
        "INSERT INTO conversations (tenant_id, conversation_id, session_ref, employee_sub,"
        " legal_basis, timestamp_authority_url, started_at, retention_until)"
        " SELECT $1, gen_random_uuid(), 'ref', 'alice', 'consent', 'https://tsa.test', $2, $3"
        " FROM generate_series(1, 5000)",
        TENANT,
        NOW,
        NOW + timedelta(days=3650),
    )
    await owner.execute(
        "INSERT INTO conversation_keys (tenant_id, key_id, conversation_id, epoch, created_at)"
        " SELECT tenant_id, gen_random_uuid(), conversation_id, 1, $1 FROM conversations",
        NOW,
    )
    await owner.execute(
        "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
        " creator_ref, creator_signature, granted_at)"
        " SELECT tenant_id, key_id, 'user', 'alice', '{}', 'gw', $1, $2 FROM conversation_keys",
        bytes(64),
        NOW,
    )

    started = time.perf_counter()
    marked = await _mark(leavers)
    elapsed = time.perf_counter() - started

    assert isinstance(marked, MarkedLeaver) and marked.wraps_deleted == 5000
    assert elapsed < 4.0, f"marking took {elapsed:.2f} s"  # 0.95 s locally


async def test_left_holders_names_a_marked_custodian_but_not_a_re_enrolled_one(
    archive, owner, leavers
):
    await recovery_key(owner)
    await owner.execute("UPDATE user_keys SET encrypted_private = 'x'")
    assert await _reenrol(archive, "dave") is None
    ceremonies = PostgresCeremonyRepository(archive._pool)
    assert await ceremonies.left_holders(TENANT) == frozenset()

    assert isinstance(await _mark(leavers, "carol"), MarkedLeaver)

    assert await ceremonies.left_holders(TENANT) == frozenset({"carol"})
    states = await ceremonies.holder_states(TENANT)
    assert states == {"carol": "kept", "dave": "kept"}


async def test_a_returning_leaver_is_no_longer_left(archive, owner, leavers):
    await recovery_key(owner)
    await owner.execute("UPDATE user_keys SET encrypted_private = 'x'")
    await _mark(leavers, "carol")
    await owner.execute(
        "INSERT INTO user_keys (tenant_id, user_sub, key_version, enc_pub, sig_pub,"
        " fingerprint, created_at) SELECT tenant_id, user_sub, 2, enc_pub, sig_pub,"
        " $1, created_at FROM user_keys WHERE user_sub = 'carol'",
        b"\x08" * 32,
    )
    ceremonies = PostgresCeremonyRepository(archive._pool)
    assert await ceremonies.left_holders(TENANT) == frozenset()


async def test_an_approval_racing_a_retirement_waits_and_sees_the_share_stale(
    archive, owner, requests
):
    """Review minor 9: the approver's key row is held shared before the request."""
    conversation, _, _ = await _ended(archive, owner)
    request, scope = await _filed(requests, owner, [conversation])
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM user_keys WHERE user_sub = 'carol' FOR UPDATE")
        approving = asyncio.create_task(
            requests.approve(TENANT, "carol", request.request_id, _approval(scope), _always, NOW)
        )
        await asyncio.sleep(0.3)
        assert not approving.done()
        await holder.execute(
            "UPDATE user_keys SET retired_at = $1, left_at = $1 WHERE user_sub = 'carol'", NOW
        )
        await transaction.commit()
        approved = await approving
    finally:
        await holder.close()

    assert approved == Refused("share_stale")
    assert await owner.fetchval("SELECT count(*) FROM recovery_decisions") == 0


async def test_a_returning_leaver_enrols_the_next_version(archive, owner, leavers):
    await enrol(owner, "alice")
    await _mark(leavers)
    record = _new_key("alice", version=1)

    assert await PostgresRecordingRepository(archive._pool).enrol_user_key(record) == 2

    retired, active = await _keys(owner, "alice")
    assert (retired["left_at"], active["key_version"], active["retired_at"]) == (NOW, 2, None)
    assert (await _audit(owner))[-1] == ("alice", "key_enrolled", "user-key:2")


class _Members:
    """The directory after Studio removed `gone`'s permissions."""

    def __init__(self, *gone: str) -> None:
        self._present = frozenset({"anna", "bernd", "carla", "dora", "emil"} - set(gone))

    async def members(self, tenant_id: str, correlation_id: str) -> frozenset[str]:
        return self._present


def _service(archive, *gone: str) -> Leavers:
    return Leavers(
        store=PostgresLeavers(archive._pool), directory=_Members(*gone), clock=lambda: NOW
    )


async def _recoverable(archive, owner, key, employee: str):
    """A conversation of `employee` whose recovery wrap seals a real CK for the key."""
    conversation, key_id, _ = await _ended(archive, owner, employee=employee)
    ck = os.urandom(32)
    context = ecies.ck_wrap_context(
        TENANT, conversation.conversation_id, key_id, "recovery", key.key_id
    )
    wrap = ecies.seal(tags.CK_WRAP, key.recovery_public_key, ck, context)
    await owner.execute(
        "UPDATE key_wraps SET blob = $1, recipient_ref = $3"
        " WHERE recipient_kind = 'recovery' AND key_id = $2",
        wrap.to_json(),
        uuid.UUID(key_id),
        key.key_id,
    )
    return conversation, key_id, ck, wrap, context


async def test_acceptance_a_leaver_loses_access_and_the_authority_keeps_it(store, owner, archive):
    """#617: a leaver's wraps and blob go, their public keys stay, recovery still opens."""
    ceremonies, _ = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    conversation, conversation_key, ck, wrap, context = await _recoverable(
        archive, owner, key, "dora"
    )
    requests = PostgresRecoveryRequests(archive._pool)
    locked, _, _ = await _ended(archive, owner, employee="dora", wrapped=False)
    await owner.execute(
        "UPDATE key_wraps SET recipient_ref = $1 WHERE recipient_kind = 'recovery'", key.key_id
    )
    own = NewRequest(
        TENANT,
        str(uuid.uuid4()),
        "key_recovery",
        "dora",
        1,
        key.key_id,
        "Lost it.",
        (locked.conversation_id,),
        bytes(64),
        NOW,
    )
    assert not isinstance(await requests.file(own, _always), Refused)

    marked = await _service(archive, "dora").mark(TENANT, "admin-anna", "dora", 1, "c")

    assert (marked.custodian, marked.wraps_deleted) == (False, 1)
    [row] = await _keys(owner, "dora")
    assert row["encrypted_private"] is None and row["left_at"] == NOW
    kept = await owner.fetchrow("SELECT enc_pub, sig_pub FROM user_keys WHERE user_sub = 'dora'")
    assert (bytes(kept["enc_pub"]), bytes(kept["sig_pub"])) == (
        DORA.key_record().enc_pub,
        DORA.key_record().sig_pub,
    )
    status = "SELECT status FROM recovery_requests WHERE request_id = $1"
    assert await owner.fetchval(status, uuid.UUID(own.request_id)) == "cancelled"

    # A supervisor's exceptional access still opens the leaver's conversation.
    request_id, scope = await _file(
        archive, owner, key.key_id, sub="emil", conversation=conversation
    )
    snapshot = await store.holder_generation(TENANT)
    ephemeral = decode_point(wrap.ephemeral)
    for participant in snapshot.participants[:2]:
        partial = encode_point(multiply(shares[participant.holder_index], ephemeral))
        blob = json.dumps({"P": b64url(partial)})
        approval = Approval({k.key_id: blob for k in scope}, bytes(64))
        decided = await requests.approve(
            TENANT, participant.holder_ref, request_id, approval, _always, NOW
        )
        assert decided is None
    served = await requests.partials(TENANT, "emil", request_id, NOW, may_supervise=True)
    partials = [
        (a.holder_index, decode_point(from_b64url(json.loads(a.blobs[conversation_key])["P"])))
        for a in served.approvals
    ]
    combined = ref.combine_partials(partials)
    assert ecies.open_with_shared_x(wrap, combined, key.recovery_public_key, context) == ck

    # Back again under the same sub: a new key, and key recovery for the old conversations.
    returning = _new_key("dora", version=1)
    assert await store.enrol_user_key(returning) == 2
    again = NewRequest(
        TENANT,
        str(uuid.uuid4()),
        "key_recovery",
        "dora",
        2,
        key.key_id,
        "Back again.",
        (conversation.conversation_id,),
        bytes(64),
        NOW,
    )
    filed = await requests.file(again, _always)
    assert not isinstance(filed, Refused), filed
    assert [k.conversation_id for k in filed] == [conversation.conversation_id]


async def test_acceptance_a_custodian_leaver_deals_and_activation_deletes_the_blob(
    store, owner, archive
):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    blob = await owner.fetchval("SELECT encrypted_private FROM user_keys WHERE user_sub = 'anna'")

    marked = await _service(archive, "anna").mark(TENANT, "admin-bernd", "anna", 1, "c")

    assert marked.custodian is True
    assert await store.left_holders(TENANT) == frozenset({"anna"})
    assert (await store.holder_states(TENANT))["anna"] == "kept"
    [row] = await _keys(owner, "anna")
    assert row["encrypted_private"] == blob
    candidates = await _service(archive, "anna").candidates(TENANT, "c")
    assert candidates == []  # retired: no active key left to list

    started = await resharing.start(
        TENANT,
        ORG_ADMIN,
        ResharingStart(2, ("bernd", "dora", "emil"), (1, 4), None, key.current_holders[0]),
        "c",
    )
    reshare_id = started.ceremony.ceremony_id
    material = await resharing.dealer(TENANT, "anna", reshare_id)
    assert (material.dealer_index, material.key.key_version) == (1, 1)
    assert not material.has_active_key
    snapshot = (await ceremonies.state(TENANT)).ceremony
    await ceremonies.deal(
        TENANT, "anna", reshare_id, reshare_dealing(snapshot, 1, shares[1], [61], ANNA)
    )
    sheet = reshare_dealing(snapshot, 4, shares[4], [71], None)
    await resharing.paper_deal(TENANT, ORG_ADMIN, reshare_id, 4, sheet)
    snapshot = (await ceremonies.state(TENANT)).ceremony
    await _confirm_all(ceremonies, snapshot, key.key_id)

    [row] = await _keys(owner, "anna")
    assert row["encrypted_private"] is None
    assert await store.left_holders(TENANT) == frozenset()


async def test_marking_waits_for_an_activation_holding_the_key_row(store, owner, archive):
    """The marking queues behind an activation's lock on the key row, as the swap does (§9.7)."""
    ceremonies, _ = _services(store)
    await _first_generation(ceremonies)
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM recovery_keys WHERE status = 'active' FOR UPDATE")
        marking = asyncio.create_task(
            _service(archive, "carla").mark(TENANT, ADMIN, "carla", 1, "c")
        )
        await asyncio.sleep(0.5)
        assert not marking.done()
        await transaction.rollback()
        assert isinstance(await marking, MarkedLeaver)
    finally:
        await holder.close()


async def test_a_custodian_marked_after_activation_dropped_them_keeps_no_blob(
    store, owner, archive
):
    """The other order of the race above: the marking sees the new holders and keeps nothing."""
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    started = await resharing.start(
        TENANT,
        ORG_ADMIN,
        ResharingStart(2, ("bernd", "dora", "emil"), (1, 4), None, key.current_holders[0]),
        "c",
    )
    reshare_id = started.ceremony.ceremony_id
    snapshot = (await ceremonies.state(TENANT)).ceremony
    await ceremonies.deal(
        TENANT, "anna", reshare_id, reshare_dealing(snapshot, 1, shares[1], [61], ANNA)
    )
    sheet = reshare_dealing(snapshot, 4, shares[4], [71], None)
    await resharing.paper_deal(TENANT, ORG_ADMIN, reshare_id, 4, sheet)
    await _confirm_all(ceremonies, (await ceremonies.state(TENANT)).ceremony, key.key_id)

    marked = await _service(archive, "carla").mark(TENANT, ADMIN, "carla", 1, "c")

    assert marked.custodian is False
    [row] = await _keys(owner, "carla")
    assert row["encrypted_private"] is None


async def test_a_left_custodian_counts_for_no_approval(archive, owner, leavers):
    await recovery_key(owner, k=2)
    await _mark(leavers, "carol")
    async with archive._pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
            row = await connection.fetchrow(USABLE_SHARES)
    assert (row["k"], row["usable"]) == (2, 1)


async def test_a_marked_users_stale_re_enrolment_falls_through_to_enrolment(
    archive, owner, leavers
):
    await enrol(owner, "alice")
    await _mark(leavers)
    assert await _reenrol(archive) == Refused("key_not_enrolled")


async def test_two_enrolments_of_a_returning_leaver_make_one_key(archive, owner, leavers):
    await enrol(owner, "alice")
    await _mark(leavers)
    repository = PostgresRecordingRepository(archive._pool)
    results = await asyncio.gather(
        repository.enrol_user_key(_new_key("alice", version=1)),
        repository.enrol_user_key(_new_key("alice", version=1)),
        return_exceptions=True,
    )
    assert sorted(type(r).__name__ for r in results) == ["KeyAlreadyEnrolledError", "int"]
    assert await owner.fetchval("SELECT count(*) FROM user_keys WHERE retired_at IS NULL") == 1
