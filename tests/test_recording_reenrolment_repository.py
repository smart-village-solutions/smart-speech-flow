"""The swap's branches over a scripted connection, for the unit run (spec §9.6)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.reenrolment_repository import PostgresKeyReenrolment
from services.api_gateway.recording.repository import RecordingStorageUnavailable, UserKeyRecord
from tests.recording_swap import swap_key
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
    return ScriptedPool(connection), connection


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
    assert await swap_key(store, RECORD, 1, NOW) == Refused(code)
    assert not any(call.startswith(("UPDATE", "DELETE", "INSERT")) for call in connection.calls)


async def test_supersession_preserves_grants_blobs_and_assignments():
    store, connection = _store({ACTIVE: OLD})
    assert await swap_key(store, RECORD, 1, NOW) is None
    assert any("superseded_at" in call for call in connection.calls)
    assert any("INSERT INTO user_keys" in call for call in connection.calls)
    assert not any(call.startswith(("DELETE", "UPDATE verifications")) for call in connection.calls)
    assert not any("SET encrypted_private" in call for call in connection.calls)
    assert _events(connection) == 1


async def test_the_impact_without_a_recovery_key_counts_nothing():
    store, _ = _store({"fingerprint FROM user_keys": b"\x01" * 32})
    impact = await PostgresKeyReenrolment(store).impact(TENANT, "alice")
    assert (impact.custodian, impact.k, impact.usable_after) == (False, None, None)


async def test_a_driver_failure_is_storage_unavailable():
    with pytest.raises(RecordingStorageUnavailable):
        await swap_key(ScriptedPool(None), RECORD, 1, NOW)
