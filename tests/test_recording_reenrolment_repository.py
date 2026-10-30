"""The swap's branches over a scripted connection, for the unit run (spec §9.6)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.reenrolment_repository import PostgresKeyReenrolment
from services.api_gateway.recording.repository import RecordingStorageUnavailable, UserKeyRecord
from tests.test_recording_archive_access_repository import ScriptedConnection, ScriptedPool

TENANT = "tenant-a"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
ACTIVE = "retired_at IS NULL FOR UPDATE"
CEREMONY = "status IN ('dealing', 'confirming')"
CUSTODIAN = "SELECT r.key_id FROM recovery_keys"
OPEN = "status = 'open' ORDER BY request_id FOR UPDATE"
WRAPS = "DELETE FROM key_wraps"
OLD = {"key_version": 1, "fingerprint": b"\x01" * 32}
RECORD = UserKeyRecord(TENANT, "alice", 2, b"e", b"s", b"\x07" * 32, b"sealed", NOW)


def _store(answers: dict[str, object]):
    connection = ScriptedConnection(answers)
    return PostgresKeyReenrolment(ScriptedPool(connection)), connection


def _events(connection) -> int:
    return sum("INSERT INTO audit_events" in call for call in connection.calls)


@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ({}, "key_not_enrolled"),
        ({ACTIVE: {**OLD, "key_version": 2}}, "key_changed"),
        ({ACTIVE: OLD, CEREMONY: True}, "ceremony_in_progress"),
    ],
)
async def test_a_refused_swap_writes_nothing(answers, code):
    store, connection = _store(answers)
    assert await store.swap(RECORD, 1, NOW) == Refused(code)
    assert not any(call.startswith(("UPDATE", "DELETE", "INSERT")) for call in connection.calls)


async def test_a_swap_with_nothing_open_retires_inserts_and_audits():
    store, connection = _store({ACTIVE: OLD, WRAPS: [{"key_id": uuid.uuid4()}]})
    assert await store.swap(RECORD, 1, NOW) is None
    assert any("UPDATE user_keys SET retired_at" in call for call in connection.calls)
    assert any("INSERT INTO user_keys" in call for call in connection.calls)
    assert not any("UPDATE recovery_requests" in call for call in connection.calls)
    assert _events(connection) == 2  # one deleted wrap, then key_reenrolled


async def test_a_custodian_swap_cancels_requests_and_audits_the_stale_share():
    request = uuid.uuid4()
    store, connection = _store(
        {ACTIVE: OLD, OPEN: [{"request_id": request, "lapsed": False}], CUSTODIAN: uuid.uuid4()}
    )
    assert await store.swap(RECORD, 1, NOW) is None
    cancel = next(i for i, c in enumerate(connection.calls) if "UPDATE recovery_requests" in c)
    delete = next(i for i, c in enumerate(connection.calls) if c.startswith(WRAPS))
    assert cancel < delete  # the order the wraps-store race needs
    assert _events(connection) == 3  # cancelled, share stale, key_reenrolled


async def test_the_impact_without_a_recovery_key_counts_nothing():
    store, _ = _store({"fingerprint FROM user_keys": b"\x01" * 32})
    impact = await store.impact(TENANT, "alice")
    assert (impact.custodian, impact.k, impact.usable_after) == (False, None, None)


async def test_a_driver_failure_is_storage_unavailable():
    with pytest.raises(RecordingStorageUnavailable):
        await PostgresKeyReenrolment(ScriptedPool(None)).swap(RECORD, 1, NOW)
