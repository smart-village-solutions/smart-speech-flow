"""The retention tables, triggers and roles against a real PostgreSQL (spec §16.1).

Same environment as test_recording_archive_database.py, plus the two worker
roles' URLs and passwords.
"""

from __future__ import annotations

import dataclasses
import os
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from services.api_gateway.recording.audit import chain_is_intact
from services.api_gateway.recording.repository import PostgresRecordingRepository
from services.api_gateway.recording.retention.decisions import (
    RetentionDecision,
    RetentionRefusedError,
)
from services.api_gateway.recording.retention.decisions_repository import (
    PostgresRetentionDecisions,
)
from tests.integration import test_recording_archive_database as archive_database
from tests.integration.test_recording_archive_database import (
    NOW,
    TENANT,
    _conversation,
    _opened,
)

# Its fixtures, shared rather than copied.
owner = archive_database.owner
archive = archive_database.archive

pytestmark = pytest.mark.integration

APP_DSN = os.environ.get("SSF_RECORDING_DATABASE_URL", "")
APP_PASSWORD = os.environ.get("SSF_RECORDING_DATABASE_PASSWORD") or None
RETENTION_DSN = os.environ.get("SSF_RECORDING_RETENTION_DATABASE_URL", "")
RETENTION_PASSWORD = os.environ.get("SSF_RECORDING_RETENTION_DATABASE_PASSWORD") or None
REPLICA_DSN = os.environ.get("SSF_RECORDING_REPLICA_DATABASE_URL", "")
REPLICA_PASSWORD = os.environ.get("SSF_RECORDING_REPLICA_DATABASE_PASSWORD") or None


async def _connect(dsn: str, password: str | None) -> asyncpg.Connection:
    if not dsn:
        pytest.skip("the retention role URLs are not set")
    return await asyncpg.connect(dsn, password=password)


async def _as(dsn, password, sql, *args, tenant=TENANT):
    connection = await _connect(dsn, password)
    try:
        async with connection.transaction():
            await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", tenant)
            return await connection.fetch(sql, *args)
    finally:
        await connection.close()


async def _decide(conversation_id, kind, *, until=None, dsn=APP_DSN, password=APP_PASSWORD):
    return await _as(
        dsn,
        password,
        "INSERT INTO retention_decisions (tenant_id, decision_id, conversation_id, at,"
        " actor_sub, kind, retain_until, reason) VALUES ($1, $2, $3, $4, 'sup', $5, $6, 'r')",
        TENANT,
        uuid.uuid4(),
        uuid.UUID(conversation_id),
        NOW,
        kind,
        until,
    )


async def test_an_extension_moves_the_date_and_a_shorter_one_is_refused(archive, owner):
    conversation, *_ = await _opened(archive)
    later = conversation.retention_until + timedelta(days=30)
    await _decide(conversation.conversation_id, "extend", until=later)
    row = await owner.fetchrow(
        "SELECT retention_until FROM conversations WHERE conversation_id = $1",
        uuid.UUID(conversation.conversation_id),
    )
    assert row["retention_until"] == later
    with pytest.raises(asyncpg.RaiseError, match="retention_not_extended"):
        await _decide(conversation.conversation_id, "extend", until=later)


async def test_the_gateway_cannot_set_the_date_or_the_hold_directly(archive):
    conversation, *_ = await _opened(archive)
    for column in ("legal_hold = TRUE", "retention_until = now()", "shredded_at = now()"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await _as(
                APP_DSN,
                APP_PASSWORD,
                f"UPDATE conversations SET {column} WHERE conversation_id = $1",
                uuid.UUID(conversation.conversation_id),
            )


async def test_holds_follow_their_decisions(archive, owner):
    conversation, *_ = await _opened(archive)
    await _decide(conversation.conversation_id, "hold_on")
    assert await owner.fetchval("SELECT legal_hold FROM conversations") is True
    await _decide(conversation.conversation_id, "hold_off")
    assert await owner.fetchval("SELECT legal_hold FROM conversations") is False


async def test_only_the_primary_worker_erases_and_only_the_gateway_holds(archive, owner):
    conversation, *_ = await _opened(archive)
    # Ended and not held, so the trigger accepts both; the policies must refuse them.
    await owner.execute("UPDATE conversations SET ended_at = $1", NOW)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _decide(conversation.conversation_id, "erase")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _decide(
            conversation.conversation_id,
            "hold_on",
            dsn=RETENTION_DSN,
            password=RETENTION_PASSWORD,
        )
    assert await owner.fetchval("SELECT count(*) FROM retention_decisions") == 0


async def test_erase_refuses_a_held_or_live_conversation(archive, owner):
    conversation, *_ = await _opened(archive)
    with pytest.raises(asyncpg.RaiseError, match="conversation_live"):
        await _decide(
            conversation.conversation_id,
            "erase",
            dsn=RETENTION_DSN,
            password=RETENTION_PASSWORD,
        )
    await owner.execute("UPDATE conversations SET ended_at = $1", NOW)
    await _decide(conversation.conversation_id, "hold_on")
    with pytest.raises(asyncpg.RaiseError, match="legal_hold_set"):
        await _decide(
            conversation.conversation_id,
            "erase",
            dsn=RETENTION_DSN,
            password=RETENTION_PASSWORD,
        )


async def test_a_shredded_conversation_takes_no_decision_wrap_or_entry(archive, owner):
    conversation, *_ = await _opened(archive)
    await owner.execute("UPDATE conversations SET shredded_at = $1", NOW)
    with pytest.raises(asyncpg.RaiseError, match="conversation_shredded"):
        await _decide(conversation.conversation_id, "hold_on")
    with pytest.raises(asyncpg.RaiseError, match="conversation_shredded"):
        await owner.execute(
            "INSERT INTO key_wraps SELECT tenant_id, key_id, 'user', 'other', blob,"
            " creator_ref, creator_signature, granted_at FROM key_wraps LIMIT 1"
        )
    with pytest.raises(asyncpg.RaiseError, match="conversation_shredded"):
        await owner.execute(
            "INSERT INTO chain_entries SELECT tenant_id, conversation_id, seq + 1,"
            " gen_random_uuid(), kind, window_id, key_id, objects, prev_hash, hash,"
            " signer_key_id, signature, created_at FROM chain_entries LIMIT 1"
        )


async def test_another_tenants_conversation_is_not_found(archive):
    conversation, *_ = await _opened(archive)
    with pytest.raises(asyncpg.NoDataFoundError):
        await _as(
            APP_DSN,
            APP_PASSWORD,
            "INSERT INTO retention_decisions (tenant_id, decision_id, conversation_id, at,"
            " actor_sub, kind, reason) VALUES ($1, $2, $3, $4, 'sup', 'hold_on', 'r')",
            "tenant-b",
            uuid.uuid4(),
            uuid.UUID(conversation.conversation_id),
            NOW,
            tenant="tenant-b",
        )


async def test_the_replica_role_writes_only_its_own_site_and_deletes_nothing(archive):
    conversation, *_ = await _opened(archive)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _as(REPLICA_DSN, REPLICA_PASSWORD, "DELETE FROM key_wraps")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _as(REPLICA_DSN, REPLICA_PASSWORD, "UPDATE conversations SET shredded_at = now()")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _as(
            REPLICA_DSN,
            REPLICA_PASSWORD,
            "INSERT INTO site_clearances VALUES ($1, $2, 'primary', now())",
            TENANT,
            uuid.UUID(conversation.conversation_id),
        )
    await _as(
        REPLICA_DSN,
        REPLICA_PASSWORD,
        "INSERT INTO site_clearances VALUES ($1, $2, 'replica', now())",
        TENANT,
        uuid.UUID(conversation.conversation_id),
    )


async def test_each_worker_beats_for_its_own_site_and_the_gateway_reads_both(archive):
    beat = (
        "INSERT INTO retention_worker_status VALUES ($1, now(), 0, FALSE, 0)"
        " ON CONFLICT (site) DO UPDATE SET beat_at = EXCLUDED.beat_at"
    )
    await _as(RETENTION_DSN, RETENTION_PASSWORD, beat, "primary")
    await _as(REPLICA_DSN, REPLICA_PASSWORD, beat, "replica")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _as(REPLICA_DSN, REPLICA_PASSWORD, beat, "primary")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _as(RETENTION_DSN, RETENTION_PASSWORD, beat, "replica")
    rows = await _as(APP_DSN, APP_PASSWORD, "SELECT site FROM retention_worker_status")
    assert sorted(row["site"] for row in rows) == ["primary", "replica"]


WORKER_ROLES = {
    "retention": (RETENTION_DSN, RETENTION_PASSWORD),
    "replica": (REPLICA_DSN, REPLICA_PASSWORD),
}


@pytest.mark.parametrize("role", sorted(WORKER_ROLES))
async def test_no_worker_role_can_rewrite_the_audit_log(archive, role):
    dsn, password = WORKER_ROLES[role]
    for statement in ("UPDATE audit_events SET actor_sub = 'x'", "DELETE FROM audit_events"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await _as(dsn, password, statement)


async def test_workers_enumerate_tenants_and_the_gateway_cannot(archive):
    await _opened(archive)
    rows = await _as(RETENTION_DSN, RETENTION_PASSWORD, "SELECT * FROM recording_tenants()")
    assert [row[0] for row in rows] == [TENANT]
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _as(APP_DSN, APP_PASSWORD, "SELECT * FROM recording_tenants()")


@pytest.fixture
async def gateway(archive):
    base = await PostgresRecordingRepository.create(dsn=APP_DSN, password=APP_PASSWORD)
    yield PostgresRetentionDecisions(base.pool), base
    await base.close()


def _decision(conversation_id, kind="extend", until=None, tenant_id=TENANT):
    return RetentionDecision(
        tenant_id=tenant_id,
        decision_id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        at=NOW,
        actor_sub="sup",
        kind=kind,
        retain_until=until,
        reason="court order 12/34",
    )


async def test_a_decision_is_applied_and_audited_under_its_own_id(archive, gateway):
    decisions, base = gateway
    conversation, *_ = await _opened(archive)
    later = conversation.retention_until + timedelta(days=1)
    decision = _decision(conversation.conversation_id, until=later)

    summary = await decisions.decide(decision, "recording.retention.extended")

    assert summary.retention_until == later
    rows = await base.audit_rows(TENANT)
    assert chain_is_intact(rows)
    last = rows[-1].event
    assert (last.event_type, last.object_ref, last.actor_sub) == (
        "recording.retention.extended",
        decision.decision_id,
        "sup",
    )


@pytest.mark.parametrize("refusal", ["retention_not_extended", "no_conversation", "shredded"])
async def test_a_refused_decision_writes_nothing(archive, owner, gateway, refusal):
    decisions, _ = gateway
    conversation, *_ = await _opened(archive)
    decision = _decision(conversation.conversation_id, until=conversation.retention_until)
    if refusal == "no_conversation":
        decision = _decision(conversation.conversation_id, "hold_on", tenant_id="tenant-b")
    elif refusal == "shredded":
        await owner.execute("UPDATE conversations SET shredded_at = $1", NOW)
        decision = _decision(conversation.conversation_id, "hold_on")
    events = await owner.fetchval("SELECT count(*) FROM audit_events")

    with pytest.raises(RetentionRefusedError) as refused:
        await decisions.decide(decision, "recording.legal_hold.on")

    assert refused.value.code == {"shredded": "conversation_shredded"}.get(refusal, refusal)
    assert await owner.fetchval("SELECT count(*) FROM retention_decisions") == 0
    assert await owner.fetchval("SELECT count(*) FROM audit_events") == events


async def test_summaries_list_newest_first_and_page_by_their_start(archive, gateway):
    decisions, _ = gateway
    older, *_ = await _opened(archive)
    newer, *_ = await _opened(
        archive, dataclasses.replace(_conversation(), started_at=NOW + timedelta(hours=1))
    )

    first = await decisions.summaries(TENANT, limit=1, started_before=None)
    rest = await decisions.summaries(TENANT, limit=10, started_before=newer.started_at)

    assert [row.conversation_id for row in first] == [newer.conversation_id]
    assert [row.conversation_id for row in rest] == [older.conversation_id]
    assert await decisions.summaries("tenant-b", limit=10, started_before=None) == []
    assert await decisions.summary("tenant-b", older.conversation_id) is None


async def test_conversations_started_together_are_all_paged(archive, gateway):
    decisions, _ = gateway
    record = dataclasses.replace(_conversation(), started_at=NOW + timedelta(hours=2))
    first, *_ = await _opened(archive, record)
    second, *_ = await _opened(
        archive, dataclasses.replace(_conversation(), started_at=NOW + timedelta(hours=2))
    )
    third, *_ = await _opened(archive)

    seen, cursor = [], (None, None)
    for _ in range(4):
        page = await decisions.summaries(
            TENANT, limit=1, started_before=cursor[0], before_id=cursor[1]
        )
        if not page:
            break
        seen.append(page[0].conversation_id)
        cursor = (page[0].started_at, page[0].conversation_id)

    assert sorted(seen) == sorted(
        [first.conversation_id, second.conversation_id, third.conversation_id]
    )
    assert seen[-1] == third.conversation_id


async def test_a_conversation_not_found_is_audited(archive, gateway):
    decisions, base = gateway
    missing = str(uuid.uuid4())
    await decisions.record_not_found(TENANT, "sup", missing, NOW)
    last = (await base.audit_rows(TENANT))[-1].event
    assert (last.event_type, last.object_ref) == ("recording.retention.not_found", missing)


async def test_one_extension_reaches_at_most_8760_hours_by_the_databases_clock(archive, owner):
    conversation, *_ = await _opened(archive)
    now = datetime.now(timezone.utc)
    with pytest.raises(asyncpg.RaiseError, match="retention_too_far"):
        await _decide(conversation.conversation_id, "extend", until=now + timedelta(hours=8762))
    within = now + timedelta(hours=8760)
    await _decide(conversation.conversation_id, "extend", until=within)
    assert await owner.fetchval("SELECT retention_until FROM conversations") == within


async def test_a_conversations_retention_rows_are_indexed(owner):
    indexes = {
        row["indexname"]: row["indexdef"]
        for row in await owner.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN"
            " ('version_locks', 'retention_decisions')"
        )
    }
    assert "(tenant_id, conversation_id)" in indexes["version_locks_conversation"]
    assert "(tenant_id, conversation_id, kind, at)" in indexes["retention_decisions_conversation"]
