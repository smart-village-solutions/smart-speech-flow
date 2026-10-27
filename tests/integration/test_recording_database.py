"""The ssf_recording database enforces what the gateway assumes (spec §11.4, §13).

Runs against the real apply.sh output, like the feedback suites:

    SSF_RECORDING_DATABASE_URL=postgresql://ssf_recording_app@127.0.0.1:5432/ssf_recording
    SSF_RECORDING_DATABASE_PASSWORD=...
    SSF_RECORDING_OWNER_DATABASE_URL=postgresql://ssf@127.0.0.1:5432/ssf_recording
    SSF_RECORDING_OWNER_DATABASE_PASSWORD=...
    pytest --run-integration tests/integration/test_recording_database.py
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import asyncpg
import pytest

from services.api_gateway.recording.audit import AuditEvent, chain_is_intact
from services.api_gateway.recording.repository import (
    KeyAlreadyEnrolledError,
    PostgresRecordingRepository,
    UserKeyRecord,
)
from tests import recording_crypto_reference as ref

pytestmark = pytest.mark.integration

APP_DSN = os.environ.get("SSF_RECORDING_DATABASE_URL", "")
APP_PASSWORD = os.environ.get("SSF_RECORDING_DATABASE_PASSWORD") or None
OWNER_DSN = os.environ.get("SSF_RECORDING_OWNER_DATABASE_URL", "")
OWNER_PASSWORD = os.environ.get("SSF_RECORDING_OWNER_DATABASE_PASSWORD") or None

_BIND = "SELECT set_config('ssf.tenant_id', $1, TRUE)"
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def _key(tenant_id: str, user_sub: str) -> UserKeyRecord:
    return UserKeyRecord(
        tenant_id=tenant_id,
        user_sub=user_sub,
        key_version=1,
        enc_pub=ref.public_point(11),
        sig_pub=ref.public_point(12),
        fingerprint=bytes(32),
        encrypted_private=b"\x01" + bytes(40),
        created_at=NOW,
    )


@pytest.fixture
async def owner():
    if not OWNER_DSN:
        pytest.skip("SSF_RECORDING_OWNER_DATABASE_URL is not set")
    connection = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    # CASCADE: chain entries (migration 003) reference the gateway keys.
    await connection.execute("TRUNCATE user_keys, audit_events, gateway_signing_keys CASCADE")
    yield connection
    await connection.close()


@pytest.fixture
async def app_connection(owner):
    connection = await asyncpg.connect(APP_DSN, password=APP_PASSWORD)
    yield connection
    await connection.close()


@pytest.fixture
async def repository(owner):
    repository = await PostgresRecordingRepository.create(dsn=APP_DSN, password=APP_PASSWORD)
    yield repository
    await repository.close()


async def test_the_application_role_is_neither_superuser_nor_rls_exempt(owner):
    row = await owner.fetchrow(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'ssf_recording_app'"
    )
    assert row is not None
    assert (row["rolsuper"], row["rolbypassrls"]) == (False, False)


async def test_the_audit_log_refuses_update_and_delete(repository, app_connection):
    await repository.record_audit(AuditEvent("tenant-a", "alice", "key_enrolled", "x", NOW))
    async with app_connection.transaction():
        await app_connection.execute(_BIND, "tenant-a")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_connection.execute("UPDATE audit_events SET actor_sub = 'mallory'")
    async with app_connection.transaction():
        await app_connection.execute(_BIND, "tenant-a")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_connection.execute("DELETE FROM audit_events")


async def test_keys_and_audit_rows_stay_inside_their_tenant(repository, app_connection):
    await repository.enrol_user_key(
        _key("tenant-a", "alice"), AuditEvent("tenant-a", "alice", "key_enrolled", "k", NOW)
    )
    assert await repository.active_user_key("tenant-b", "alice") is None
    assert await repository.audit_rows("tenant-b") == []
    async with app_connection.transaction():
        await app_connection.execute(_BIND, "tenant-b")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_connection.execute(
                "INSERT INTO audit_events VALUES ('tenant-a', 99, now(), 'x', 'x', 'x'," " $1, $1)",
                bytes(32),
            )


async def test_enrolment_round_trip_one_active_key_and_an_intact_chain(repository):
    record = _key("tenant-a", "alice")
    await repository.enrol_user_key(
        record, AuditEvent("tenant-a", "alice", "key_enrolled", "k", NOW)
    )
    assert await repository.active_user_key("tenant-a", "alice") == record
    with pytest.raises(KeyAlreadyEnrolledError):
        await repository.enrol_user_key(
            record, AuditEvent("tenant-a", "alice", "key_enrolled", "k", NOW)
        )
    await repository.record_audit(AuditEvent("tenant-a", "alice", "key_blob_read", "k", NOW))
    rows = await repository.audit_rows("tenant-a")
    assert [row.seq for row in rows] == [1, 2]
    assert chain_is_intact(rows)


async def test_gateway_keys_are_registered_once(repository):
    public_key = ref.public_point(13)
    await repository.register_gateway_key("gk-1", public_key, NOW)
    await repository.register_gateway_key("gk-1", public_key, NOW)
    assert await repository.gateway_keys() == (("gk-1", public_key),)
