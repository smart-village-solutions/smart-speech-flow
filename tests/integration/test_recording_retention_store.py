"""The retention workers' database access, as each site's role (spec §16.1).

Same environment as test_recording_retention_database.py.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import pytest

from services.api_gateway.recording.repository import (
    PostgresRecordingRepository,
    RecordingStorageUnavailable,
)
from services.api_gateway.recording.retention.decisions_repository import (
    PostgresRetentionDecisions,
)
from services.api_gateway.recording.retention.settings import WorkerSettings
from services.api_gateway.recording.retention.store import LockState, PostgresRetentionStore
from services.api_gateway.recording.storage.sigv4 import Credentials
from tests.integration import test_recording_archive_database as archive_database
from tests.integration.test_recording_archive_database import NOW, TENANT, _opened

pytestmark = pytest.mark.integration

owner = archive_database.owner
archive = archive_database.archive

ROLES = {
    "primary": (
        os.environ.get("SSF_RECORDING_RETENTION_DATABASE_URL", ""),
        os.environ.get("SSF_RECORDING_RETENTION_DATABASE_PASSWORD", ""),
    ),
    "replica": (
        os.environ.get("SSF_RECORDING_REPLICA_DATABASE_URL", ""),
        os.environ.get("SSF_RECORDING_REPLICA_DATABASE_PASSWORD", ""),
    ),
}
APP_DSN = os.environ.get("SSF_RECORDING_DATABASE_URL", "")
APP_PASSWORD = os.environ.get("SSF_RECORDING_DATABASE_PASSWORD") or None


def _settings(site: str) -> WorkerSettings:
    dsn, password = ROLES[site]
    if not dsn:
        pytest.skip("the retention role URLs are not set")
    return WorkerSettings(
        site=site,  # type: ignore[arg-type]
        endpoint="http://seaweedfs.test:8333",
        credentials=Credentials("unused", "unused"),
        database_url=dsn,
        database_password=password,
        state_dir=Path("/nonexistent"),
    )


@pytest.fixture
async def stores(archive):
    opened = {site: await PostgresRetentionStore.connect(_settings(site)) for site in ROLES}
    yield opened
    for store in opened.values():
        await store.close()


async def _stored(archive, conversation=None):
    """An opened conversation whose consent object the store confirmed."""
    conversation, _, _, consent = await _opened(archive, conversation)
    await archive.record_stored(TENANT, consent.entry_id, "record.json", "v-consent", NOW)
    return conversation, consent


async def _decide(conversation_id: str, kind: str, at=NOW, until=None) -> None:
    connection = await asyncpg.connect(APP_DSN, password=APP_PASSWORD)
    try:
        async with connection.transaction():
            await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
            await connection.execute(
                "INSERT INTO retention_decisions (tenant_id, decision_id, conversation_id, at,"
                " actor_sub, kind, retain_until, reason) VALUES ($1, $2, $3, $4, 'sup', $5, $6,"
                " 'r')",
                TENANT,
                uuid.uuid4(),
                uuid.UUID(conversation_id),
                at,
                kind,
                until,
            )
    finally:
        await connection.close()


async def test_each_site_discovers_its_own_row_once(archive, owner, stores):
    conversation, consent = await _stored(archive)

    assert await stores["primary"].discover(TENANT, NOW) == 1
    assert await stores["primary"].discover(TENANT, NOW) == 0
    assert await stores["replica"].discover(TENANT, NOW) == 1

    sites = await owner.fetch("SELECT site, version_id FROM version_locks ORDER BY site")
    assert [(row["site"], row["version_id"]) for row in sites] == [
        ("primary", "v-consent"),
        ("replica", "v-consent"),
    ]
    [replica_row] = await stores["replica"].due_versions(TENANT, NOW)
    assert replica_row.key == f"{conversation.conversation_id}/{consent.entry_id}/record.json"


async def test_a_due_version_carries_its_conversations_state_and_hold_decisions(archive, stores):
    conversation, _ = await _stored(archive)
    await stores["primary"].discover(TENANT, NOW)
    [row] = await stores["primary"].due_versions(TENANT, NOW)
    assert row.retention_until == conversation.retention_until
    assert (row.legal_hold, row.shredded_at, row.checked_at) == (False, None, None)
    assert (row.hold_on_at, row.hold_off_at) == (None, None)

    await _decide(conversation.conversation_id, "hold_on", NOW + timedelta(minutes=1))
    await _decide(conversation.conversation_id, "hold_off", NOW + timedelta(minutes=2))
    await _decide(conversation.conversation_id, "hold_on", NOW + timedelta(minutes=3))

    # Each decision made the row due by the database's clock.
    [row] = await stores["primary"].due_versions(TENANT, datetime.now(timezone.utc))
    assert row.legal_hold is True
    assert row.hold_on_at == NOW + timedelta(minutes=3)
    assert row.hold_off_at == NOW + timedelta(minutes=2)


async def test_another_tenant_sees_no_versions(archive, stores):
    await _stored(archive)
    await stores["primary"].discover(TENANT, NOW)
    assert await stores["primary"].due_versions("tenant-b", NOW) == []
    assert await stores["primary"].discover("tenant-b", NOW) == 0


async def test_failures_back_off_and_a_success_clears_them(archive, owner, stores):
    await _stored(archive)
    store = stores["primary"]
    await store.discover(TENANT, NOW)
    [row] = await store.due_versions(TENANT, NOW)

    await store.record_failure(row, NOW)
    first = await owner.fetchrow("SELECT * FROM version_locks")
    [row] = await store.due_versions(TENANT, first["next_attempt_at"])
    await store.record_failure(row, NOW + timedelta(minutes=5))
    second = await owner.fetchrow("SELECT * FROM version_locks")

    assert first["next_attempt_at"] == NOW + timedelta(seconds=60)
    assert second["next_attempt_at"] == NOW + timedelta(minutes=5, seconds=120)
    assert first["failing_since"] == second["failing_since"] == NOW
    assert await store.overdue_since(TENANT, NOW) == NOW

    [row] = await store.due_versions(TENANT, second["next_attempt_at"])
    later = NOW + timedelta(days=1)
    await store.record(row, LockState(NOW, row.retention_until, False, None, None), later)
    cleared = await owner.fetchrow("SELECT * FROM version_locks")
    assert (cleared["attempts"], cleared["failing_since"]) == (0, None)
    assert cleared["locked_until"] == row.retention_until
    assert cleared["next_attempt_at"] == later
    assert await store.overdue_since(TENANT, NOW) is None
    # Due and not yet taken, it is owed from when it fell due.
    assert await store.overdue_since(TENANT, later + timedelta(hours=1)) == later


async def test_the_backoff_stops_growing_at_its_ceiling(archive, owner, stores):
    await _stored(archive)
    store = stores["primary"]
    await store.discover(TENANT, NOW)
    await owner.execute("UPDATE version_locks SET attempts = 5000")
    [row] = await store.due_versions(TENANT, NOW)
    await store.record_failure(row, NOW)
    assert await owner.fetchval("SELECT next_attempt_at FROM version_locks") == NOW + timedelta(
        hours=6
    )


async def test_a_decision_made_while_a_row_is_worked_on_is_not_overwritten(archive, owner, stores):
    conversation, _ = await _stored(archive)
    store = stores["primary"]
    await store.discover(TENANT, NOW)
    [row] = await store.due_versions(TENANT, NOW)

    # A decision's own time comes from the gateway; the row falls due by the database's clock.
    await _decide(conversation.conversation_id, "hold_on", NOW + timedelta(days=1000))
    await store.record(row, LockState(NOW, None, False, None, None), NOW + timedelta(days=365))
    reset = await owner.fetchval("SELECT next_attempt_at FROM version_locks")
    assert abs(reset - datetime.now(timezone.utc)) < timedelta(minutes=1)

    [row] = await store.due_versions(TENANT, reset)
    await _decide(conversation.conversation_id, "hold_off", NOW)
    await store.record_failure(row, NOW + timedelta(days=365))
    again = await owner.fetchval("SELECT next_attempt_at FROM version_locks")
    assert again > reset and abs(again - datetime.now(timezone.utc)) < timedelta(minutes=1)


async def test_the_replica_cannot_reach_the_primarys_rows(archive, owner, stores):
    await _stored(archive)
    await stores["primary"].discover(TENANT, NOW)
    assert await stores["replica"].due_versions(TENANT, NOW) == []
    [row] = await stores["primary"].due_versions(TENANT, NOW)
    # The replica's role, claiming to be the primary: row-level security still hides the row.
    impostor = PostgresRetentionStore(stores["replica"].pool, "primary")
    assert await impostor.due_versions(TENANT, NOW) == []
    await impostor.record(row, LockState(NOW, None, True, NOW, NOW), NOW)
    untouched = await owner.fetchrow("SELECT * FROM version_locks")
    assert (untouched["held"], untouched["deleted_at"]) == (False, None)


async def test_each_site_beats_only_for_itself(archive, owner, stores):
    await stores["primary"].beat(NOW, 12.5, False, 1)
    await stores["primary"].beat(NOW + timedelta(minutes=5), 0.0, True, 0)
    await stores["replica"].beat(NOW, 0.0, False, 0)
    rows = await owner.fetch("SELECT * FROM retention_worker_status ORDER BY site")
    assert [(row["site"], row["beat_at"], row["halted"]) for row in rows] == [
        ("primary", NOW + timedelta(minutes=5), True),
        ("replica", NOW, False),
    ]
    impostor = PostgresRetentionStore(stores["replica"].pool, "primary")
    with pytest.raises(RecordingStorageUnavailable) as refused:
        await impostor.beat(NOW, 0.0, False, 0)
    assert "postgresql://" not in str(refused.value)


async def test_tenants_and_audit_marks(archive, owner, stores):
    await _stored(archive)
    assert await stores["replica"].tenants() == [TENANT]
    last = await owner.fetchrow("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1")
    mark = await stores["replica"].audit_mark(TENANT)
    assert (mark.seq, mark.hash) == (last["seq"], bytes(last["hash"]).hex())
    assert await stores["primary"].audit_hash_at(TENANT, mark.seq) == mark.hash
    assert await stores["primary"].audit_hash_at(TENANT, mark.seq + 1) is None
    assert await stores["primary"].audit_mark("tenant-b") is None


async def _held_after_check(store, owner, *, legal_hold=False, hold_off=None):
    """A version this site found held, as after a restore re-read it."""
    [row] = await store.due_versions(TENANT, NOW)
    await store.record(row, LockState(NOW, row.retention_until, True, NOW, None), NOW)
    if legal_hold:
        await owner.execute("UPDATE conversations SET legal_hold = TRUE")
    if hold_off is not None:
        await _decide(row.conversation_id, "hold_off", hold_off)
    return row


async def test_a_restore_re_read_resets_only_this_sites_rows(archive, owner, stores):
    await _stored(archive)
    for site in ("primary", "replica"):
        await stores[site].discover(TENANT, NOW)
        [row] = await stores[site].due_versions(TENANT, NOW)
        await stores[site].record(
            row, LockState(NOW, NOW, False, None, None), NOW + timedelta(days=9)
        )

    await stores["replica"].recheck_all(TENANT, NOW)

    rows = await owner.fetch(
        "SELECT site, checked_at, next_attempt_at FROM version_locks ORDER BY site"
    )
    assert [(r["site"], r["checked_at"], r["next_attempt_at"]) for r in rows] == [
        ("primary", NOW, NOW + timedelta(days=9)),
        ("replica", None, NOW),
    ]


@pytest.mark.parametrize(
    ("legal_hold", "hold_off", "counted"),
    [
        (False, None, 1),
        (True, None, 0),
        (False, NOW + timedelta(days=1), 0),
        (False, NOW - timedelta(days=1), 1),
    ],
)
async def test_a_hold_with_nothing_to_lift_it_is_a_mismatch(
    archive, owner, stores, legal_hold, hold_off, counted
):
    await _stored(archive)
    store = stores["primary"]
    await store.discover(TENANT, NOW)
    await _held_after_check(store, owner, legal_hold=legal_hold, hold_off=hold_off)
    assert await store.hold_mismatches(TENANT) == counted
    assert await stores["replica"].hold_mismatches(TENANT) == 0


async def test_a_restore_lists_held_extended_and_unread_versions(archive, owner, stores):
    held, _ = await _stored(archive)
    store = stores["primary"]
    await store.discover(TENANT, NOW)
    await _held_after_check(store, owner)
    assert await store.restore_conflicts(TENANT) == [
        (held.conversation_id, "held_without_hold", held.retention_until)
    ]

    await owner.execute(
        "UPDATE version_locks SET held = FALSE, locked_until = $1",
        held.retention_until + timedelta(days=4),
    )
    assert await store.restore_conflicts(TENANT) == [
        (held.conversation_id, "locked_beyond_date", held.retention_until + timedelta(days=4))
    ]
    await owner.execute(
        "UPDATE version_locks SET locked_until = $1", held.retention_until + timedelta(days=2)
    )
    assert await store.restore_conflicts(TENANT) == []

    await store.recheck_all(TENANT, NOW)
    [(conversation_id, reason, _)] = await store.restore_conflicts(TENANT)
    assert (conversation_id, reason) == (held.conversation_id, "not_yet_read")
    assert await stores["replica"].restore_conflicts(TENANT) == []


async def test_the_gateway_reads_both_sites_heartbeats(archive, stores):
    await stores["replica"].beat(NOW, 0.0, False, 0)
    await stores["primary"].beat(NOW, 30.0, True, 2)
    base = await PostgresRecordingRepository.create(dsn=APP_DSN, password=APP_PASSWORD)
    try:
        statuses = await PostgresRetentionDecisions(base.pool).worker_statuses()
    finally:
        await base.close()
    assert [(s.site, s.failing_seconds, s.halted, s.hold_mismatches) for s in statuses] == [
        ("primary", 30.0, True, 2),
        ("replica", 0.0, False, 0),
    ]
