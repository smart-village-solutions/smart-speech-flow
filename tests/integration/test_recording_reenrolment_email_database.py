"""Email confirmation of a re-enrolment in Postgres (spec §9.9; migration 010)."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import timedelta

import asyncpg
import pytest

from services.api_gateway.recording.audit import chain_is_intact
from services.api_gateway.recording.key_confirmation_repository import (
    LinkDetails,
    PendingKey,
    PostgresKeyConfirmations,
)
from services.api_gateway.recording.leavers_repository import PostgresLeavers
from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.repository import PostgresRecordingRepository
from tests import recording_crypto_reference as ref
from tests.integration.test_recording_archive_database import (  # noqa: F401 - fixtures
    _BIND,
    APP_DSN,
    APP_PASSWORD,
    NOW,
    OWNER_DSN,
    OWNER_PASSWORD,
    TENANT,
    archive,
    owner,
)
from tests.integration.test_recording_archive_access_database import _ended
from tests.integration.test_recording_key_recovery_database import _key_recovery, _new_key
from tests.integration.test_recording_leavers_database import _running_ceremony, _waiting
from tests.integration.test_recording_recovery_requests_database import (  # noqa: F401
    _audit,
    enrol,
    recovery_key,
    requests,
)
from tests.integration.test_recording_resharing_database import _clean

pytestmark = pytest.mark.integration

OTHER = "tenant-b"
ADMIN = "admin-anna"


@pytest.fixture(autouse=True)
async def _fresh(owner):
    await _clean(owner)
    await owner.execute("DELETE FROM user_key_reenrolments")
    yield
    await owner.execute("DELETE FROM user_key_reenrolments")
    await _clean(owner)


def _hash(label: str) -> bytes:
    return hashlib.sha256(label.encode()).digest()


async def _pending(owner, sub="alice", *, tenant=TENANT, label="t1", email="alice@example.org"):
    await owner.execute(
        "INSERT INTO user_key_reenrolments (tenant_id, user_sub, key_version, enc_pub, sig_pub,"
        " fingerprint, encrypted_private, email, replaces_version, token_hash, requested_at,"
        " expires_at) VALUES ($1, $2, 2, $3, $4, $5, 'sealed', $6, 1, $7, $8, $9)",
        tenant,
        sub,
        ref.public_point(700),
        ref.public_point(701),
        b"\x07" * 32,
        email,
        _hash(label),
        NOW,
        NOW + timedelta(minutes=30),
    )


async def _as_app(statement: str, *args, tenant=TENANT):
    connection = await asyncpg.connect(APP_DSN, password=APP_PASSWORD)
    try:
        async with connection.transaction():
            await connection.execute(_BIND, tenant)
            return await connection.fetch(statement, *args)
    finally:
        await connection.close()


async def test_the_app_cannot_update_a_pending_row(archive, owner):
    await _pending(owner)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _as_app("UPDATE user_key_reenrolments SET email = 'mallory@example.org'")


async def test_pending_rows_are_confined_to_their_tenant(archive, owner):
    await _pending(owner, "alice")
    await _pending(owner, "bob", tenant=OTHER, label="t2")

    rows = await _as_app("SELECT user_sub FROM user_key_reenrolments")

    assert [r["user_sub"] for r in rows] == ["alice"]


async def test_reenrolment_tenant_finds_any_tenants_token(archive, owner):
    await _pending(owner, "bob", tenant=OTHER, label="t2")

    found = await _as_app("SELECT reenrolment_tenant($1) AS tenant", _hash("t2"))
    missing = await _as_app("SELECT reenrolment_tenant($1) AS tenant", _hash("nope"))

    assert (found[0]["tenant"], missing[0]["tenant"]) == (OTHER, None)


async def test_addresses_are_at_most_254_characters(archive, owner):
    await enrol(owner, "alice")
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute("UPDATE user_keys SET email = $1", "a" * 255)
    with pytest.raises(asyncpg.CheckViolationError):
        await _pending(owner, email="")


async def test_an_enrolment_stores_its_address(archive, owner):
    repository = PostgresRecordingRepository(archive._pool)
    record = replace(_new_key(version=1), email="alice@example.org")
    await repository.enrol_user_key(record)

    stored = await repository.active_user_key(TENANT, "alice")
    assert stored is not None and stored.email == "alice@example.org"
    assert await owner.fetchval("SELECT email FROM user_keys") == "alice@example.org"


async def _with_address(owner, sub="alice"):
    await enrol(owner, sub)
    await owner.execute(
        "UPDATE user_keys SET email = $2 WHERE user_sub = $1", sub, f"{sub}@example.org"
    )


async def test_a_marking_clears_the_address_and_cancels_the_pending_key(archive, owner):
    await _with_address(owner)
    await _pending(owner)

    await PostgresLeavers(archive._pool).mark(TENANT, "alice", 1, ADMIN, NOW)

    assert await owner.fetchval("SELECT email FROM user_keys WHERE user_sub = 'alice'") is None
    assert await owner.fetchval("SELECT count(*) FROM user_key_reenrolments") == 0
    assert (ADMIN, "key_reenrolment.cancelled", "user-key:alice:2") in await _audit(owner)


async def test_a_retirement_without_a_pending_key_cancels_nothing(archive, owner):
    await _with_address(owner)
    await _pending(owner, "bob", label="t2")

    await PostgresLeavers(archive._pool).mark(TENANT, "alice", 1, ADMIN, NOW)

    assert await owner.fetchval("SELECT count(*) FROM user_key_reenrolments") == 1
    assert not [event for event in await _audit(owner) if event[1].startswith("key_reenrolment")]


@pytest.fixture
def confirmations(archive):
    return PostgresKeyConfirmations(archive._pool)


def _later(record_at=NOW, minutes=30):
    return record_at + timedelta(minutes=minutes)


async def _hold(confirmations, label="t1", *, at=NOW, sub="alice"):
    record = replace(_new_key(sub, 2, at), email=None)
    return await confirmations.hold(record, 1, _hash(label), _later(at))


async def _rows(owner):
    return await owner.fetch(
        "SELECT user_sub, key_version, email, replaces_version, token_hash, expires_at"
        " FROM user_key_reenrolments ORDER BY user_sub"
    )


async def test_a_hold_pins_the_current_keys_address_and_keeps_the_key_active(
    archive, owner, confirmations
):
    await _with_address(owner)

    assert await _hold(confirmations) == "alice@example.org"

    [row] = await _rows(owner)
    assert (row["email"], row["key_version"], row["replaces_version"]) == (
        "alice@example.org",
        2,
        1,
    )
    assert bytes(row["token_hash"]) == _hash("t1") and row["expires_at"] == _later()
    active = await owner.fetchval("SELECT key_version FROM user_keys WHERE retired_at IS NULL")
    assert active == 1
    assert (await _audit(owner))[-1] == ("alice", "key_reenrolment.requested", "user-key:alice:2")


async def test_a_key_without_an_address_cannot_be_held(archive, owner, confirmations):
    await enrol(owner, "alice")
    assert await _hold(confirmations) == Refused("email_not_verified")
    assert await _rows(owner) == []


@pytest.mark.parametrize(("replaces", "code"), [(2, "key_changed"), (1, "key_not_enrolled")])
async def test_a_hold_keeps_the_swaps_refusals(archive, owner, confirmations, replaces, code):
    if code == "key_changed":
        await _with_address(owner)
    record = replace(_new_key("alice", replaces + 1), email=None)
    assert await confirmations.hold(record, replaces, _hash("t1"), _later()) == Refused(code)


async def test_a_second_hold_supersedes_the_first(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations, "t1")
    await _hold(confirmations, "t2")

    [row] = await _rows(owner)
    assert bytes(row["token_hash"]) == _hash("t2")
    assert [event[1] for event in await _audit(owner)] == [
        "key_reenrolment.requested",
        "key_reenrolment.cancelled",
        "key_reenrolment.requested",
    ]


async def test_two_concurrent_holds_leave_one_pending_key(archive, owner, confirmations):
    """Review: under FOR SHARE both would insert and the second would fail as a 503."""
    await _with_address(owner)
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM user_keys WHERE user_sub = 'alice' FOR UPDATE")
        first = asyncio.create_task(_hold(confirmations, "t1"))
        await _waiting(owner, 1)
        second = asyncio.create_task(_hold(confirmations, "t2"))
        await _waiting(owner, 2)
        await transaction.rollback()
        results = await asyncio.gather(first, second)
    finally:
        await holder.close()

    assert results == ["alice@example.org", "alice@example.org"]
    assert len(await _rows(owner)) == 1


async def test_a_release_spares_a_newer_pending_key(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations, "t1")
    await _hold(confirmations, "t2")

    await confirmations.release(TENANT, _hash("t1"), NOW)
    assert len(await _rows(owner)) == 1
    await confirmations.release(TENANT, _hash("t2"), NOW)

    assert await _rows(owner) == []
    assert (await _audit(owner))[-1] == ("alice", "key_reenrolment.cancelled", "user-key:alice:2")


async def test_the_sweep_expires_old_links_except_the_one_in_hand(archive, owner, confirmations):
    await _with_address(owner, "alice")
    await _with_address(owner, "bob")
    await _with_address(owner, "carl")
    await _hold(confirmations, "t1", sub="alice", at=NOW - timedelta(hours=1))
    await _hold(confirmations, "t2", sub="bob", at=NOW - timedelta(hours=1))
    await _hold(confirmations, "t3", sub="carl")

    await confirmations.sweep(TENANT, NOW, keep=_hash("t2"))

    assert [row["user_sub"] for row in await _rows(owner)] == ["bob", "carl"]
    assert ("alice", "key_reenrolment.expired", "user-key:alice:2") in await _audit(owner)


async def test_pending_of_shows_only_a_live_link(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations)

    pending = await confirmations.pending_of(TENANT, "alice", NOW)
    expired = await confirmations.pending_of(TENANT, "alice", _later(minutes=31))

    assert pending == PendingKey(b"\x07" * 32, _later()) and expired is None
    assert await confirmations.pending_of(TENANT, "bob", NOW) is None


async def test_tenant_of_names_the_links_tenant(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations)
    assert await confirmations.tenant_of(_hash("t1")) == TENANT
    assert await confirmations.tenant_of(_hash("nope")) is None


async def test_a_lookup_shows_the_link_and_expires_a_lapsed_one(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations)

    shown = await confirmations.lookup(TENANT, _hash("t1"), NOW)
    assert shown == LinkDetails(b"\x07" * 32, NOW, _later())
    assert await confirmations.lookup(OTHER, _hash("t1"), NOW) == Refused("link_invalid")
    assert await confirmations.lookup(TENANT, _hash("nope"), NOW) == Refused("link_invalid")

    lapsed = await confirmations.lookup(TENANT, _hash("t1"), _later(minutes=31))

    assert lapsed == Refused("link_expired") and await _rows(owner) == []
    assert (await _audit(owner))[-1] == ("alice", "key_reenrolment.expired", "user-key:alice:2")


async def test_a_decline_deletes_the_pending_key_once(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations)

    assert await confirmations.decline(TENANT, _hash("t1"), NOW) is None
    assert await confirmations.decline(TENANT, _hash("t1"), NOW) == Refused("link_invalid")

    assert await _rows(owner) == []
    active = await owner.fetchval("SELECT key_version FROM user_keys WHERE retired_at IS NULL")
    assert active == 1
    assert (await _audit(owner))[-1] == ("alice", "key_reenrolment.declined", "user-key:alice:2")


async def test_an_expired_link_cannot_be_declined(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations)
    assert await confirmations.decline(TENANT, _hash("t1"), _later(minutes=31)) == Refused(
        "link_expired"
    )


async def _active(owner, sub="alice"):
    return await owner.fetchrow(
        "SELECT key_version, email, created_at FROM user_keys"
        " WHERE user_sub = $1 AND retired_at IS NULL",
        sub,
    )


async def test_criterion_1_the_old_key_works_until_the_link_is_confirmed(
    archive, owner, confirmations, requests
):
    locked, _, _ = await _ended(archive, owner, employee="alice", wrapped=False)
    await _with_address(owner)
    await _hold(confirmations)

    # Pending: the old key still files and is still the one shown.
    _, filed = await _key_recovery(requests, owner, [locked])
    assert not isinstance(filed, Refused) and (await _active(owner))["key_version"] == 1

    later = NOW + timedelta(minutes=5)
    assert await confirmations.confirm(TENANT, _hash("t1"), later) == b"\x07" * 32

    active = await _active(owner)
    assert (active["key_version"], active["email"], active["created_at"]) == (
        2,
        "alice@example.org",
        later,
    )
    old = await owner.fetchrow(
        "SELECT retired_at, email FROM user_keys WHERE user_sub = 'alice' AND key_version = 1"
    )
    assert (old["retired_at"], old["email"]) == (later, None)
    assert await _rows(owner) == []


async def test_criterion_2_a_link_works_once_for_its_tenant_and_expires(
    archive, owner, confirmations
):
    await _with_address(owner)
    await _with_address(owner, "bob")
    await _hold(confirmations, "t1")
    await _hold(confirmations, "t2", sub="bob")

    assert await confirmations.confirm(OTHER, _hash("t1"), NOW) == Refused("link_invalid")
    assert await confirmations.confirm(TENANT, _hash("t1"), NOW) == b"\x07" * 32
    assert await confirmations.confirm(TENANT, _hash("t1"), NOW) == Refused("link_invalid")
    # Alice's link touched nobody else: Bob's key and pending key are as they were.
    assert (await _active(owner, "bob"))["key_version"] == 1
    assert [row["user_sub"] for row in await _rows(owner)] == ["bob"]

    lapsed = await confirmations.confirm(TENANT, _hash("t2"), _later(minutes=31))
    assert lapsed == Refused("link_expired")
    assert (await _active(owner, "bob"))["key_version"] == 1 and await _rows(owner) == []


async def test_criterion_3_a_link_for_a_replaced_key_is_refused(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations)
    await PostgresLeavers(archive._pool).mark(TENANT, "alice", 1, ADMIN, NOW)

    assert await confirmations.confirm(TENANT, _hash("t1"), NOW) == Refused("link_invalid")


async def test_a_replaced_key_that_slipped_past_retirement_is_refused_and_dropped(
    archive, owner, confirmations
):
    """Defence in depth: a key retired outside retire_key still cannot be swapped."""
    await _with_address(owner)
    await _hold(confirmations)
    await owner.execute("UPDATE user_keys SET retired_at = $1", NOW)

    assert await confirmations.confirm(TENANT, _hash("t1"), NOW) == Refused("link_invalid")
    assert await _rows(owner) == []
    assert (await _audit(owner))[-1] == ("alice", "key_reenrolment.cancelled", "user-key:alice:2")


async def test_a_running_ceremony_keeps_the_link_for_later(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations)
    ceremony = await _running_ceremony(owner)
    await owner.execute(
        "INSERT INTO ceremony_participants (tenant_id, ceremony_id, holder_index, kind,"
        " holder_ref, display_name, fingerprint, enc_pub, sig_pub) SELECT $1, $2, 1, 'custodian',"
        " 'alice',"
        " 'Alice', fingerprint, enc_pub, sig_pub FROM user_keys WHERE user_sub = 'alice'",
        TENANT,
        ceremony,
    )
    audited = len(await _audit(owner))

    refused = await confirmations.confirm(TENANT, _hash("t1"), NOW)

    assert refused == Refused("ceremony_in_progress")
    assert len(await _rows(owner)) == 1 and len(await _audit(owner)) == audited


async def test_criterion_5_every_step_is_audited(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations, "t1")
    await _hold(confirmations, "t2")
    await confirmations.confirm(TENANT, _hash("t2"), NOW)

    events = [event for event in await _audit(owner) if event[0] == "alice"]
    assert events == [
        ("alice", "key_reenrolment.requested", "user-key:alice:2"),
        ("alice", "key_reenrolment.cancelled", "user-key:alice:2"),
        ("alice", "key_reenrolment.requested", "user-key:alice:2"),
        ("alice", "key_reenrolled", "user-key:2"),
    ]
    assert chain_is_intact(await PostgresRecordingRepository(archive._pool).audit_rows(TENANT))


async def test_confirm_racing_confirm_swaps_once(archive, owner, confirmations):
    await _with_address(owner)
    await _hold(confirmations)
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM user_keys WHERE user_sub = 'alice' FOR UPDATE")
        first = asyncio.create_task(confirmations.confirm(TENANT, _hash("t1"), NOW))
        await _waiting(owner, 1)
        second = asyncio.create_task(confirmations.confirm(TENANT, _hash("t1"), NOW))
        await _waiting(owner, 2)
        await transaction.rollback()
        results = await asyncio.gather(first, second)
    finally:
        await holder.close()

    assert sorted(results, key=repr) == sorted([b"\x07" * 32, Refused("link_invalid")], key=repr)
    assert await owner.fetchval("SELECT count(*) FROM user_keys WHERE user_sub = 'alice'") == 2


@pytest.mark.parametrize("confirm_first", [True, False])
async def test_confirm_racing_a_new_request(archive, owner, confirmations, confirm_first):
    await _with_address(owner)
    await _hold(confirmations, "t1")
    holder = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT 1 FROM user_keys WHERE user_sub = 'alice' FOR UPDATE")
        calls = [
            lambda: confirmations.confirm(TENANT, _hash("t1"), NOW),
            lambda: _hold(confirmations, "t2"),
        ]
        first, second = calls if confirm_first else calls[::-1]
        started = asyncio.create_task(first())
        await _waiting(owner, 1)
        queued = asyncio.create_task(second())
        await _waiting(owner, 2)
        await transaction.rollback()
        results = await asyncio.gather(started, queued)
    finally:
        await holder.close()

    confirmed, held = results if confirm_first else results[::-1]
    if confirm_first:
        assert (confirmed, held) == (b"\x07" * 32, Refused("key_changed"))
        assert (await _active(owner))["key_version"] == 2
    else:
        assert (confirmed, held) == (Refused("link_invalid"), "alice@example.org")
        assert bytes((await _rows(owner))[0]["token_hash"]) == _hash("t2")
