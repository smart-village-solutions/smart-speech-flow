"""The ceremony tables enforce what the ceremony service assumes (migration 002).

Same environment as test_recording_database.py:

    pytest --run-integration tests/integration/test_recording_ceremony_database.py
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import asyncpg
import pytest

from services.api_gateway.recording.audit import AuditEvent, chain_is_intact
from services.api_gateway.recording.ceremony import CeremonyService, StartRequest
from services.api_gateway.recording.ceremony_model import CeremonyError, DealingRecord
from services.api_gateway.recording.ceremony_repository import PostgresCeremonyRepository
from tests.recording_ceremony_actors import (
    ANNA,
    BERND,
    CARLA,
    DEVICE,
    ORG_ADMIN,
    POLYNOMIALS,
    TENANT,
    gateway_secrets,
)
from tests.recording_fakes import FakeCustodianDirectory

pytestmark = pytest.mark.integration

APP_DSN = os.environ.get("SSF_RECORDING_DATABASE_URL", "")
APP_PASSWORD = os.environ.get("SSF_RECORDING_DATABASE_PASSWORD") or None
OWNER_DSN = os.environ.get("SSF_RECORDING_OWNER_DATABASE_URL", "")
OWNER_PASSWORD = os.environ.get("SSF_RECORDING_OWNER_DATABASE_PASSWORD") or None
CUSTODIANS = (ANNA, BERND, CARLA)
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
async def owner():
    if not OWNER_DSN:
        pytest.skip("SSF_RECORDING_OWNER_DATABASE_URL is not set")
    connection = await asyncpg.connect(OWNER_DSN, password=OWNER_PASSWORD)
    await connection.execute(
        "TRUNCATE recovery_shares, recovery_keys, ceremony_confirmations, ceremony_dealings,"
        " ceremony_participants, recovery_ceremonies, user_keys, audit_events,"
        " gateway_signing_keys CASCADE"
    )
    yield connection
    await connection.close()


@pytest.fixture
async def repository(owner):
    repository = await PostgresCeremonyRepository.create(dsn=APP_DSN, password=APP_PASSWORD)
    for holder in CUSTODIANS:
        await repository.enrol_user_key(
            holder.key_record(), AuditEvent(TENANT, holder.sub, "key_enrolled", "k", NOW)
        )
    secrets = gateway_secrets()
    await repository.register_gateway_key(secrets.signing_key_id, secrets.signing_public_key, NOW)
    yield repository
    await repository.close()


def _service(repository) -> CeremonyService:
    return CeremonyService(
        repository=repository,
        directory=FakeCustodianDirectory({h.sub: h.sub.title() for h in CUSTODIANS}),
        secrets=gateway_secrets(),
    )


async def _start(service, paper: bool = True):
    request = StartRequest(2, ("anna", "bernd", "carla"), DEVICE.enc_pub if paper else None)
    return await service.start(TENANT, ORG_ADMIN, request, "corr")


async def test_a_whole_ceremony_lands_in_its_tables_with_an_intact_audit_chain(repository, owner):
    service = _service(repository)
    snapshot = await _start(service)
    ceremony_id = snapshot.ceremony.ceremony_id
    for holder in CUSTODIANS:
        snapshot = await service.deal(
            TENANT, holder.sub, ceremony_id, holder.deal(snapshot, POLYNOMIALS[holder.sub])
        )
    snapshot = (await service.state(TENANT)).ceremony
    assert snapshot.ceremony.status == "confirming"
    for holder in CUSTODIANS:
        index = snapshot.custodian(holder.sub).holder_index
        received = await service.subshares(TENANT, holder.sub, ceremony_id)
        share = holder.share(snapshot, index, received[index])
        signature, sealed = holder.confirmation(
            snapshot, index, share, snapshot.ceremony.transcript_hash
        )
        await service.confirm(TENANT, holder.sub, ceremony_id, signature, sealed)
    paper = await service.subshares(TENANT, ORG_ADMIN, ceremony_id)
    assert set(paper) == {4, 5}
    status = await service.confirm_paper(
        TENANT, ORG_ADMIN, ceremony_id, snapshot.ceremony.transcript_hash
    )
    assert status == "active"

    key = await repository.active_recovery_key(TENANT)
    shares = await repository.recovery_shares(TENANT, key.key_id)
    assert [s.encrypted_share is None for s in shares] == [False, False, False, True, True]
    rows = await repository.audit_rows(TENANT)
    assert chain_is_intact(rows)
    assert rows[-1].event.event_type == "recovery_key_activated"


async def test_one_ceremony_in_progress_per_tenant(repository):
    service = _service(repository)
    await _start(service)
    with pytest.raises(CeremonyError) as caught:
        await _start(service)
    assert caught.value.code == "CEREMONY_IN_PROGRESS"


async def test_an_aborted_ceremony_accepts_nothing_more(repository):
    service = _service(repository)
    snapshot = await _start(service)
    ceremony_id = snapshot.ceremony.ceremony_id
    dealing = ANNA.deal(snapshot, POLYNOMIALS["anna"])
    await service.abort(TENANT, "bernd", ceremony_id, "cancelled")
    with pytest.raises(CeremonyError):
        await service.deal(TENANT, "anna", ceremony_id, dealing)
    with pytest.raises(CeremonyError) as caught:
        await repository.add_dealing(
            TENANT,
            ceremony_id,
            _record(dealing),
            AuditEvent(TENANT, "anna", "ceremony_dealt", "x", NOW),
        )
    assert caught.value.code == "CEREMONY_STATE"


def _record(dealing):
    return DealingRecord(
        1,
        dealing.commitments,
        dealing.proof_c,
        dealing.proof_s,
        dealing.signature,
        datetime.now(timezone.utc),
        dealing.subshares,
    )


async def test_ceremonies_stay_inside_their_tenant(repository):
    await _start(_service(repository))
    assert await repository.open_ceremony("tenant-other", datetime.now(timezone.utc)) is None


async def test_the_application_role_cannot_rewrite_dealings_or_keys(repository):
    service = _service(repository)
    await _start(service, paper=False)
    connection = await asyncpg.connect(APP_DSN, password=APP_PASSWORD)
    try:
        async with connection.transaction():
            await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute("DELETE FROM ceremony_participants")
        async with connection.transaction():
            await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute("UPDATE recovery_keys SET k = 1")
    finally:
        await connection.close()
