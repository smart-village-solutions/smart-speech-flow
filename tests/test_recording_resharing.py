"""Resharing end to end over the fake store, and every refusal on its way (spec §9.7)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.ceremony import CeremonyService, StartRequest
from services.api_gateway.recording.ceremony_model import CeremonyError, CeremonySnapshot
from services.api_gateway.recording.crypto.curve import ORDER
from services.api_gateway.recording.resharing import ResharingService
from services.api_gateway.recording.resharing_model import (
    ResharingStart,
    contribution,
    end_to_end_holds,
    new_public_shares,
)
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
    TENANT,
    gateway_secrets,
    reshare_dealing,
    share_proof,
)
from tests.recording_fakes import FakeCeremonyRepository, FakeCustodianDirectory

START = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
FIRST = (ANNA, BERND, CARLA)
HOLDERS = {h.sub: h for h in (ANNA, BERND, CARLA, DORA, EMIL)}
SECRET = sum(coefficients[0] for coefficients in POLYNOMIALS.values()) % ORDER
RESHARING_ID = "5a1e7c3d-0b2f-4e6a-9c8d-7f6e5d4c3b2a"
FIRST_ID = "0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a"


@dataclass
class World:
    ceremonies: CeremonyService
    resharing: ResharingService
    repository: FakeCeremonyRepository
    # Every holder's share of the first generation, custodians and paper.
    shares: dict[int, int]


async def _first_generation(ceremonies: CeremonyService) -> dict[int, int]:
    await ceremonies.start(
        TENANT, ORG_ADMIN, StartRequest(2, ("anna", "bernd", "carla"), DEVICE.enc_pub), "c"
    )
    snapshot = (await ceremonies.state(TENANT)).ceremony
    for holder in FIRST:
        snapshot = await ceremonies.deal(
            TENANT,
            holder.sub,
            snapshot.ceremony.ceremony_id,
            holder.deal(snapshot, POLYNOMIALS[holder.sub]),
        )
    ceremony_id = snapshot.ceremony.ceremony_id
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


SECRETS = gateway_secrets()


def _sealed_key(holder):
    """A key record whose blob the server layer opens, as an enrolled one does."""
    blob = SECRETS.server_layer.seal(b'{"blob": 1}', tenant_id=TENANT, user_sub=holder.sub)
    return replace(holder.key_record(), encrypted_private=blob)


@pytest.fixture
async def world() -> World:
    repository = FakeCeremonyRepository(keys={h.sub: _sealed_key(h) for h in HOLDERS.values()})
    directory = FakeCustodianDirectory({sub: sub.title() for sub in HOLDERS})
    ids = iter([FIRST_ID, RESHARING_ID])
    ticks = iter(range(10_000))

    def clock() -> datetime:
        return START + timedelta(seconds=next(ticks))

    ceremonies = CeremonyService(
        repository=repository,
        directory=directory,
        secrets=gateway_secrets(),
        clock=clock,
        new_id=lambda: next(ids),
    )
    resharing = ResharingService(
        repository=repository,
        directory=directory,
        server_layer=SECRETS.server_layer,
        clock=clock,
        new_id=lambda: RESHARING_ID,
    )
    shares = await _first_generation(ceremonies)
    return World(ceremonies, resharing, repository, shares)


def _start(k=2, custodians=("bernd", "dora", "emil"), dealers=(1, 4), device=None):
    return ResharingStart(k, tuple(custodians), tuple(dealers), device, FIRST_ID)


async def _code(awaitable) -> str:
    with pytest.raises(CeremonyError) as caught:
        await awaitable
    return caught.value.code


async def _snapshot(world: World) -> CeremonySnapshot:
    return (await world.ceremonies.state(TENANT)).ceremony


async def _deal(world: World, snapshot: CeremonySnapshot) -> CeremonySnapshot:
    """Anna deals her share 1, the device types in paper sheet 4; degree k'−1 each."""
    tail = list(range(61, 60 + snapshot.ceremony.k))
    await world.ceremonies.deal(
        TENANT, "anna", RESHARING_ID, reshare_dealing(snapshot, 1, world.shares[1], tail, ANNA)
    )
    sheet = reshare_dealing(snapshot, 4, world.shares[4], [t + 10 for t in tail], None)
    await world.resharing.paper_deal(TENANT, ORG_ADMIN, RESHARING_ID, 4, sheet)
    return await _snapshot(world)


async def _confirm(world: World, snapshot: CeremonySnapshot, *, proof=True) -> dict[int, int]:
    key_id = world.repository.recovery_key.key_id
    shares, status = {}, None
    for participant in snapshot.custodians:
        holder = HOLDERS[participant.holder_ref]
        index = participant.holder_index
        received = await world.ceremonies.subshares(TENANT, holder.sub, RESHARING_ID)
        shares[index] = holder.share(snapshot, index, received[index])
        signature, sealed = holder.confirmation(
            snapshot, index, shares[index], snapshot.ceremony.transcript_hash, key_id
        )
        status = await world.ceremonies.confirm(
            TENANT,
            holder.sub,
            RESHARING_ID,
            signature,
            sealed,
            share_proof(snapshot, index, shares[index]) if proof else None,
        )
    assert status == "active"
    return shares


async def test_a_resharing_moves_the_shares_and_keeps_x(world):
    before = world.repository.recovery_key
    started = await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    assert [(p.holder_index, p.holder_ref) for p in started.participants] == [
        (1, "bernd"),
        (2, "dora"),
        (3, "emil"),
    ]
    assert [(d.dealer_index, d.holder_ref, d.kind) for d in started.dealers] == [
        (1, "anna", "custodian"),
        (4, "paper-1", "paper"),
    ]
    assert started.ceremony.previous_transcript_hash == before.transcript_hash

    snapshot = await _deal(world, await _snapshot(world))
    assert snapshot.ceremony.status == "confirming"
    new = await _confirm(world, snapshot)

    key = world.repository.recovery_key
    assert (key.key_id, key.recovery_public_key, key.transcript_hash) == (
        before.key_id,
        before.recovery_public_key,
        before.transcript_hash,
    )
    assert key.current_holders == (RESHARING_ID, snapshot.ceremony.transcript_hash)
    assert (key.k, key.n) == (2, 3)
    for pair in ((1, 2), (2, 3), (1, 3)):
        assert sum(ref.lagrange_at_zero(i, pair) * new[i] for i in pair) % ORDER == SECRET
    assert [s.holder_ref for s in world.repository.shares] == ["bernd", "dora", "emil"]
    assert world.repository.audit[-1].event_type == "recovery_key_reshared"


async def test_the_threshold_may_change(world):
    await world.resharing.start(
        TENANT, ORG_ADMIN, _start(k=3, custodians=("anna", "bernd", "dora", "emil")), "c"
    )
    new = await _confirm(world, await _deal(world, await _snapshot(world)))
    assert world.repository.recovery_key.k == 3
    triple = (1, 2, 4)
    assert sum(ref.lagrange_at_zero(i, triple) * new[i] for i in triple) % ORDER == SECRET


@pytest.mark.parametrize(
    ("start", "code"),
    [
        (_start(k=0), "INVALID_CEREMONY"),
        (_start(k=3), "INVALID_CEREMONY"),
        (_start(custodians=("dora", "dora", "emil")), "INVALID_CEREMONY"),
        (_start(dealers=(1,)), "INVALID_DEALERS"),
        (_start(dealers=(1, 1)), "INVALID_DEALERS"),
        (_start(dealers=(1, 2, 3)), "INVALID_DEALERS"),
        (_start(dealers=(1, 9)), "INVALID_DEALERS"),
        (_start(custodians=("dora", "emil", "zoe")), "NOT_A_CUSTODIAN"),
        (_start(device=b"\x04" + bytes(64)), "INVALID_CEREMONY"),
    ],
)
async def test_a_malformed_resharing_is_refused(world, start, code):
    assert await _code(world.resharing.start(TENANT, ORG_ADMIN, start, "c")) == code


async def test_a_new_custodian_needs_a_key(world):
    del world.repository.keys["emil"]
    assert (
        await _code(world.resharing.start(TENANT, ORG_ADMIN, _start(), "c"))
        == "CUSTODIAN_NOT_ENROLLED"
    )


async def test_a_dealer_whose_share_is_lost_is_refused(world):
    world.repository.unusable.add("anna")
    assert await _code(world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")) == "DEALER_UNUSABLE"


async def test_only_an_existing_key_is_reshared(world):
    world.repository.recovery_key = None
    assert await _code(world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")) == "NO_RECOVERY_KEY"


@pytest.mark.parametrize("starter", ["anna", "dora"])
async def test_the_device_may_not_belong_to_an_old_or_new_custodian(world, starter):
    assert await _code(world.resharing.start(TENANT, starter, _start(), "c")) == "INVALID_CEREMONY"


async def test_a_custodian_may_start_when_no_sheet_and_no_device_are_involved(world):
    started = await world.resharing.start(TENANT, "anna", _start(dealers=(1, 2)), "c")
    assert started.ceremony.started_by == "anna"


async def test_dealers_chosen_from_an_older_generation_are_refused(world):
    stale = replace(_start(), holders_ceremony_id="00000000-0000-4000-8000-000000000000")
    assert await _code(world.resharing.start(TENANT, ORG_ADMIN, stale, "c")) == "HOLDERS_CHANGED"


async def test_a_dealer_gets_nothing_once_it_has_dealt(world):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    snapshot = await _snapshot(world)
    await world.ceremonies.deal(
        TENANT, "anna", RESHARING_ID, reshare_dealing(snapshot, 1, world.shares[1], [61], ANNA)
    )
    assert await _code(world.resharing.dealer(TENANT, "anna", RESHARING_ID)) == "CEREMONY_STATE"


async def test_one_ceremony_at_a_time(world):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    assert (
        await _code(world.resharing.start(TENANT, ORG_ADMIN, _start(), "c"))
        == "CEREMONY_IN_PROGRESS"
    )


async def test_only_listed_dealers_deal_and_only_once(world):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    snapshot = await _snapshot(world)
    # Bernd is new holder 1, but old holder 2 is not a dealer.
    dealing = reshare_dealing(snapshot, 2, world.shares[2], [61], BERND)
    assert (
        await _code(world.ceremonies.deal(TENANT, "bernd", RESHARING_ID, dealing))
        == "NOT_A_PARTICIPANT"
    )
    good = reshare_dealing(snapshot, 1, world.shares[1], [61], ANNA)
    await world.ceremonies.deal(TENANT, "anna", RESHARING_ID, good)
    assert (
        await _code(world.ceremonies.deal(TENANT, "anna", RESHARING_ID, good))
        == "ALREADY_SUBMITTED"
    )


def _wrong_share(world, snapshot):
    return reshare_dealing(snapshot, 1, world.shares[1] + 1, [61], ANNA)


def _unweighted(world, snapshot):
    return reshare_dealing(snapshot, 1, world.shares[1], [61], ANNA, weight=1)


def _unsigned(world, snapshot):
    return reshare_dealing(snapshot, 1, world.shares[1], [61], None)


def _signed_for_another_set(world, snapshot):
    other = replace(snapshot, participants=snapshot.participants[:2])
    return replace(
        reshare_dealing(snapshot, 1, world.shares[1], [61], ANNA),
        signature=reshare_dealing(other, 1, world.shares[1], [61], ANNA).signature,
    )


def _signed_for_another_generation(world, snapshot):
    other = replace(
        snapshot, ceremony=replace(snapshot.ceremony, previous_transcript_hash=bytes(32))
    )
    return replace(
        reshare_dealing(snapshot, 1, world.shares[1], [61], ANNA),
        signature=reshare_dealing(other, 1, world.shares[1], [61], ANNA).signature,
    )


def _signed_by_someone_else(world, snapshot):
    return reshare_dealing(snapshot, 1, world.shares[1], [61], BERND)


@pytest.mark.parametrize(
    "tamper",
    [
        _wrong_share,
        _unweighted,
        _unsigned,
        _signed_for_another_set,
        _signed_for_another_generation,
        _signed_by_someone_else,
    ],
)
async def test_a_bad_custodian_dealing_is_refused(world, tamper):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    dealing = tamper(world, await _snapshot(world))
    assert (
        await _code(world.ceremonies.deal(TENANT, "anna", RESHARING_ID, dealing))
        == "INVALID_DEALING"
    )


async def test_paper_dealings_come_from_the_starter_for_paper_dealers_unsigned(world):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    snapshot = await _snapshot(world)
    sheet = reshare_dealing(snapshot, 4, world.shares[4], [71], None)
    assert (
        await _code(world.resharing.paper_deal(TENANT, "bernd", RESHARING_ID, 4, sheet))
        == "NOT_A_PARTICIPANT"
    )
    # Even a dealing anna signed is not the device's to send for her.
    anna = reshare_dealing(snapshot, 1, world.shares[1], [61], ANNA)
    assert (
        await _code(world.resharing.paper_deal(TENANT, ORG_ADMIN, RESHARING_ID, 1, anna))
        == "INVALID_DEALING"
    )
    signed = replace(
        sheet, signature=reshare_dealing(snapshot, 4, world.shares[4], [71], ANNA).signature
    )
    assert (
        await _code(world.resharing.paper_deal(TENANT, ORG_ADMIN, RESHARING_ID, 4, signed))
        == "INVALID_DEALING"
    )
    typo = reshare_dealing(snapshot, 4, world.shares[4] + 1, [71], None)
    assert (
        await _code(world.resharing.paper_deal(TENANT, ORG_ADMIN, RESHARING_ID, 4, typo))
        == "INVALID_DEALING"
    )
    await world.resharing.paper_deal(TENANT, ORG_ADMIN, RESHARING_ID, 4, sheet)


async def test_paper_dealing_needs_a_resharing_in_progress(world):
    snapshot = await _snapshot(world)
    assert snapshot is None
    sheet = object()
    code = await _code(world.resharing.paper_deal(TENANT, ORG_ADMIN, RESHARING_ID, 4, sheet))
    assert code == "NO_CEREMONY"


async def test_a_confirmation_without_a_good_share_proof_is_refused(world):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    snapshot = await _deal(world, await _snapshot(world))
    received = await world.ceremonies.subshares(TENANT, "bernd", RESHARING_ID)
    share = BERND.share(snapshot, 1, received[1])
    key_id = world.repository.recovery_key.key_id
    signature, sealed = BERND.confirmation(
        snapshot, 1, share, snapshot.ceremony.transcript_hash, key_id
    )
    for proof in (None, share_proof(snapshot, 1, share + 1), share_proof(snapshot, 2, share)):
        code = await _code(
            world.ceremonies.confirm(TENANT, "bernd", RESHARING_ID, signature, sealed, proof)
        )
        assert code == "INVALID_CONFIRMATION"


async def test_shares_that_do_not_rebuild_x_abort_and_keep_the_old_holders(world):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    snapshot = await _deal(world, await _snapshot(world))
    old_shares = list(world.repository.shares)
    # As if X had been tampered with in storage after the dealings were checked.
    world.repository.recovery_key = replace(
        world.repository.recovery_key, recovery_public_key=ref.public_point(5)
    )
    with pytest.raises(CeremonyError) as caught:
        await _confirm(world, snapshot)
    assert caught.value.code == "CEREMONY_ABORTED"
    assert world.repository.shares == old_shares
    assert world.repository.aborted[RESHARING_ID].reason == "canary_failed"


async def test_dealers_and_new_custodians_may_abort_but_never_with_the_gateway_reason(world):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    assert (
        await _code(world.ceremonies.abort(TENANT, "anna", RESHARING_ID, "canary_failed"))
        == "INVALID_REASON"
    )
    assert (
        await _code(world.ceremonies.abort(TENANT, "carla", RESHARING_ID, "cancelled"))
        == "NOT_A_PARTICIPANT"
    )
    await world.ceremonies.abort(TENANT, "anna", RESHARING_ID, "contribution_invalid")
    state = await world.ceremonies.state(TENANT)
    assert state.recovery_key is not None
    assert state.last_failed.reason == "contribution_invalid"


async def test_a_dealer_gets_its_share_and_the_key_that_opens_it(world):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    material = await world.resharing.dealer(TENANT, "anna", RESHARING_ID)
    assert (material.dealer_index, material.key.user_sub, material.blob) == (
        1,
        "anna",
        '{"blob": 1}',
    )
    assert material.encrypted_share == world.repository.shares[0].encrypted_share
    assert world.repository.audit[-1].event_type == "key_blob_read"
    assert await _code(world.resharing.dealer(TENANT, "dora", RESHARING_ID)) == "NOT_A_PARTICIPANT"
    world.repository.unusable.add("anna")
    assert await _code(world.resharing.dealer(TENANT, "anna", RESHARING_ID)) == "DEALER_UNUSABLE"


async def test_the_dealer_route_is_for_resharings_only(world):
    world.repository.recovery_key = None
    await world.ceremonies.start(TENANT, ORG_ADMIN, StartRequest(1, ("dora", "emil"), None), "c")
    ceremony_id = (await _snapshot(world)).ceremony.ceremony_id
    assert await _code(world.resharing.dealer(TENANT, "dora", ceremony_id)) == "CEREMONY_STATE"


def test_a_contribution_is_the_lagrange_weighted_public_share():
    weight = ref.lagrange_at_zero(1, [1, 4])
    assert contribution(1, [1, 4], ref.public_point(9)) == ref.public_point(weight * 9 % ORDER)


async def test_the_end_to_end_check_needs_the_real_x(world):
    await world.resharing.start(TENANT, ORG_ADMIN, _start(), "c")
    snapshot = await _deal(world, await _snapshot(world))
    x = world.repository.recovery_key.recovery_public_key
    assert end_to_end_holds(snapshot, x)
    assert not end_to_end_holds(snapshot, ref.public_point(5))
    assert set(new_public_shares(snapshot)) == {1, 2, 3}
