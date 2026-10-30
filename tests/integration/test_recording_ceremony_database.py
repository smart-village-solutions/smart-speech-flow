"""The ceremony tables enforce what the ceremony service assumes (migration 002).

Same environment as test_recording_database.py:

    pytest --run-integration tests/integration/test_recording_ceremony_database.py
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from services.api_gateway.recording import ceremony_repository
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
        " ceremony_dealers, ceremony_participants, recovery_ceremonies, user_keys, audit_events,"
        " gateway_signing_keys CASCADE"
    )
    yield connection
    await connection.close()


@pytest.fixture
async def repository(owner):
    repository = await PostgresCeremonyRepository.create(dsn=APP_DSN, password=APP_PASSWORD)
    for holder in CUSTODIANS:
        await repository.enrol_user_key(holder.key_record())
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


async def _run_to_active(service) -> str:
    """A whole ceremony with paper holders, from start to an active key; its ID."""
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
    return ceremony_id


async def test_a_whole_ceremony_lands_in_its_tables_with_an_intact_audit_chain(repository, owner):
    await _run_to_active(_service(repository))

    key = await repository.active_recovery_key(TENANT)
    shares = await repository.recovery_shares(TENANT, key.key_id)
    assert [s.encrypted_share is None for s in shares] == [False, False, False, True, True]
    rows = await repository.audit_rows(TENANT)
    assert chain_is_intact(rows)
    assert rows[-1].event.event_type == "recovery_key_activated"


async def test_a_closed_ceremony_is_read_without_sub_shares(repository):
    """What browsers check gateway keys against (#616, spec §10.6)."""
    ceremony_id = await _run_to_active(_service(repository))
    key = await repository.active_recovery_key(TENANT)
    [read] = await repository.chain(TENANT, ceremony_id)

    assert key.key_id == ceremony_id
    assert read.ceremony.status == "active"
    assert read.ceremony.transcript_hash == key.transcript_hash
    assert all(dealing.subshares == {} for dealing in read.dealings)
    assert {c.holder_index for c in read.confirmations} == {
        p.holder_index for p in read.participants if p.kind == "custodian"
    }
    assert await repository.chain("tenant-other", ceremony_id) == []


async def test_the_last_dealing_and_the_move_to_signing_commit_together(repository, monkeypatch):
    service = _service(repository)
    snapshot = await _start(service, paper=False)
    ceremony_id = snapshot.ceremony.ceremony_id
    for holder in (ANNA, BERND):
        snapshot = await service.deal(
            TENANT, holder.sub, ceremony_id, holder.deal(snapshot, POLYNOMIALS[holder.sub])
        )
    last = CARLA.deal(snapshot, POLYNOMIALS["carla"])

    def broken(_snapshot):
        raise RuntimeError("transcript failed")

    monkeypatch.setattr(ceremony_repository, "computed_transcript_hash", broken)
    with pytest.raises(RuntimeError):
        await service.deal(TENANT, "carla", ceremony_id, last)
    stuck = (await service.state(TENANT)).ceremony
    assert (stuck.ceremony.status, stuck.has_dealt(3)) == ("dealing", False)

    monkeypatch.undo()
    after = await service.deal(TENANT, "carla", ceremony_id, last)
    assert after.ceremony.status == "confirming"
    assert after.ceremony.transcript_hash is not None


async def test_the_last_signature_and_the_activation_commit_together(repository, monkeypatch):
    service = _service(repository)
    snapshot = await _start(service, paper=False)
    ceremony_id = snapshot.ceremony.ceremony_id
    for holder in CUSTODIANS:
        snapshot = await service.deal(
            TENANT, holder.sub, ceremony_id, holder.deal(snapshot, POLYNOMIALS[holder.sub])
        )
    snapshot = (await service.state(TENANT)).ceremony
    signed = {}
    for holder in CUSTODIANS:
        index = snapshot.custodian(holder.sub).holder_index
        received = await service.subshares(TENANT, holder.sub, ceremony_id)
        share = holder.share(snapshot, index, received[index])
        signed[holder.sub] = holder.confirmation(
            snapshot, index, share, snapshot.ceremony.transcript_hash
        )
    for holder in (ANNA, BERND):
        await service.confirm(TENANT, holder.sub, ceremony_id, *signed[holder.sub])

    def broken(_snapshot):
        raise RuntimeError("signing failed")

    monkeypatch.setattr(service, "_recovery_key", broken)
    with pytest.raises(RuntimeError):
        await service.confirm(TENANT, "carla", ceremony_id, *signed["carla"])
    assert await repository.active_recovery_key(TENANT) is None
    assert not (await service.state(TENANT)).ceremony.has_confirmed(3)

    monkeypatch.undo()
    assert await service.confirm(TENANT, "carla", ceremony_id, *signed["carla"]) == "active"
    assert await repository.active_recovery_key(TENANT) is not None


async def test_one_ceremony_in_progress_per_tenant(repository):
    service = _service(repository)
    snapshot = await _start(service)
    with pytest.raises(CeremonyError) as caught:
        await _start(service)
    assert caught.value.code == "CEREMONY_IN_PROGRESS"
    now = datetime.now(timezone.utc)
    assert await repository.last_failed_ceremony(TENANT, now) is None
    lapsed = await repository.last_failed_ceremony(TENANT, now + timedelta(hours=25))
    assert (lapsed.ceremony_id, lapsed.reason) == (snapshot.ceremony.ceremony_id, "expired")


async def test_an_aborted_ceremony_accepts_nothing_more(repository):
    service = _service(repository)
    snapshot = await _start(service)
    ceremony_id = snapshot.ceremony.ceremony_id
    dealing = ANNA.deal(snapshot, POLYNOMIALS["anna"])
    await service.abort(TENANT, "bernd", ceremony_id, "cancelled")
    failed = await repository.last_failed_ceremony(TENANT, datetime.now(timezone.utc))
    assert (failed.ceremony_id, failed.reason) == (ceremony_id, "cancelled")
    assert await repository.last_failed_ceremony("tenant-other", datetime.now(timezone.utc)) is None
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
            # k follows the holders since #617c; X and the first transcript never change.
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute("UPDATE recovery_keys SET transcript_hash = $1", bytes(32))
    finally:
        await connection.close()
