"""The resharing repository's branches over a scripted connection, for the unit run (§9.7)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from services.api_gateway.recording import resharing_repository
from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.ceremony_model import (
    CeremonyDealer,
    CeremonyError,
    CeremonyParticipant,
    CeremonyRecord,
    CeremonySnapshot,
    ConfirmationRecord,
)
from services.api_gateway.recording.ceremony_repository import PostgresCeremonyRepository
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from tests import recording_crypto_reference as ref
from tests.test_recording_archive_access_repository import ScriptedConnection, ScriptedPool

TENANT = "tenant-a"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
KEY_ID = str(uuid.uuid4())
RESHARING = str(uuid.uuid4())
GENERATION = "SELECT r.holders_ceremony_id"
OPEN = "status = 'open' ORDER BY request_id FOR UPDATE"
KEY_ROW = "AND status = 'active' FOR UPDATE"
HOLDERS_LOCK = "AND status = 'active' FOR SHARE"
PREVIOUS = bytes([1]) * 32


def _store(answers: dict[str, object]):
    connection = ScriptedConnection(answers)
    return PostgresCeremonyRepository(ScriptedPool(connection)), connection


def _participant(index: int, ref_: str) -> CeremonyParticipant:
    return CeremonyParticipant(
        index,
        ref_,
        "custodian",
        None,
        ref.public_point(index),
        ref.public_point(20 + index),
        bytes([index]) * 32,
    )


def _snapshot() -> CeremonySnapshot:
    ceremony = CeremonyRecord(
        tenant_id=TENANT,
        ceremony_id=RESHARING,
        k=2,
        started_by="olga",
        started_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        status="confirming",
        gateway_keys=(),
        transcript_hash=bytes(32),
        kind="resharing",
        recovery_key_id=KEY_ID,
        previous_transcript_hash=bytes([1]) * 32,
    )
    participants = (_participant(1, "bernd"), _participant(2, "dora"), _participant(3, "emil"))
    confirmations = tuple(
        ConfirmationRecord(p.holder_index, bytes(64), "{}", NOW, (1, 2)) for p in participants
    )
    return CeremonySnapshot(
        ceremony, participants, (), confirmations, (CeremonyDealer(1, "anna", "custodian"),)
    )


def _row(**values) -> dict:
    return values


async def test_no_active_key_has_no_holder_generation():
    store, _ = _store({})
    assert await store.holder_generation(TENANT) is None


async def test_the_holder_generation_comes_from_the_key_pointer():
    holders = uuid.uuid4()
    participant = _row(
        holder_index=1,
        holder_ref="anna",
        kind="custodian",
        display_name="Anna",
        enc_pub=ref.public_point(1),
        sig_pub=ref.public_point(2),
        fingerprint=bytes(32),
    )
    store, _ = _store(
        {
            GENERATION: _row(holders_ceremony_id=holders, holders_transcript_hash=bytes(32), k=2),
            "FROM ceremony_participants": [participant],
            "FROM recovery_shares": [_row(holder_index=1, holder_public_share=ref.public_point(3))],
        }
    )
    generation = await store.holder_generation(TENANT)
    assert (generation.ceremony_id, generation.k) == (str(holders), 2)
    assert generation.public_shares == {1: ref.public_point(3)}
    assert generation.holder(1).holder_ref == "anna"
    assert generation.holder(2) is None


async def test_each_current_holder_is_fresh_kept_or_lost():
    rows = [_row(holder_ref="anna", state="kept"), _row(holder_ref="bernd", state="fresh")]
    store, connection = _store({"ELSE 'lost' END AS state": rows})
    assert await store.holder_states(TENANT) == {"anna": "kept", "bernd": "fresh"}
    assert "p.ceremony_id = r.holders_ceremony_id" in connection.calls[-1]


async def test_dealer_material_is_the_share_and_the_listed_key():
    key = _row(
        tenant_id=TENANT,
        user_sub="anna",
        key_version=1,
        enc_pub=b"e",
        sig_pub=b"s",
        fingerprint=bytes(32),
        encrypted_private=b"blob",
        created_at=NOW,
        encrypted_share="{}",
    )
    store, connection = _store({"AND s.holder_index = $1": key})
    material = await store.dealer_material(TENANT, 1, "anna")
    assert (material.dealer_index, material.encrypted_share, material.key.key_version) == (
        1,
        "{}",
        1,
    )
    assert "u.retired_at IS NULL OR u.encrypted_private IS NOT NULL" in connection.calls[-1]
    empty, _ = _store({})
    assert await empty.dealer_material(TENANT, 1, "anna") is None


async def test_a_resharing_is_inserted_with_its_dealers_and_audit():
    store, connection = _store({HOLDERS_LOCK: PREVIOUS})
    snapshot = _snapshot()
    await store.create_resharing(
        snapshot.ceremony,
        snapshot.participants,
        snapshot.dealers,
        [AuditEvent(TENANT, "olga", "ceremony_started", "c", NOW)],
    )
    order = [
        next(i for i, c in enumerate(connection.calls) if fragment in c)
        for fragment in (
            "UPDATE recovery_ceremonies SET status = 'aborted'",
            "INSERT INTO recovery_ceremonies",
            "INSERT INTO ceremony_participants",
            "INSERT INTO ceremony_dealers",
            "INSERT INTO audit_events",
        )
    ]
    assert order == sorted(order)


async def test_a_second_open_ceremony_is_a_conflict_not_an_outage():
    store, _ = _store(
        {HOLDERS_LOCK: PREVIOUS, "INSERT INTO recovery_ceremonies": asyncpg.UniqueViolationError("one")}
    )
    snapshot = _snapshot()
    with pytest.raises(CeremonyError) as caught:
        await store.create_resharing(snapshot.ceremony, (), (), [])
    assert caught.value.code == "CEREMONY_IN_PROGRESS"


async def test_a_driver_failure_is_storage_unavailable():
    with pytest.raises(RecordingStorageUnavailable):
        await PostgresCeremonyRepository(ScriptedPool(None)).holder_generation(TENANT)


async def test_the_chain_reads_every_active_generation_of_the_key():
    store, connection = _store({})
    assert await store.chain(TENANT, KEY_ID) == []
    assert "recovery_key_id = $1" in connection.calls[-1]


async def test_activation_that_fails_the_final_check_aborts_and_writes_nothing_else(monkeypatch):
    monkeypatch.setattr(resharing_repository, "end_to_end_holds", lambda *_: False)
    connection = ScriptedConnection(
        {KEY_ROW: _row(key_id=uuid.UUID(KEY_ID), recovery_public_key=b"x", holders_transcript_hash=PREVIOUS)}
    )
    step = AuditEvent(TENANT, "emil", "ceremony_confirmed", "c", NOW)
    assert (
        await resharing_repository.activate_resharing(connection, _snapshot(), [step]) == "aborted"
    )
    assert any("SET status = 'aborted'" in c for c in connection.calls)
    assert not any("recovery_shares" in c or "recovery_requests" in c for c in connection.calls)


async def test_activation_without_its_key_aborts():
    connection = ScriptedConnection({})
    step = AuditEvent(TENANT, "emil", "ceremony_confirmed", "c", NOW)
    assert (
        await resharing_repository.activate_resharing(connection, _snapshot(), [step]) == "aborted"
    )


async def test_activation_keeps_the_lock_order_and_audits_once(monkeypatch):
    monkeypatch.setattr(resharing_repository, "end_to_end_holds", lambda *_: True)
    monkeypatch.setattr(
        resharing_repository, "new_public_shares", lambda s: {1: b"1", 2: b"2", 3: b"3"}
    )
    request = uuid.uuid4()
    connection = ScriptedConnection(
        {
            KEY_ROW: _row(key_id=uuid.UUID(KEY_ID), recovery_public_key=b"x", holders_transcript_hash=PREVIOUS),
            OPEN: [_row(request_id=request, lapsed=False)],
            "WHERE status <> ALL": [_row(ceremony_id=uuid.UUID(RESHARING))],
        }
    )
    step = AuditEvent(TENANT, "emil", "ceremony_confirmed", "c", NOW)
    assert (
        await resharing_repository.activate_resharing(connection, _snapshot(), [step]) == "active"
    )
    order = [
        next(i for i, c in enumerate(connection.calls) if fragment in c)
        for fragment in (
            KEY_ROW,
            OPEN,
            "FROM conversations c",
            "DELETE FROM recovery_partials",
            "UPDATE recovery_requests",
            "DELETE FROM recovery_shares",
            "UPDATE recovery_keys SET holders_ceremony_id",
            "UPDATE user_keys SET encrypted_private = NULL",
            "SET status = 'active'",
            "UPDATE ceremony_dealings SET subshares",
            "INSERT INTO audit_events",
        )
    ]
    assert order == sorted(order)
    audits = [c for c in connection.calls if "INSERT INTO audit_events" in c]
    assert len(audits) == 3  # the confirmation, the cancelled request, the resharing


async def test_activation_with_nothing_open_skips_the_request_writes(monkeypatch):
    monkeypatch.setattr(resharing_repository, "end_to_end_holds", lambda *_: True)
    monkeypatch.setattr(
        resharing_repository, "new_public_shares", lambda s: {1: b"1", 2: b"2", 3: b"3"}
    )
    connection = ScriptedConnection(
        {KEY_ROW: _row(key_id=uuid.UUID(KEY_ID), recovery_public_key=b"x", holders_transcript_hash=PREVIOUS)}
    )
    step = AuditEvent(TENANT, "emil", "ceremony_confirmed", "c", NOW)
    assert (
        await resharing_repository.activate_resharing(connection, _snapshot(), [step]) == "active"
    )
    assert not any("recovery_partials" in c for c in connection.calls)


async def test_a_resharing_of_holders_since_replaced_is_refused_before_any_write():
    store, connection = _store({HOLDERS_LOCK: bytes(32)})
    snapshot = _snapshot()
    with pytest.raises(CeremonyError) as caught:
        await store.create_resharing(snapshot.ceremony, (), (), [])
    assert caught.value.code == "HOLDERS_CHANGED"
    assert not any(c.startswith(("INSERT", "UPDATE")) for c in connection.calls)


async def test_activation_of_a_resharing_whose_holders_moved_on_aborts_as_chain_invalid():
    connection = ScriptedConnection(
        {KEY_ROW: _row(key_id=uuid.UUID(KEY_ID), recovery_public_key=b"x", holders_transcript_hash=bytes(32))}
    )
    step = AuditEvent(TENANT, "emil", "ceremony_confirmed", "c", NOW)
    assert await resharing_repository.activate_resharing(connection, _snapshot(), [step]) == "aborted"
    assert not any("recovery_shares" in c for c in connection.calls)
