"""Resharing in Postgres (spec §9.7; migration 008)."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import asyncpg
import pytest

from services.api_gateway.recording.archive_access_repository import _APPROVED
from services.api_gateway.recording.audit import AuditEvent, chain_is_intact
from services.api_gateway.recording.ceremony import CeremonyService, StartRequest
from services.api_gateway.recording.ceremony_model import CeremonyError, CeremonyRecord
from services.api_gateway.recording.ceremony_repository import PostgresCeremonyRepository
from services.api_gateway.recording.crypto import ecies, tags
from services.api_gateway.recording.crypto.curve import ORDER, decode_point, encode_point, multiply
from services.api_gateway.recording.crypto.encoding import b64url, from_b64url
from services.api_gateway.recording.recovery_requests_model import Approval, NewRequest, Refused
from services.api_gateway.recording.recovery_requests_repository import PostgresRecoveryRequests
from services.api_gateway.recording.reenrolment_repository import PostgresKeyReenrolment
from services.api_gateway.recording.repository import UserKeyRecord
from services.api_gateway.recording.resharing import ResharingService
from services.api_gateway.recording.resharing_model import ResharingStart
from tests import recording_crypto_reference as ref
from tests.recording_ceremony_actors import (
    ANNA,
    BERND,
    CARLA,
    DEVICE,
    DORA,
    EMIL,
    ORG_ADMIN,
    POLYNOMIALS,
    gateway_secrets,
    reshare_dealing,
    share_proof,
)
from tests.recording_fakes import FakeCustodianDirectory
from tests.integration.test_recording_archive_access_database import _ended
from tests.integration.test_recording_archive_database import (  # noqa: F401 - fixtures
    _ARCHIVE_TABLES,
    NOW,
    TENANT,
    archive,
    owner,
)
from tests.integration.test_recording_recovery_requests_database import (  # noqa: F401
    file_directly,
    recovery_key,
)

pytestmark = pytest.mark.integration

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "deploy/postgres/recording/migrations/008_recording_resharing.sql"
)


APP_DSN = os.environ.get("SSF_RECORDING_DATABASE_URL", "")
APP_PASSWORD = os.environ.get("SSF_RECORDING_DATABASE_PASSWORD") or None
HOLDERS = {h.sub: h for h in (ANNA, BERND, CARLA, DORA, EMIL)}
FIRST = (ANNA, BERND, CARLA)
SECRET = sum(coefficients[0] for coefficients in POLYNOMIALS.values()) % ORDER
SECRETS = gateway_secrets()


async def _clean(owner) -> None:
    await owner.execute(f"TRUNCATE {_ARCHIVE_TABLES}")
    await owner.execute(
        "TRUNCATE recovery_shares, recovery_keys, ceremony_confirmations, ceremony_dealings,"
        " ceremony_dealers, ceremony_participants, recovery_ceremonies CASCADE"
    )
    await owner.execute("DELETE FROM user_keys")


@pytest.fixture(autouse=True)
async def _fresh(owner):
    await _clean(owner)
    yield
    await _clean(owner)


@pytest.fixture
async def store(owner):
    repository = await PostgresCeremonyRepository.create(dsn=APP_DSN, password=APP_PASSWORD)
    secrets = SECRETS
    for holder in HOLDERS.values():
        blob = secrets.server_layer.seal(b"{}", tenant_id=TENANT, user_sub=holder.sub)
        await repository.enrol_user_key(
            replace(holder.key_record(TENANT), encrypted_private=blob),
            AuditEvent(TENANT, holder.sub, "key_enrolled", "k", NOW),
        )
    await repository.register_gateway_key(secrets.signing_key_id, secrets.signing_public_key, NOW)
    yield repository
    await repository.close()


def _services(store) -> tuple[CeremonyService, ResharingService]:
    directory = FakeCustodianDirectory({sub: sub.title() for sub in HOLDERS})
    return (
        CeremonyService(repository=store, directory=directory, secrets=SECRETS),
        ResharingService(repository=store, directory=directory, server_layer=SECRETS.server_layer),
    )


async def _first_generation(ceremonies: CeremonyService) -> dict[int, int]:
    """A 2-of-3 key with two paper sheets; every holder's share, for the test to deal with."""
    request = StartRequest(2, ("anna", "bernd", "carla"), DEVICE.enc_pub)
    snapshot = await ceremonies.start(TENANT, ORG_ADMIN, request, "c")
    ceremony_id = snapshot.ceremony.ceremony_id
    for holder in FIRST:
        snapshot = await ceremonies.deal(
            TENANT, holder.sub, ceremony_id, holder.deal(snapshot, POLYNOMIALS[holder.sub])
        )
    snapshot = (await ceremonies.state(TENANT)).ceremony
    shares = {}
    for holder in FIRST:
        index = snapshot.custodian(holder.sub).holder_index
        received = await ceremonies.subshares(TENANT, holder.sub, ceremony_id)
        shares[index] = holder.share(snapshot, index, received[index])
        signature, sealed = holder.confirmation(
            snapshot, index, shares[index], snapshot.ceremony.transcript_hash
        )
        await ceremonies.confirm(TENANT, holder.sub, ceremony_id, signature, sealed)
    for index, received in (await ceremonies.subshares(TENANT, ORG_ADMIN, ceremony_id)).items():
        shares[index] = DEVICE.share(snapshot, index, received)
    await ceremonies.confirm_paper(
        TENANT, ORG_ADMIN, ceremony_id, snapshot.ceremony.transcript_hash
    )
    return shares


async def _holders(ceremonies: CeremonyService) -> str:
    return (await ceremonies.state(TENANT)).recovery_key.current_holders[0]


async def _reshare_and_deal(
    ceremonies, resharing, shares, *, k=2, custodians=("bernd", "dora", "emil")
):
    """Anna deals share 1 and the device types in sheet 4; returns the snapshot to confirm."""
    started = await resharing.start(
        TENANT, ORG_ADMIN, ResharingStart(k, custodians, (1, 4), None, await _holders(ceremonies)), "c"
    )
    snapshot = (await ceremonies.state(TENANT)).ceremony
    reshare_id = started.ceremony.ceremony_id
    tail = list(range(61, 60 + k))
    await ceremonies.deal(
        TENANT, "anna", reshare_id, reshare_dealing(snapshot, 1, shares[1], tail, ANNA)
    )
    sheet = reshare_dealing(snapshot, 4, shares[4], [t + 10 for t in tail], None)
    await resharing.paper_deal(TENANT, ORG_ADMIN, reshare_id, 4, sheet)
    return (await ceremonies.state(TENANT)).ceremony


async def _confirm_one(ceremonies, snapshot, holder, key_id) -> tuple[int, int, str]:
    reshare_id = snapshot.ceremony.ceremony_id
    index = snapshot.custodian(holder.sub).holder_index
    received = await ceremonies.subshares(TENANT, holder.sub, reshare_id)
    share = holder.share(snapshot, index, received[index])
    signature, sealed = holder.confirmation(
        snapshot, index, share, snapshot.ceremony.transcript_hash, key_id
    )
    status = await ceremonies.confirm(
        TENANT, holder.sub, reshare_id, signature, sealed, share_proof(snapshot, index, share)
    )
    return index, share, status


async def _confirm_all(ceremonies, snapshot, key_id) -> dict[int, int]:
    new = {}
    for participant in snapshot.custodians:
        index, share, _ = await _confirm_one(
            ceremonies, snapshot, HOLDERS[participant.holder_ref], key_id
        )
        new[index] = share
    return new


async def _as_app(archive, *statements: tuple[str, tuple]) -> list[str]:
    """Each statement as the app role, in one transaction that is rolled back."""
    results = []
    async with archive._pool.acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
            for query, args in statements:
                results.append(await connection.execute(query, *args))
        finally:
            await transaction.rollback()
    return results


async def _ceremony(owner, status: str, *, subshares: dict | None = None) -> uuid.UUID:
    ceremony_id = uuid.uuid4()
    await owner.execute(
        "INSERT INTO recovery_ceremonies (tenant_id, ceremony_id, k, started_by, started_at,"
        " expires_at, status, gateway_keys) VALUES ($1, $2, 1, 'admin', $3, $3, $4, '[]')",
        TENANT,
        ceremony_id,
        NOW,
        status,
    )
    await owner.execute(
        "INSERT INTO ceremony_participants (tenant_id, ceremony_id, holder_index, holder_ref,"
        " kind, enc_pub, sig_pub, fingerprint) VALUES ($1, $2, 1, 'carol', 'custodian', $3, $4, $5)",
        TENANT,
        ceremony_id,
        ref.public_point(11),
        ref.public_point(12),
        bytes(32),
    )
    await owner.execute(
        "INSERT INTO ceremony_dealers VALUES ($1, $2, 1, 'carol', 'custodian')",
        TENANT,
        ceremony_id,
    )
    await owner.execute(
        "INSERT INTO ceremony_dealings (tenant_id, ceremony_id, dealer_index, commitments,"
        " proof_c, proof_s, signature, subshares, dealt_at)"
        " VALUES ($1, $2, 1, $3, $4, $4, $5, $6, $7)",
        TENANT,
        ceremony_id,
        [ref.public_point(13)],
        bytes(32),
        bytes(64),
        json.dumps(subshares if subshares is not None else {"1": "sealed"}),
        NOW,
    )
    return ceremony_id


async def _rerun_migration(connection: asyncpg.Connection) -> None:
    await connection.execute(MIGRATION.read_text())


async def test_a_key_made_before_008_becomes_its_own_first_generation(archive, owner):
    conversation, key_id, _ = await _ended(archive, owner)
    request_id = await file_directly(owner, conversation.conversation_id, key_id)
    recovery = uuid.UUID(await recovery_key(owner))
    async with owner.transaction():
        # Back to the shape 007 left: no generation columns filled, no dealers.
        for table, column in (
            ("recovery_keys", "holders_ceremony_id"),
            ("recovery_keys", "holders_transcript_hash"),
            ("recovery_shares", "ceremony_id"),
            ("recovery_requests", "holders_ceremony_id"),
        ):
            await owner.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL")
            await owner.execute(f"UPDATE {table} SET {column} = NULL")
        await owner.execute("DELETE FROM ceremony_dealers")
        await _rerun_migration(owner)
        key = await owner.fetchrow("SELECT * FROM recovery_keys WHERE key_id = $1", recovery)
        shares = await owner.fetch("SELECT DISTINCT ceremony_id FROM recovery_shares")
        request = await owner.fetchval(
            "SELECT holders_ceremony_id FROM recovery_requests WHERE request_id = $1", request_id
        )
        dealers = await owner.fetch(
            "SELECT dealer_index, holder_ref, kind FROM ceremony_dealers WHERE ceremony_id = $1"
            " ORDER BY dealer_index",
            recovery,
        )
        custodians = await owner.fetch(
            "SELECT holder_index, holder_ref, kind FROM ceremony_participants"
            " WHERE ceremony_id = $1 AND kind = 'custodian' ORDER BY holder_index",
            recovery,
        )
    assert key["holders_ceremony_id"] == recovery
    assert bytes(key["holders_transcript_hash"]) == bytes(key["transcript_hash"])
    assert [row["ceremony_id"] for row in shares] == [recovery]
    assert request == recovery
    assert [tuple(row) for row in dealers] == [tuple(row) for row in custodians]
    assert len(dealers) >= 2


async def test_008_clears_the_sub_shares_of_closed_ceremonies_only(owner):
    active = await _ceremony(owner, "active")
    aborted = await _ceremony(owner, "aborted")
    dealing = await _ceremony(owner, "dealing")
    await _rerun_migration(owner)
    rows = await owner.fetch("SELECT ceremony_id, subshares FROM ceremony_dealings")
    sealed = {row["ceremony_id"]: json.loads(row["subshares"]) for row in rows}
    assert sealed == {active: {}, aborted: {}, dealing: {"1": "sealed"}}


async def test_008_applied_again_changes_nothing(owner):
    async def shape():
        constraints = await owner.fetch(
            "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace"
            " WHERE n.nspname = 'public' ORDER BY conname"
        )
        policies = await owner.fetch("SELECT policyname FROM pg_policies ORDER BY policyname")
        return [r[0] for r in constraints], [r[0] for r in policies]

    before = await shape()
    await _rerun_migration(owner)
    assert await shape() == before


async def test_dealings_name_a_dealer_not_a_participant(owner):
    old = await owner.fetchval(
        "SELECT count(*) FROM pg_constraint WHERE conrelid = 'ceremony_dealings'::regclass"
        " AND confrelid = 'ceremony_participants'::regclass"
    )
    assert old == 0
    ceremony_id = await _ceremony(owner, "dealing")
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await owner.execute(
            "INSERT INTO ceremony_dealings (tenant_id, ceremony_id, dealer_index, commitments,"
            " proof_c, proof_s, subshares, dealt_at) VALUES ($1, $2, 2, $3, $4, $4, '{}', $5)",
            TENANT,
            ceremony_id,
            [ref.public_point(13)],
            bytes(32),
            NOW,
        )


async def test_a_share_proof_has_both_halves_or_neither(owner):
    row = await owner.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE conname = 'ceremony_confirmations_share_proof'"
    )
    assert "share_proof_c IS NULL" in row


async def test_a_resharing_names_its_key_and_previous_transcript(owner):
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute(
            "INSERT INTO recovery_ceremonies (tenant_id, ceremony_id, k, started_by, started_at,"
            " expires_at, status, gateway_keys, kind) VALUES ($1, $2, 1, 'admin', $3, $3,"
            " 'dealing', '[]', 'resharing')",
            TENANT,
            uuid.uuid4(),
            NOW,
        )


async def test_the_app_may_replace_shares_and_move_the_key_to_new_holders(archive, owner):
    key_id = uuid.UUID(await recovery_key(owner))
    results = await _as_app(
        archive,
        ("DELETE FROM recovery_shares WHERE key_id = $1", (key_id,)),
        (
            "UPDATE recovery_keys SET holders_ceremony_id = key_id, holders_transcript_hash = $2,"
            " k = 2, n = 3, mode = 'enhanced' WHERE key_id = $1",
            (key_id, bytes(32)),
        ),
    )
    assert results == ["DELETE 2", "UPDATE 1"]


async def test_the_app_never_changes_the_recovery_public_key(archive, owner):
    key_id = uuid.UUID(await recovery_key(owner))
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _as_app(
            archive,
            (
                "UPDATE recovery_keys SET recovery_public_key = $2 WHERE key_id = $1",
                (key_id, ref.public_point(5)),
            ),
        )


async def test_the_app_may_clear_sub_shares_but_not_change_commitments(archive, owner):
    ceremony_id = await _ceremony(owner, "active")
    cleared = await _as_app(
        archive,
        (
            "UPDATE ceremony_dealings SET subshares = '{}' WHERE ceremony_id = $1",
            (ceremony_id,),
        ),
    )
    assert cleared == ["UPDATE 1"]
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _as_app(
            archive,
            (
                "UPDATE ceremony_dealings SET commitments = '{}' WHERE ceremony_id = $1",
                (ceremony_id,),
            ),
        )


async def test_dealers_are_tenant_isolated(owner):
    row = await owner.fetchrow(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'ceremony_dealers'"
    )
    assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True)


async def test_a_resharing_replaces_the_holders_and_keeps_the_key(store, owner):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    before = await store.active_recovery_key(TENANT)
    # Carla re-enrolled earlier; her custodian blob was kept for a resharing (§9.6).
    await owner.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'carla'", NOW)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    reshare_id = snapshot.ceremony.ceremony_id
    new = await _confirm_all(ceremonies, snapshot, before.key_id)
    kept = await owner.fetchval(
        "SELECT count(*) FROM user_keys"
        " WHERE retired_at IS NOT NULL AND encrypted_private IS NOT NULL"
    )
    assert kept == 0
    assert await store.usable_shares(TENANT) == 3
    reenrolment = PostgresKeyReenrolment(store.pool)
    assert (await reenrolment.impact(TENANT, "dora")).custodian is True
    assert (await reenrolment.impact(TENANT, "anna")).custodian is False

    key = await store.active_recovery_key(TENANT)
    assert (key.key_id, key.recovery_public_key, key.transcript_hash) == (
        before.key_id,
        before.recovery_public_key,
        before.transcript_hash,
    )
    assert key.current_holders == (reshare_id, snapshot.ceremony.transcript_hash)
    assert (key.k, key.n, key.mode) == (2, 3, "enhanced")
    for pair in ((1, 2), (2, 3)):
        assert sum(ref.lagrange_at_zero(i, pair) * new[i] for i in pair) % ORDER == SECRET
    rows = await owner.fetch(
        "SELECT holder_index, holder_ref, ceremony_id, encrypted_share IS NOT NULL AS sealed"
        " FROM recovery_shares ORDER BY holder_index"
    )
    assert [tuple(r) for r in rows] == [
        (1, "bernd", uuid.UUID(reshare_id), True),
        (2, "dora", uuid.UUID(reshare_id), True),
        (3, "emil", uuid.UUID(reshare_id), True),
    ]
    generation = await store.holder_generation(TENANT)
    assert (generation.ceremony_id, generation.k) == (reshare_id, 2)
    assert [s.ceremony.ceremony_id for s in await store.chain(TENANT, before.key_id)] == [
        before.key_id,
        reshare_id,
    ]
    leftovers = await owner.fetchval(
        "SELECT count(*) FROM ceremony_dealings WHERE subshares <> '{}'::jsonb"
    )
    assert leftovers == 0
    unsigned = await owner.fetch(
        "SELECT dealer_index FROM ceremony_dealings WHERE signature IS NULL"
    )
    assert [r["dealer_index"] for r in unsigned] == [4]
    proofs = await owner.fetchval(
        "SELECT count(*) FROM ceremony_confirmations WHERE ceremony_id = $1"
        " AND share_proof_c IS NOT NULL",
        uuid.UUID(reshare_id),
    )
    assert proofs == 3
    audit = await store.audit_rows(TENANT)
    assert chain_is_intact(audit)
    assert audit[-1].event.event_type == "recovery_key_reshared"
    assert audit[-1].event.object_ref == f"recovery-key:{before.key_id}:ceremony:{reshare_id}"


async def test_activation_closes_open_requests_and_drops_their_partials(store, owner, archive):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    conversation, key_id, _ = await _ended(archive, owner)
    request_id = uuid.uuid4()
    await owner.execute(
        "INSERT INTO recovery_requests (tenant_id, request_id, kind, requester_sub,"
        " requester_key_version, recovery_key_id, reason, request_signature, status,"
        " created_at, expires_at, holders_ceremony_id) VALUES ($1, $2, 'access', 'carla', 1, $3,"
        " 'why', $4, 'open', $5, $6, $3)",
        TENANT,
        request_id,
        uuid.UUID(key.key_id),
        bytes(64),
        NOW,
        NOW + timedelta(days=700),
    )
    await owner.execute(
        "INSERT INTO recovery_request_keys VALUES ($1, $2, $3, $4)",
        TENANT,
        request_id,
        uuid.UUID(conversation.conversation_id),
        uuid.UUID(key_id),
    )
    await owner.execute(
        "INSERT INTO recovery_decisions (tenant_id, request_id, holder_index, attempt,"
        " custodian_sub, decision, signed_partials, approval_signature, decided_at)"
        " VALUES ($1, $2, 1, 1, 'anna', 'approved', '[]', $3, $4)",
        TENANT,
        request_id,
        bytes(64),
        NOW,
    )
    await owner.execute(
        "INSERT INTO recovery_partials VALUES ($1, $2, 1, 1, $3, $4, '{}')",
        TENANT,
        request_id,
        uuid.UUID(conversation.conversation_id),
        uuid.UUID(key_id),
    )
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    await _confirm_all(ceremonies, snapshot, key.key_id)

    status = await owner.fetchval(
        "SELECT status FROM recovery_requests WHERE request_id = $1", request_id
    )
    assert status == "cancelled"
    assert await owner.fetchval("SELECT count(*) FROM recovery_partials") == 0
    events = [(r.event.actor_sub, r.event.event_type) for r in await store.audit_rows(TENANT)]
    assert ("system", "recovery.request.cancelled") in events


async def test_shares_that_fail_the_final_check_abort_and_keep_the_old_holders(store, owner):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    reshare_id = snapshot.ceremony.ceremony_id
    old = await owner.fetch("SELECT * FROM recovery_shares ORDER BY holder_index")
    await _confirm_one(ceremonies, snapshot, BERND, key.key_id)
    await _confirm_one(ceremonies, snapshot, DORA, key.key_id)
    # X changed in storage after the dealings were checked.
    await owner.execute("UPDATE recovery_keys SET recovery_public_key = $1", ref.public_point(5))
    with pytest.raises(CeremonyError) as caught:
        await _confirm_one(ceremonies, snapshot, EMIL, key.key_id)
    assert caught.value.code == "CEREMONY_ABORTED"

    row = await owner.fetchrow(
        "SELECT status, close_reason FROM recovery_ceremonies WHERE ceremony_id = $1",
        uuid.UUID(reshare_id),
    )
    assert tuple(row) == ("aborted", "canary_failed")
    assert await owner.fetch("SELECT * FROM recovery_shares ORDER BY holder_index") == old
    confirmed = await owner.fetchval(
        "SELECT count(*) FROM ceremony_confirmations WHERE ceremony_id = $1",
        uuid.UUID(reshare_id),
    )
    assert confirmed == 3
    assert (
        await owner.fetchval(
            "SELECT count(*) FROM ceremony_dealings WHERE subshares <> '{}'::jsonb"
        )
        == 0
    )
    state = await ceremonies.state(TENANT)
    assert state.recovery_key is not None
    assert state.last_failed.reason == "canary_failed"


async def test_two_last_confirmations_at_once_activate_exactly_once(store):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    await _confirm_one(ceremonies, snapshot, BERND, key.key_id)
    results = await asyncio.gather(
        _confirm_one(ceremonies, snapshot, DORA, key.key_id),
        _confirm_one(ceremonies, snapshot, EMIL, key.key_id),
    )
    assert sorted(status for _, _, status in results) == ["active", "confirming"]
    events = [r.event.event_type for r in await store.audit_rows(TENANT)]
    assert events.count("recovery_key_reshared") == 1


async def test_a_re_enrolled_dealer_deals_with_the_retired_key_until_its_blob_is_gone(store, owner):
    ceremonies, resharing = _services(store)
    await _first_generation(ceremonies)
    await owner.execute("UPDATE user_keys SET retired_at = $1 WHERE user_sub = 'anna'", NOW)
    await owner.execute(
        "INSERT INTO user_keys (tenant_id, user_sub, key_version, enc_pub, sig_pub,"
        " fingerprint, created_at) VALUES ($1, 'anna', 2, $2, $3, $4, $5)",
        TENANT,
        ref.public_point(901),
        ref.public_point(902),
        bytes([9]) * 32,
        NOW,
    )
    assert await store.holder_states(TENANT) == {
        "anna": "kept",
        "bernd": "fresh",
        "carla": "fresh",
    }
    started = await resharing.start(
        TENANT, ORG_ADMIN, ResharingStart(2, ("bernd", "dora", "emil"), (1, 2), None, await _holders(ceremonies)),
        "c",
    )
    material = await resharing.dealer(TENANT, "anna", started.ceremony.ceremony_id)
    assert (material.dealer_index, material.key.key_version) == (1, 1)
    assert material.encrypted_share.startswith("{")

    await owner.execute(
        "UPDATE user_keys SET encrypted_private = NULL WHERE key_version = 1"
        " AND user_sub = 'anna'"
    )
    assert (await store.holder_states(TENANT))["anna"] == "lost"
    with pytest.raises(CeremonyError) as caught:
        await resharing.dealer(TENANT, "anna", started.ceremony.ceremony_id)
    assert caught.value.code == "DEALER_UNUSABLE"


async def test_an_aborted_resharing_drops_its_sub_shares_and_is_reported(store, owner):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    reshare_id = snapshot.ceremony.ceremony_id
    await ceremonies.abort(TENANT, "anna", reshare_id, "contribution_invalid")
    sealed = await owner.fetch(
        "SELECT subshares FROM ceremony_dealings WHERE ceremony_id = $1", uuid.UUID(reshare_id)
    )
    assert [json.loads(r["subshares"]) for r in sealed] == [{}, {}]
    state = await ceremonies.state(TENANT)
    assert state.last_failed.reason == "contribution_invalid"
    assert (await store.holder_generation(TENANT)).ceremony_id != reshare_id


async def test_only_one_ceremony_or_resharing_runs_at_a_time(store):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    await _reshare_and_deal(ceremonies, resharing, shares)
    with pytest.raises(CeremonyError) as caught:
        await resharing.start(
            TENANT, ORG_ADMIN, ResharingStart(2, ("bernd", "dora", "emil"), (1, 4), None, await _holders(ceremonies)),
            "c",
        )
    assert caught.value.code == "CEREMONY_IN_PROGRESS"


async def _file(archive, owner, key_id: str, *, sub="carla", conversation=None):
    """An access request for a conversation (a fresh one by default) wrapped for this key."""
    if conversation is None:
        conversation, _, _ = await _ended(archive, owner)
    await owner.execute(
        "UPDATE key_wraps SET recipient_ref = $1 WHERE recipient_kind = 'recovery'", key_id
    )
    request = NewRequest(
        TENANT,
        str(uuid.uuid4()),
        "access",
        sub,
        1,
        key_id,
        "why",
        (conversation.conversation_id,),
        bytes(64),
        NOW,
    )
    scope = await PostgresRecoveryRequests(archive._pool).file(request, lambda *_: True)
    assert not isinstance(scope, Refused), scope
    return request.request_id, scope


def _approval(scope) -> Approval:
    return Approval({key.key_id: "{}" for key in scope}, bytes(64))


async def test_after_a_resharing_the_new_custodians_decide_and_the_old_do_not(
    store, owner, archive
):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    await _confirm_all(ceremonies, snapshot, key.key_id)
    request_id, scope = await _file(archive, owner, key.key_id)
    requests = PostgresRecoveryRequests(archive._pool)

    listed = await requests.approvals(TENANT, "dora", key.key_id, NOW)
    assert [row.request_id for row, _ in listed] == [request_id]
    assert listed[0][0].holders_ceremony_id == snapshot.ceremony.ceremony_id
    assert await requests.approvals(TENANT, "anna", key.key_id, NOW) == []
    assert await requests.decline(TENANT, "anna", request_id, "no", NOW) == Refused("not_found")
    assert (
        await requests.approve(TENANT, "dora", request_id, _approval(scope), lambda *_: True, NOW)
        is None
    )


async def test_a_completed_request_keeps_its_k_when_a_resharing_raises_it(store, owner, archive):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    request_id, scope = await _file(archive, owner, key.key_id)
    requests = PostgresRecoveryRequests(archive._pool)
    for custodian in ("anna", "bernd"):
        await requests.approve(
            TENANT, custodian, request_id, _approval(scope), lambda *_: True, NOW
        )
    await owner.execute(
        "UPDATE recovery_requests SET status = 'completed', closed_at = $2 WHERE request_id = $1",
        uuid.UUID(request_id),
        NOW,
    )
    snapshot = await _reshare_and_deal(
        ceremonies, resharing, shares, k=3, custodians=("bernd", "carla", "dora", "emil")
    )
    await _confirm_all(ceremonies, snapshot, key.key_id)

    assert (await store.active_recovery_key(TENANT)).k == 3
    approved = await owner.fetchval(
        f"SELECT {_APPROVED} FROM recovery_requests r WHERE r.request_id = $1",
        uuid.UUID(request_id),
    )
    assert approved is True


async def test_a_filing_that_holds_the_key_row_is_seen_and_closed_by_activation(
    store, owner, archive
):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    await _confirm_one(ceremonies, snapshot, BERND, key.key_id)
    await _confirm_one(ceremonies, snapshot, DORA, key.key_id)
    request_id = uuid.uuid4()
    filer = await asyncpg.connect(APP_DSN, password=APP_PASSWORD)
    try:
        transaction = filer.transaction()
        await transaction.start()
        await filer.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
        # What a filing holds between reading the holders and inserting its request.
        holders = await filer.fetchval(
            "SELECT holders_ceremony_id FROM recovery_keys WHERE status = 'active' FOR SHARE"
        )
        last = asyncio.create_task(_confirm_one(ceremonies, snapshot, EMIL, key.key_id))
        await asyncio.sleep(0.5)
        assert not last.done()
        await filer.execute(
            "INSERT INTO recovery_requests (tenant_id, request_id, kind, requester_sub,"
            " requester_key_version, recovery_key_id, reason, request_signature, status,"
            " created_at, expires_at, holders_ceremony_id) VALUES ($1, $2, 'access', 'carla', 1,"
            " $3, 'why', $4, 'open', $5, $6, $7)",
            TENANT,
            request_id,
            uuid.UUID(key.key_id),
            bytes(64),
            NOW,
            NOW + timedelta(days=700),
            holders,
        )
        await transaction.commit()
        assert (await last)[2] == "active"
    finally:
        await filer.close()
    status = await owner.fetchval(
        "SELECT status FROM recovery_requests WHERE request_id = $1", request_id
    )
    assert status == "cancelled"


async def test_an_old_holder_learns_its_request_closed_at_activation(store, owner, archive):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    request_id, _ = await _file(archive, owner, key.key_id)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    await _confirm_all(ceremonies, snapshot, key.key_id)
    requests = PostgresRecoveryRequests(archive._pool)
    assert await requests.decline(TENANT, "anna", request_id, "no", NOW) == Refused("closed")
    assert await requests.decline(TENANT, "dora", request_id, "no", NOW) == Refused("not_found")


async def test_a_dealer_cannot_re_enrol_while_the_resharing_runs(store, owner, archive):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    await _reshare_and_deal(ceremonies, resharing, shares)
    swap = PostgresKeyReenrolment(archive._pool)
    assert await swap.check(TENANT, "anna", 1, NOW) == Refused("ceremony_in_progress")
    assert await swap.check(TENANT, "carla", 1, NOW) is None


async def test_the_swap_waits_for_an_activation_holding_the_key_row(store, owner, archive):
    ceremonies, _ = _services(store)
    await _first_generation(ceremonies)
    record = UserKeyRecord(
        TENANT,
        "carla",
        2,
        ref.public_point(801),
        ref.public_point(802),
        bytes([8]) * 32,
        b"sealed",
        NOW,
    )
    holder = await asyncpg.connect(APP_DSN, password=APP_PASSWORD)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT)
        await holder.execute("SELECT 1 FROM recovery_keys WHERE status = 'active' FOR UPDATE")
        swap = asyncio.create_task(PostgresKeyReenrolment(archive._pool).swap(record, 1, NOW))
        await asyncio.sleep(0.5)
        assert not swap.done()
        await transaction.rollback()
        assert await swap is None
    finally:
        await holder.close()


async def test_acceptance_old_archives_and_the_canary_open_with_the_new_custodians(
    store, owner, archive
):
    """#617's criterion: after a valid resharing, the canary and old archives open."""
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    conversation, conversation_key, _ = await _ended(archive, owner)
    ck = os.urandom(32)
    context = ecies.ck_wrap_context(
        TENANT, conversation.conversation_id, conversation_key, "recovery", key.key_id
    )
    wrap = ecies.seal(tags.CK_WRAP, key.recovery_public_key, ck, context)
    await owner.execute(
        "UPDATE key_wraps SET blob = $1 WHERE recipient_kind = 'recovery' AND key_id = $2",
        wrap.to_json(),
        uuid.UUID(conversation_key),
    )
    requests = PostgresRecoveryRequests(archive._pool)
    open_before, scope = await _file(archive, owner, key.key_id, sub="carla")
    for custodian in ("anna", "bernd"):
        await requests.approve(
            TENANT, custodian, open_before, _approval(scope), lambda *_: True, NOW
        )
    await owner.execute(
        "UPDATE recovery_requests SET status = 'completed', closed_at = $2 WHERE request_id = $1",
        uuid.UUID(open_before),
        NOW,
    )
    still_open, _ = await _file(archive, owner, key.key_id, sub="dora")

    snapshot = await _reshare_and_deal(
        ceremonies, resharing, shares, k=3, custodians=("bernd", "carla", "dora", "emil")
    )
    new = await _confirm_all(ceremonies, snapshot, key.key_id)

    status = await owner.fetchval(
        "SELECT status FROM recovery_requests WHERE request_id = $1", uuid.UUID(still_open)
    )
    assert status == "cancelled"
    approved = await owner.fetchval(
        f"SELECT {_APPROVED} FROM recovery_requests r WHERE r.request_id = $1",
        uuid.UUID(open_before),
    )
    assert approved is True

    # The conversation recorded before the resharing, requested by anna now and approved
    # by three new custodians with real partials.
    request_id, scope = await _file(
        archive, owner, key.key_id, sub="anna", conversation=conversation
    )
    ephemeral = decode_point(wrap.ephemeral)
    holders = {p.holder_ref: p.holder_index for p in snapshot.custodians}
    for custodian in ("carla", "dora", "emil"):
        index = holders[custodian]
        partial = encode_point(multiply(new[index], ephemeral))
        blob = json.dumps({"P": b64url(partial)})
        approval = Approval({k.key_id: blob for k in scope}, bytes(64))
        assert (
            await requests.approve(TENANT, custodian, request_id, approval, lambda *_: True, NOW)
            is None
        )
    served = await requests.partials(TENANT, "anna", request_id, NOW, may_supervise=True)
    assert served.holders_ceremony_id == snapshot.ceremony.ceremony_id
    partials = [
        (a.holder_index, decode_point(from_b64url(json.loads(a.blobs[conversation_key])["P"])))
        for a in served.approvals
    ]
    opened = ecies.open_with_shared_x(
        wrap, ref.combine_partials(partials), key.recovery_public_key, context
    )
    assert opened == ck

    canary = ecies.Sealed.from_json(key.canary_wrap, expected_type=tags.CK_WRAP)
    canary_partials = [
        (index, multiply(new[index], decode_point(canary.ephemeral))) for index in sorted(new)[:3]
    ]
    canary_context = ecies.ck_wrap_context(TENANT, "canary", key.key_id, "recovery", key.key_id)
    assert (
        len(
            ecies.open_with_shared_x(
                canary,
                ref.combine_partials(canary_partials),
                key.recovery_public_key,
                canary_context,
            )
        )
        == 32
    )


async def test_a_resharing_started_against_replaced_holders_is_refused(store, owner):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    await _confirm_all(ceremonies, snapshot, key.key_id)
    stale = CeremonyRecord(
        tenant_id=TENANT,
        ceremony_id=str(uuid.uuid4()),
        k=2,
        started_by=ORG_ADMIN,
        started_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        status="dealing",
        gateway_keys=(),
        kind="resharing",
        recovery_key_id=key.key_id,
        previous_transcript_hash=key.transcript_hash,
    )
    with pytest.raises(CeremonyError) as caught:
        await store.create_resharing(stale, (), (), [])
    assert caught.value.code == "HOLDERS_CHANGED"


async def test_activation_refuses_a_resharing_of_holders_that_were_replaced(store, owner):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    key = await store.active_recovery_key(TENANT)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    old = await owner.fetch("SELECT * FROM recovery_shares ORDER BY holder_index")
    # As if another resharing had moved the holders on while this one ran.
    await owner.execute("UPDATE recovery_keys SET holders_transcript_hash = $1", bytes(32))
    with pytest.raises(CeremonyError) as caught:
        await _confirm_all(ceremonies, snapshot, key.key_id)
    assert caught.value.code == "CEREMONY_ABORTED"
    reason = await owner.fetchval(
        "SELECT close_reason FROM recovery_ceremonies WHERE ceremony_id = $1",
        uuid.UUID(snapshot.ceremony.ceremony_id),
    )
    assert reason == "chain_invalid"
    assert await owner.fetch("SELECT * FROM recovery_shares ORDER BY holder_index") == old


async def test_a_lapsed_resharing_loses_its_sub_shares_when_next_read(store, owner):
    ceremonies, resharing = _services(store)
    shares = await _first_generation(ceremonies)
    snapshot = await _reshare_and_deal(ceremonies, resharing, shares)
    await owner.execute(
        "UPDATE recovery_ceremonies SET expires_at = $1 WHERE ceremony_id = $2",
        NOW,
        uuid.UUID(snapshot.ceremony.ceremony_id),
    )
    assert await store.open_ceremony(TENANT, NOW + timedelta(seconds=1)) is None
    sealed = await owner.fetch(
        "SELECT subshares FROM ceremony_dealings WHERE ceremony_id = $1",
        uuid.UUID(snapshot.ceremony.ceremony_id),
    )
    assert [json.loads(r["subshares"]) for r in sealed] == [{}, {}]
