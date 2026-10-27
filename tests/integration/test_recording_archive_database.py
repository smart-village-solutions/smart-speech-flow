"""The archive tables enforce what the gateway assumes (spec §11, §13; migration 003).

Runs against the real apply.sh output, like test_recording_database.py.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from services.api_gateway.recording.archive_repository import (
    ConversationRecord,
    NewKey,
    PostgresArchiveRepository,
    WindowOpening,
)
from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.chain import (
    GENESIS,
    ChainObject,
    chain_is_intact,
    seal_entry,
)
from services.api_gateway.recording.conversation_keys import (
    Recipient,
    new_conversation_key,
    wrap_key,
)
from services.api_gateway.recording.repository import (
    PostgresRecordingRepository,
    RecordingStorageUnavailable,
)
from services.api_gateway.recording.secrets import gateway_key_id
from tests import recording_crypto_reference as ref

pytestmark = pytest.mark.integration

APP_DSN = os.environ.get("SSF_RECORDING_DATABASE_URL", "")
APP_PASSWORD = os.environ.get("SSF_RECORDING_DATABASE_PASSWORD") or None
OWNER_DSN = os.environ.get("SSF_RECORDING_OWNER_DATABASE_URL", "")
OWNER_PASSWORD = os.environ.get("SSF_RECORDING_OWNER_DATABASE_PASSWORD") or None

_BIND = "SELECT set_config('ssf.tenant_id', $1, TRUE)"
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
TENANT = "tenant-a"
GATEWAY = ref.private_key(7)
GATEWAY_PUBLIC = ref.public_point(7)
GATEWAY_ID = gateway_key_id(GATEWAY_PUBLIC)
RECOVERY = Recipient("recovery", "rk-1", ref.public_point(31), b"\x31" * 32)
_ARCHIVE_TABLES = (
    "chain_stamps, stored_objects, chain_entries, key_wraps, conversation_keys,"
    " recording_windows, conversations"
)


@pytest.fixture
async def owner():
    if not OWNER_DSN:
        pytest.skip("SSF_RECORDING_OWNER_DATABASE_URL is not set")
    connection = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    await connection.execute(f"TRUNCATE {_ARCHIVE_TABLES}, audit_events, gateway_signing_keys")
    yield connection
    await connection.close()


@pytest.fixture
async def archive(owner):
    base = await PostgresRecordingRepository.create(dsn=APP_DSN, password=APP_PASSWORD)
    await base.register_gateway_key(GATEWAY_ID, GATEWAY_PUBLIC, NOW)
    yield PostgresArchiveRepository(base.pool)
    await base.close()


def _conversation(tenant_id=TENANT) -> ConversationRecord:
    return ConversationRecord(
        tenant_id=tenant_id,
        conversation_id=str(uuid.uuid4()),
        session_ref="ref-1",
        employee_sub="alice",
        legal_basis="consent",
        timestamp_authority_url="https://tsa.test/tsr",
        started_at=NOW,
        retention_until=NOW + timedelta(hours=720),
    )


def _entry(conversation, seq, prev_hash, key_id, *, kind="message", window_id=None, objects=None):
    entry_id = str(uuid.uuid4())
    return seal_entry(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.conversation_id,
        seq=seq,
        entry_id=entry_id,
        kind=kind,
        window_id=window_id,
        key_id=key_id,
        objects=objects
        or (
            ChainObject(
                "record.json",
                f"{conversation.conversation_id}/{entry_id}/record.json",
                10,
                "aa" * 32,
            ),
        ),
        prev_hash=prev_hash,
        created_at=NOW,
        signing_key=GATEWAY,
        signer_key_id=GATEWAY_ID,
    )


def _new_key(conversation, epoch=1) -> tuple[NewKey, str]:
    key = new_conversation_key(epoch)
    wrap = wrap_key(
        key,
        RECOVERY,
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.conversation_id,
        signing_key=GATEWAY,
        signer_key_id=GATEWAY_ID,
    )
    return NewKey(key.key_id, epoch, NOW, (wrap,)), key.key_id


async def _opened(archive, conversation=None):
    conversation = conversation or _conversation()
    key, key_id = _new_key(conversation)
    window_id = str(uuid.uuid4())
    consent = _entry(conversation, 1, GENESIS, key_id, kind="consent", window_id=window_id)
    await archive.open_window(
        WindowOpening(
            conversation=conversation,
            new_conversation=True,
            window_id=window_id,
            opened_at=NOW,
            key=key,
            consent=consent,
            audit=AuditEvent(conversation.tenant_id, "guest", "recording.arming", window_id, NOW),
        )
    )
    return conversation, key_id, window_id, consent


async def test_a_yes_writes_conversation_window_key_wrap_consent_and_audit(archive, owner):
    conversation, key_id, window_id, consent = await _opened(archive)

    async with owner.transaction():
        counts = {
            table: await owner.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608
            for table in (
                "conversations",
                "recording_windows",
                "conversation_keys",
                "key_wraps",
                "chain_entries",
                "audit_events",
            )
        }
    assert set(counts.values()) == {1}
    assert await archive.conversation(TENANT, conversation.conversation_id) == conversation
    assert await archive.chain_state(TENANT, conversation.conversation_id) == (1, consent.hash, 1)


async def test_a_yes_that_fails_part_way_writes_nothing(archive, owner):
    conversation = _conversation()
    key, key_id = _new_key(conversation)
    consent = _entry(conversation, 1, GENESIS, key_id, kind="consent")
    unsigned = consent.__class__(**{**consent.__dict__, "signer_key_id": "gk-unknown"})

    with pytest.raises(RecordingStorageUnavailable):
        await archive.open_window(
            WindowOpening(
                conversation=conversation,
                new_conversation=True,
                window_id=str(uuid.uuid4()),
                opened_at=NOW,
                key=key,
                consent=unsigned,
                audit=AuditEvent(TENANT, "guest", "recording.arming", "w", NOW),
            )
        )

    assert await owner.fetchval("SELECT count(*) FROM conversations") == 0
    assert await owner.fetchval("SELECT count(*) FROM audit_events") == 0


async def test_appended_entries_form_an_intact_chain_with_a_new_epoch(archive):
    conversation, key_id, window_id, consent = await _opened(archive)
    second = _entry(conversation, 2, consent.hash, key_id, window_id=window_id)
    await archive.append_entry(second, None)
    key, new_key_id = _new_key(conversation, epoch=2)
    third = _entry(conversation, 3, second.hash, new_key_id, window_id=window_id)
    await archive.append_entry(third, key)

    chain = await archive.chain(TENANT, conversation.conversation_id)

    assert [entry.seq for entry in chain] == [1, 2, 3]
    assert chain == [consent, second, third]
    assert chain_is_intact(chain, {GATEWAY_ID: GATEWAY_PUBLIC})
    assert await archive.chain_state(TENANT, conversation.conversation_id) == (3, third.hash, 2)


async def test_a_second_entry_with_the_same_seq_is_refused(archive):
    conversation, key_id, _, consent = await _opened(archive)
    await archive.append_entry(_entry(conversation, 2, consent.hash, key_id), None)

    with pytest.raises(RecordingStorageUnavailable):
        await archive.append_entry(_entry(conversation, 2, consent.hash, key_id), None)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE chain_entries SET kind = 'failed'",
        "DELETE FROM chain_entries",
        "UPDATE stored_objects SET version_id = 'v-forged'",
        "DELETE FROM stored_objects",
        "UPDATE conversations SET retention_until = now()",
        "UPDATE conversations SET employee_sub = 'mallory'",
        "DELETE FROM key_wraps",
        "UPDATE chain_stamps SET head_hash = head_hash",
        "DELETE FROM chain_stamps",
    ],
)
async def test_the_application_role_cannot_rewrite_the_archive(archive, statement):
    conversation, _, consent_window, consent = await _opened(archive)
    await archive.record_stored(TENANT, consent.entry_id, "record.json", "v1", NOW)
    await archive.close_window(TENANT, conversation.conversation_id, consent_window, NOW, "stop")
    connection = await asyncpg.connect(APP_DSN, password=APP_PASSWORD)
    try:
        async with connection.transaction():
            await connection.execute(_BIND, TENANT)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(statement)
    finally:
        await connection.close()


async def test_another_tenant_sees_none_of_it(archive):
    conversation, _, _, _ = await _opened(archive)

    assert await archive.conversation("tenant-b", conversation.conversation_id) is None
    assert await archive.chain("tenant-b", conversation.conversation_id) == []


async def test_stored_objects_are_recorded_once_and_only_for_known_entries(archive):
    _, _, _, consent = await _opened(archive)

    assert await archive.record_stored(TENANT, consent.entry_id, "record.json", "v1", NOW)
    assert await archive.record_stored(TENANT, consent.entry_id, "record.json", "v1", NOW)
    assert not await archive.record_stored(TENANT, str(uuid.uuid4()), "record.json", "v9", NOW)
    assert await archive.stored_types(TENANT, consent.entry_id) == {"record.json"}


async def test_a_closed_window_is_stamped_only_once_all_its_entries_are_stored(archive):
    conversation, key_id, window_id, consent = await _opened(archive)
    two = (
        ChainObject("original.wav", "k/original.wav", 5, "bb" * 32),
        ChainObject("record.json", "k/record.json", 5, "cc" * 32),
    )
    message = _entry(conversation, 2, consent.hash, key_id, window_id=window_id, objects=two)
    await archive.append_entry(message, None)
    await archive.close_window(TENANT, conversation.conversation_id, window_id, NOW, "stop")
    later = NOW + timedelta(seconds=1)

    await archive.record_stored(TENANT, consent.entry_id, "record.json", "v1", NOW)
    await archive.record_stored(TENANT, message.entry_id, "record.json", "v2", NOW)
    assert await archive.pending_stamps(TENANT, later) == []

    await archive.record_stored(TENANT, message.entry_id, "original.wav", "v3", NOW)
    [stamp] = await archive.pending_stamps(TENANT, later)
    assert (stamp.head_seq, stamp.head_hash, stamp.url) == (2, message.hash, "https://tsa.test/tsr")

    await archive.defer_stamp(TENANT, stamp, later + timedelta(minutes=1))
    assert await archive.pending_stamps(TENANT, later) == []
    [deferred] = await archive.pending_stamps(TENANT, later + timedelta(minutes=1))
    assert deferred.attempts == 1

    await archive.save_stamp(TENANT, deferred, b"token", later)
    assert await archive.pending_stamps(TENANT, later + timedelta(hours=1)) == []
    [row] = await archive.stamps(TENANT, conversation.conversation_id)
    assert bytes(row["tsa_token"]) == b"token"


async def test_the_end_of_a_conversation_closes_a_window_left_open(archive, owner):
    conversation, _, window_id, _ = await _opened(archive)

    await archive.end_conversation(TENANT, conversation.conversation_id, NOW)

    row = await owner.fetchrow(
        "SELECT closed_at, close_reason FROM recording_windows WHERE window_id = $1",
        uuid.UUID(window_id),
    )
    assert (row["closed_at"], row["close_reason"]) == (NOW, "session_ended")


async def test_the_end_of_a_conversation_does_not_stamp_the_same_head_twice(archive):
    conversation, _, window_id, _ = await _opened(archive)

    await archive.close_window(TENANT, conversation.conversation_id, window_id, NOW, "stop")
    await archive.end_conversation(TENANT, conversation.conversation_id, NOW)

    assert len(await archive.stamps(TENANT, conversation.conversation_id)) == 1


async def test_pauses_are_kept_in_order_with_their_resumption(archive, owner):
    conversation, _, window_id, _ = await _opened(archive)

    await archive.note_pause(TENANT, conversation.conversation_id, window_id, NOW, "liveness")
    await archive.note_resume(TENANT, window_id, NOW + timedelta(seconds=5))
    await archive.note_pause(TENANT, conversation.conversation_id, window_id, NOW, "storage")

    pauses = await owner.fetchval(
        "SELECT pauses::text FROM recording_windows WHERE window_id = $1", uuid.UUID(window_id)
    )
    import json

    assert [(p["reason"], p["resumed_at"] is not None) for p in json.loads(pauses)] == [
        ("liveness", True),
        ("storage", False),
    ]
    assert await owner.fetchval("SELECT incomplete FROM conversations") is True
