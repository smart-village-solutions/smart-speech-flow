"""Expiry and early erasure in the database, as the primary worker's role (spec §16.1).

Same environment as test_recording_retention_database.py.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import timedelta

import asyncpg
import pytest

from services.api_gateway.recording.audit import AuditEvent, AuditRow, chain_is_intact
from services.api_gateway.recording.retention.decisions import RetentionRefusedError
from services.api_gateway.recording.retention.store import (
    EXPIRY_DELETION_ORDER,
    KEPT_AFTER_EXPIRY,
    LockState,
)
from tests.integration import test_recording_archive_database as archive_database
from tests.integration import test_recording_retention_store as store_tests
from tests.integration.test_recording_archive_database import NOW, TENANT, _conversation

pytestmark = pytest.mark.integration

owner = archive_database.owner
archive = archive_database.archive
stores = store_tests.stores
_decide = store_tests._decide


async def _expired(archive, owner, *, ended=True, started=NOW - timedelta(days=40)):
    """A stored conversation whose retention date passed a day ago."""
    record = dataclasses.replace(
        _conversation(), started_at=started, retention_until=NOW - timedelta(days=1)
    )
    conversation, consent = await store_tests._stored(archive, record)
    if ended:
        await owner.execute(
            "UPDATE conversations SET ended_at = $2 WHERE conversation_id = $1",
            uuid.UUID(conversation.conversation_id),
            started + timedelta(minutes=30),
        )
    return conversation.conversation_id


async def _count(owner, table: str, conversation_id: str) -> int:
    if table == "stored_objects":
        sql = (
            "SELECT count(*) FROM stored_objects WHERE entry_id IN"
            " (SELECT entry_id FROM chain_entries WHERE conversation_id = $1)"
        )
    elif table == "key_wraps":
        sql = (
            "SELECT count(*) FROM key_wraps WHERE key_id IN"
            " (SELECT key_id FROM conversation_keys WHERE conversation_id = $1)"
        )
    else:
        sql = f"SELECT count(*) FROM {table} WHERE conversation_id = $1"  # noqa: S608 - fixed names
    return await owner.fetchval(sql, uuid.UUID(conversation_id))


async def _audit_rows(owner) -> list[AuditRow]:
    rows = await owner.fetch("SELECT * FROM audit_events WHERE tenant_id = $1 ORDER BY seq", TENANT)
    return [
        AuditRow(
            event=AuditEvent(
                row["tenant_id"], row["actor_sub"], row["event_type"], row["object_ref"], row["at"]
            ),
            seq=row["seq"],
            prev_hash=bytes(row["prev_hash"]),
            hash=bytes(row["hash"]),
        )
        for row in rows
    ]


async def test_only_ended_or_long_started_unheld_conversations_past_their_date_are_due(
    archive, owner, stores
):
    due = await _expired(archive, owner)
    abandoned = await _expired(archive, owner, ended=False, started=NOW - timedelta(hours=25))
    live = await _expired(archive, owner, ended=False, started=NOW - timedelta(hours=23))
    held = await _expired(archive, owner)
    await _decide(held, "hold_on")
    in_date, _ = await store_tests._stored(archive)

    found = await stores["primary"].due_expiries(TENANT, NOW)

    assert set(found) == {due, abandoned}
    assert live not in found and held not in found and in_date.conversation_id not in found
    with pytest.raises(RetentionRefusedError, match="primary_only"):
        await stores["replica"].due_expiries(TENANT, NOW)


async def test_a_shred_removes_its_wraps_only_and_is_audited(archive, owner, stores):
    shredded, kept = await _expired(archive, owner), await _expired(archive, owner)
    store = stores["primary"]
    await store.discover(TENANT, NOW)
    for due in await store.due_versions(TENANT, NOW):
        await store.record(due, LockState(NOW, None, False, None, None), NOW + timedelta(days=9))

    assert await store.shred(TENANT, shredded, NOW, "retention-worker") is True

    assert await _count(owner, "key_wraps", shredded) == 0
    assert await _count(owner, "key_wraps", kept) == 1
    assert (
        await owner.fetchval(
            "SELECT shredded_at FROM conversations WHERE conversation_id = $1", uuid.UUID(shredded)
        )
        == NOW
    )
    reset = await owner.fetch(
        "SELECT conversation_id, next_attempt_at FROM version_locks ORDER BY conversation_id"
    )
    assert {str(r["conversation_id"]): r["next_attempt_at"] for r in reset} == {
        shredded: NOW,
        kept: NOW + timedelta(days=9),
    }
    audit = await _audit_rows(owner)
    assert chain_is_intact(audit)
    assert (audit[-1].event.event_type, audit[-1].event.object_ref) == (
        "recording.shredded",
        shredded,
    )
    # The gateway can never wrap a key for it again.
    with pytest.raises(Exception, match="conversation_shredded"):
        await owner.execute(
            "INSERT INTO key_wraps SELECT w.tenant_id, k.key_id, w.recipient_kind, 'again',"
            " w.blob, w.creator_ref, w.creator_signature, w.granted_at FROM key_wraps w,"
            " conversation_keys k WHERE k.conversation_id = $1 LIMIT 1",
            uuid.UUID(shredded),
        )
    assert await store.shred(TENANT, shredded, NOW, "retention-worker") is False


async def test_a_hold_that_arrives_before_the_shred_stops_it(archive, owner, stores):
    conversation = await _expired(archive, owner)
    assert await stores["primary"].due_expiries(TENANT, NOW) == [conversation]
    await _decide(conversation, "hold_on")
    assert await stores["primary"].shred(TENANT, conversation, NOW, "retention-worker") is False
    assert await _count(owner, "key_wraps", conversation) == 1


async def test_a_site_clears_a_shredded_conversation_once_its_versions_are_gone(
    archive, owner, stores
):
    conversation = await _expired(archive, owner)
    replica = stores["replica"]
    await replica.discover(TENANT, NOW)
    await stores["primary"].shred(TENANT, conversation, NOW, "retention-worker")
    assert await replica.clearable(TENANT) == []

    [row] = await replica.due_versions(TENANT, NOW)
    await replica.record(row, LockState(NOW, None, False, None, NOW), NOW)
    assert await replica.clearable(TENANT) == [conversation]
    await replica.record_clearance(TENANT, conversation, NOW)
    assert await replica.clearable(TENANT) == []
    sites = await owner.fetch("SELECT site FROM site_clearances")
    assert [r["site"] for r in sites] == ["replica"]
    assert await stores["primary"].deletable(TENANT) == []


async def test_rows_go_only_after_both_sites_cleared_and_audit_and_decisions_stay(
    archive, owner, stores
):
    expired, kept = await _expired(archive, owner), await _expired(archive, owner)
    await _decide(expired, "extend", until=NOW)
    primary = stores["primary"]
    await primary.shred(TENANT, expired, NOW, "retention-worker")
    await primary.record_clearance(TENANT, expired, NOW)
    assert await primary.delete_rows(TENANT, expired, NOW) is False
    await stores["replica"].record_clearance(TENANT, expired, NOW)
    assert await primary.deletable(TENANT) == [expired]

    assert await primary.delete_rows(TENANT, expired, NOW) is True

    for table in EXPIRY_DELETION_ORDER:
        assert await _count(owner, table, expired) == 0, table
    assert await _count(owner, "conversations", kept) == 1
    assert await _count(owner, "key_wraps", kept) == 1
    assert await _count(owner, "retention_decisions", expired) == 1
    audit = await _audit_rows(owner)
    assert chain_is_intact(audit)
    assert [r.event.event_type for r in audit[-2:]] == [
        "recording.versions_deleted",
        "recording.expired",
    ]
    assert all(r.event.object_ref == expired for r in audit[-2:])
    with pytest.raises(RetentionRefusedError, match="primary_only"):
        await stores["replica"].delete_rows(TENANT, kept, NOW)


async def test_every_table_naming_a_conversation_is_expired_or_kept(owner):
    rows = await owner.fetch(
        "SELECT table_name FROM information_schema.columns"
        " WHERE table_schema = 'public' AND column_name = 'conversation_id'"
    )
    named = {row["table_name"] for row in rows}
    assert named <= set(EXPIRY_DELETION_ORDER) | set(KEPT_AFTER_EXPIRY), sorted(
        named - set(EXPIRY_DELETION_ORDER) - set(KEPT_AFTER_EXPIRY)
    )
    # These name no conversation themselves and go through their parents.
    assert {"stored_objects", "key_wraps"} <= set(EXPIRY_DELETION_ORDER)
    assert EXPIRY_DELETION_ORDER[-1] == "conversations"


async def test_an_erasure_shreds_at_once_as_the_operator(archive, owner, stores):
    conversation = await _expired(archive, owner)
    await owner.execute(
        "UPDATE conversations SET retention_until = $2 WHERE conversation_id = $1",
        uuid.UUID(conversation),
        NOW + timedelta(days=300),
    )

    decision_id = await stores["primary"].erase(TENANT, conversation, NOW, "alice", "court order")

    decision = await owner.fetchrow("SELECT * FROM retention_decisions")
    assert (str(decision["decision_id"]), decision["kind"], decision["actor_sub"]) == (
        decision_id,
        "erase",
        "operator:alice",
    )
    assert await _count(owner, "key_wraps", conversation) == 0
    audit = await _audit_rows(owner)
    assert chain_is_intact(audit)
    assert [(r.event.event_type, r.event.object_ref, r.event.actor_sub) for r in audit[-2:]] == [
        ("recording.retention.erased", decision_id, "operator:alice"),
        ("recording.shredded", conversation, "operator:alice"),
    ]


@pytest.mark.parametrize("state", ["held", "live", "shredded", "missing"])
async def test_an_erasure_is_refused_for_a_held_live_shredded_or_missing_conversation(
    archive, owner, stores, state
):
    conversation = await _expired(archive, owner, ended=state != "live")
    if state == "held":
        await _decide(conversation, "hold_on")
    elif state == "shredded":
        await stores["primary"].shred(TENANT, conversation, NOW, "retention-worker")
    elif state == "missing":
        conversation = str(uuid.uuid4())
    decisions = await owner.fetchval("SELECT count(*) FROM retention_decisions")
    events = await owner.fetchval("SELECT count(*) FROM audit_events")

    with pytest.raises(RetentionRefusedError) as refused:
        await stores["primary"].erase(TENANT, conversation, NOW, "alice", "court order")

    assert (
        refused.value.code
        == {
            "held": "legal_hold_set",
            "live": "conversation_live",
            "shredded": "conversation_shredded",
            "missing": "no_conversation",
        }[state]
    )
    assert await owner.fetchval("SELECT count(*) FROM retention_decisions") == decisions
    assert await owner.fetchval("SELECT count(*) FROM audit_events") == events
    with pytest.raises(RetentionRefusedError, match="primary_only"):
        await stores["replica"].erase(TENANT, conversation, NOW, "alice", "x")


@pytest.mark.parametrize("site", ["primary", "replica"])
async def test_a_version_held_on_either_site_stops_expiry_and_erasure(archive, owner, stores, site):
    conversation = await _expired(archive, owner)
    await stores[site].discover(TENANT, NOW)
    [row] = await stores[site].due_versions(TENANT, NOW)
    await stores[site].record(row, LockState(NOW, None, True, NOW, None), NOW)
    primary = stores["primary"]

    assert await primary.due_expiries(TENANT, NOW) == []
    assert await primary.shred(TENANT, conversation, NOW, "retention-worker") is False
    with pytest.raises(RetentionRefusedError, match="version_held"):
        await primary.erase(TENANT, conversation, NOW, "alice", "court order")
    assert await _count(owner, "key_wraps", conversation) == 1
    assert await owner.fetchval("SELECT count(*) FROM retention_decisions") == 0

    await stores[site].record(row, LockState(NOW, None, False, None, None), NOW)
    assert await primary.due_expiries(TENANT, NOW) == [conversation]


_LATE_WRAP = (
    "INSERT INTO key_wraps SELECT w.tenant_id, w.key_id, w.recipient_kind, 'late', w.blob,"
    " w.creator_ref, w.creator_signature, w.granted_at FROM key_wraps w"
    " JOIN conversation_keys k USING (tenant_id, key_id) WHERE k.conversation_id = $1"
)


async def test_a_shred_waits_for_a_wrap_being_granted_and_takes_it_too(archive, owner, stores):
    conversation = await _expired(archive, owner)
    async with archive._pool.acquire() as gateway:
        transaction = gateway.transaction()
        await transaction.start()
        await gateway.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
        await gateway.execute(_LATE_WRAP, uuid.UUID(conversation))
        shred = asyncio.create_task(
            stores["primary"].shred(TENANT, conversation, NOW, "retention-worker")
        )
        await asyncio.sleep(0.5)
        assert not shred.done()  # held back by the grant's share lock
        await transaction.commit()
    assert await shred is True
    assert await _count(owner, "key_wraps", conversation) == 0


async def test_a_wrap_granted_during_a_shred_is_refused(archive, owner, stores):
    conversation = await _expired(archive, owner)
    shredder = await asyncpg.connect(
        archive_database.OWNER_DSN, password=archive_database.OWNER_PASSWORD
    )
    try:
        transaction = shredder.transaction()
        await transaction.start()
        await shredder.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR UPDATE",
            uuid.UUID(conversation),
        )
        await shredder.execute(
            "UPDATE conversations SET shredded_at = $2 WHERE conversation_id = $1",
            uuid.UUID(conversation),
            NOW,
        )

        async def grant():
            async with archive._pool.acquire() as gateway:
                async with gateway.transaction():
                    await gateway.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
                    await gateway.execute(_LATE_WRAP, uuid.UUID(conversation))

        granting = asyncio.create_task(grant())
        await asyncio.sleep(0.5)
        assert not granting.done()  # waits for the shred's row lock
        await transaction.commit()
        with pytest.raises(asyncpg.RaiseError, match="conversation_shredded"):
            await granting
    finally:
        await shredder.close()
