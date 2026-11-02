"""The pending store's branches over a scripted connection, for the unit run (spec §9.9).

The database behaviour itself is proven in
tests/integration/test_recording_reenrolment_email_database.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.key_confirmation_repository import (
    LinkDetails,
    PendingKey,
    PostgresKeyConfirmations,
)
from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.repository import RecordingStorageUnavailable, UserKeyRecord
from tests.test_recording_archive_access_repository import ScriptedConnection, ScriptedPool

TENANT = "tenant-a"
NOW = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=30)
HASH = b"\x09" * 32
ACTIVE = "retired_at IS NULL FOR UPDATE"
CEREMONY = "status IN ('dealing', 'confirming')"
EARLIER = "DELETE FROM user_key_reenrolments WHERE user_sub = $1"
INSERT = "INSERT INTO user_key_reenrolments"
SWEEP_LOCK = "pg_try_advisory_xact_lock"
SWEEP = "WHERE expires_at <= $1"
READ = "SELECT user_sub, key_version, fingerprint"
TAKE = "DELETE FROM user_key_reenrolments WHERE token_hash = $1 RETURNING user_sub, key_version, fingerprint"
OWNER = "SELECT user_sub FROM user_key_reenrolments"
CONFIRM_TAKE = "WHERE token_hash = $1 AND user_sub = $2"
OLD = {"key_version": 1, "fingerprint": b"\x01" * 32, "email": "alice@example.org"}
PENDING = {
    "user_sub": "alice",
    "key_version": 2,
    "fingerprint": b"\x07" * 32,
    "requested_at": NOW,
    "expires_at": LATER,
}
FULL = {
    **PENDING,
    "enc_pub": b"e",
    "sig_pub": b"s",
    "encrypted_private": b"sealed",
    "email": "alice@example.org",
    "replaces_version": 1,
}
RECORD = UserKeyRecord(TENANT, "alice", 2, b"e", b"s", b"\x07" * 32, b"sealed", NOW)


def _store(answers: dict[str, object]):
    connection = ScriptedConnection(answers)
    return PostgresKeyConfirmations(ScriptedPool(connection)), connection


def _events(connection) -> int:
    return sum("INSERT INTO audit_events" in call for call in connection.calls)


def _wrote(connection, fragment: str) -> bool:
    return any(fragment in call for call in connection.calls)


async def test_a_hold_pins_the_active_keys_address():
    store, connection = _store({ACTIVE: OLD})
    assert await store.hold(RECORD, 1, HASH, LATER) == "alice@example.org"
    assert _wrote(connection, INSERT) and _events(connection) == 1  # requested


async def test_a_hold_supersedes_an_earlier_pending_key():
    store, connection = _store({ACTIVE: OLD, EARLIER: {"user_sub": "alice", "key_version": 2}})
    await store.hold(RECORD, 1, HASH, LATER)
    assert _events(connection) == 2  # cancelled, then requested


@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ({}, "key_not_enrolled"),
        ({ACTIVE: {**OLD, "key_version": 2}}, "key_changed"),
        ({ACTIVE: OLD, CEREMONY: True}, "ceremony_in_progress"),
        ({ACTIVE: {**OLD, "email": None}}, "email_not_verified"),
    ],
)
async def test_a_refused_hold_writes_nothing(answers, code):
    store, connection = _store(answers)
    assert await store.hold(RECORD, 1, HASH, LATER) == Refused(code)
    assert not _wrote(connection, INSERT) and _events(connection) == 0


@pytest.mark.parametrize(
    ("row", "events"), [({"user_sub": "alice", "key_version": 2}, 1), (None, 0)]
)
async def test_a_release_cancels_only_a_row_it_found(row, events):
    store, connection = _store({"WHERE token_hash = $1": row})
    await store.release(TENANT, HASH, NOW)
    assert _events(connection) == events


async def test_the_sweep_expires_each_lapsed_row():
    rows = [{"user_sub": "bob", "key_version": 2}, {"user_sub": "alice", "key_version": 3}]
    store, connection = _store({SWEEP_LOCK: True, SWEEP: rows})
    await store.sweep(TENANT, NOW, keep=HASH)
    assert _events(connection) == 2


async def test_a_sweep_already_running_is_left_to_its_turn():
    store, connection = _store({SWEEP_LOCK: False, SWEEP: [{"user_sub": "bob", "key_version": 2}]})
    await store.sweep(TENANT, NOW)
    assert not _wrote(connection, SWEEP) and _events(connection) == 0


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"fingerprint": b"\x07" * 32, "expires_at": LATER}, PendingKey(b"\x07" * 32, LATER)),
        (None, None),
    ],
)
async def test_pending_of_reads_the_waiting_key(row, expected):
    store, _ = _store({"AND expires_at > $2": row})
    assert await store.pending_of(TENANT, "alice", NOW) == expected


@pytest.mark.parametrize(("answer", "expected"), [(TENANT, TENANT), (None, None)])
async def test_tenant_of_asks_the_definer_function(answer, expected):
    store, connection = _store({"reenrolment_tenant": answer})
    assert await store.tenant_of(HASH) == expected
    assert not _wrote(connection, "set_config")  # before any tenant is known


async def test_a_lookup_shows_a_live_link():
    store, connection = _store({READ: PENDING})
    assert await store.lookup(TENANT, HASH, NOW) == LinkDetails(b"\x07" * 32, NOW, LATER)
    assert _events(connection) == 0


@pytest.mark.parametrize(
    ("answers", "code", "events"),
    [
        ({}, "link_invalid", 0),
        (
            {READ: {**PENDING, "expires_at": NOW}, TAKE: {**PENDING, "expires_at": NOW}},
            "link_expired",
            1,
        ),
        # Expired, but a concurrent call took it first.
        ({READ: {**PENDING, "expires_at": NOW}}, "link_invalid", 0),
    ],
)
async def test_a_lookup_refuses_a_missing_or_lapsed_link(answers, code, events):
    store, connection = _store(answers)
    assert await store.lookup(TENANT, HASH, NOW) == Refused(code)
    assert _events(connection) == events


@pytest.mark.parametrize(
    ("taken", "answer", "events"),
    [
        (PENDING, None, 1),
        (None, Refused("link_invalid"), 0),
        ({**PENDING, "expires_at": NOW}, Refused("link_expired"), 1),
    ],
)
async def test_a_decline_takes_the_row_once(taken, answer, events):
    store, connection = _store({TAKE: taken})
    assert await store.decline(TENANT, HASH, NOW) == answer
    assert _events(connection) == events


async def test_a_confirm_swaps_from_the_pending_row():
    store, connection = _store({OWNER: "alice", ACTIVE: OLD, CONFIRM_TAKE: FULL})
    assert await store.confirm(TENANT, HASH, NOW) == b"\x07" * 32
    assert _wrote(connection, "INSERT INTO user_keys")
    assert _wrote(connection, "UPDATE user_keys SET retired_at")


@pytest.mark.parametrize(
    ("answers", "code", "events"),
    [
        ({}, "link_invalid", 0),
        ({OWNER: "alice", ACTIVE: OLD}, "link_invalid", 0),
        (
            {OWNER: "alice", ACTIVE: OLD, CONFIRM_TAKE: {**FULL, "expires_at": NOW}},
            "link_expired",
            1,
        ),
        # A replaced key that slipped past retirement: the row goes, the link is spent.
        (
            {OWNER: "alice", ACTIVE: {**OLD, "key_version": 3}, CONFIRM_TAKE: FULL},
            "link_invalid",
            1,
        ),
    ],
)
async def test_a_refused_confirm_swaps_nothing(answers, code, events):
    store, connection = _store(answers)
    assert await store.confirm(TENANT, HASH, NOW) == Refused(code)
    assert not _wrote(connection, "INSERT INTO user_keys")
    assert _events(connection) == events


async def test_a_running_ceremony_rolls_the_confirm_back():
    store, connection = _store({OWNER: "alice", ACTIVE: OLD, CONFIRM_TAKE: FULL, CEREMONY: True})
    assert await store.confirm(TENANT, HASH, NOW) == Refused("ceremony_in_progress")
    assert not _wrote(connection, "INSERT INTO user_keys") and _events(connection) == 0


@pytest.mark.parametrize("call", ["hold", "tenant_of", "decline"])
async def test_a_driver_failure_is_storage_unavailable(call):
    store = PostgresKeyConfirmations(ScriptedPool(None))
    arguments = {
        "hold": (RECORD, 1, HASH, LATER),
        "tenant_of": (HASH,),
        "decline": (TENANT, HASH, NOW),
    }[call]
    with pytest.raises(RecordingStorageUnavailable):
        await getattr(store, call)(*arguments)
