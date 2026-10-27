"""The recovery-key ceremony end to end, and every refusal on its way (spec §9.2, §20)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.ceremony import CeremonyService, StartRequest
from services.api_gateway.recording.ceremony_model import CeremonyError
from services.api_gateway.recording.crypto import ecies, tags
from services.api_gateway.recording.crypto.curve import ORDER, decode_point, multiply
from services.api_gateway.recording.crypto.signatures import verify_fields, wrap_fields
from tests import recording_crypto_reference as ref
from tests.recording_ceremony_actors import (
    ANNA,
    BERND,
    CARLA,
    DEVICE,
    GATEWAY_SCALAR,
    ORG_ADMIN,
    POLYNOMIALS,
    TENANT,
    gateway_secrets,
)
from tests.recording_fakes import FakeCeremonyRepository, FakeCustodianDirectory

START = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
CUSTODIANS = (ANNA, BERND, CARLA)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def world():
    repository = FakeCeremonyRepository(keys={h.sub: h.key_record() for h in CUSTODIANS})
    directory = FakeCustodianDirectory({"anna": "Anna", "bernd": "Bernd", "carla": "Carla"})
    clock = Clock()
    service = CeremonyService(
        repository=repository,
        directory=directory,
        secrets=gateway_secrets(),
        clock=clock,
        new_id=lambda: "0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a",
    )
    return service, repository, directory, clock


def _request(k: int = 2, custodians=("anna", "bernd", "carla"), paper: bool = True):
    return StartRequest(k, tuple(custodians), DEVICE.enc_pub if paper else None)


async def _code(awaitable) -> str:
    with pytest.raises(CeremonyError) as caught:
        await awaitable
    return caught.value.code


async def _deal_all(service, tenant=TENANT):
    snapshot = (await service.state(tenant)).ceremony
    for holder in CUSTODIANS:
        snapshot = await service.deal(
            tenant,
            holder.sub,
            snapshot.ceremony.ceremony_id,
            holder.deal(snapshot, POLYNOMIALS[holder.sub]),
        )
    return (await service.state(tenant)).ceremony


async def _confirm_all(service, snapshot) -> dict[int, int]:
    ceremony_id = snapshot.ceremony.ceremony_id
    shares = {}
    for holder in CUSTODIANS:
        index = snapshot.custodian(holder.sub).holder_index
        received = await service.subshares(TENANT, holder.sub, ceremony_id)
        shares[index] = holder.share(snapshot, index, received[index])
        signature, sealed = holder.confirmation(
            snapshot, index, shares[index], snapshot.ceremony.transcript_hash
        )
        await service.confirm(TENANT, holder.sub, ceremony_id, signature, sealed)
    return shares


@pytest.mark.asyncio
async def test_a_full_ceremony_activates_a_key_no_party_ever_held(world):
    service, repository, _, _ = world
    started = await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    assert [p.holder_ref for p in started.participants] == [
        "anna",
        "bernd",
        "carla",
        "paper-1",
        "paper-2",
    ]

    snapshot = await _deal_all(service)
    assert snapshot.ceremony.status == "confirming"
    shares = await _confirm_all(service, snapshot)
    # Custodians are done; the key waits for the paper shares.
    assert repository.recovery_key is None

    paper = await service.subshares(TENANT, ORG_ADMIN, snapshot.ceremony.ceremony_id)
    for index, received in paper.items():
        shares[index] = DEVICE.share(snapshot, index, received)
    status = await service.confirm_paper(
        TENANT, ORG_ADMIN, snapshot.ceremony.ceremony_id, snapshot.ceremony.transcript_hash
    )
    assert status == "active"

    key = repository.recovery_key
    secret = sum(coefficients[0] for coefficients in POLYNOMIALS.values()) % ORDER
    assert key.recovery_public_key == ref.public_point(secret)
    assert (key.k, key.n, key.mode) == (2, 5, "enhanced")
    # Test-only reconstruction: any k shares give x, custodian or paper.
    for pair in ((1, 3), (4, 5), (2, 5)):
        lagrange = [ref.lagrange_at_zero(i, pair) for i in pair]
        assert sum(lam * shares[i] for lam, i in zip(lagrange, pair)) % ORDER == secret
    assert [s.encrypted_share is None for s in repository.shares] == [
        False,
        False,
        False,
        True,
        True,
    ]
    assert [e.event_type for e in repository.audit][-1] == "recovery_key_activated"


@pytest.mark.asyncio
async def test_the_canary_is_signed_for_the_transcript_and_opens_with_k_partials(world):
    service, repository, _, _ = world
    await service.start(TENANT, ORG_ADMIN, _request(paper=False), "corr")
    shares = await _confirm_all(service, await _deal_all(service))
    key = repository.recovery_key

    sealed = ecies.Sealed.from_json(key.canary_wrap, expected_type=tags.CK_WRAP)
    signed = wrap_fields(
        TENANT, "canary", key.key_id, sealed.ephemeral, "recovery", key.key_id, key.transcript_hash
    )
    assert verify_fields(
        ref.public_point(GATEWAY_SCALAR), key.canary_signature, tags.WRAP_SIG, *signed
    )
    ephemeral = decode_point(sealed.ephemeral)
    partials = [(i, multiply(shares[i], ephemeral)) for i in (1, 3)]
    context = ecies.ck_wrap_context(TENANT, "canary", key.key_id, "recovery", key.key_id)
    opened = ecies.open_with_shared_x(
        sealed, ref.combine_partials(partials), key.recovery_public_key, context
    )
    assert len(opened) == 32
    with pytest.raises(ecies.SealedPayloadError):
        ecies.open_with_shared_x(
            sealed, ref.combine_partials(partials[:1]), key.recovery_public_key, context
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_", "code"),
    [
        (_request(k=0), "INVALID_CEREMONY"),
        (_request(k=6), "INVALID_CEREMONY"),
        (_request(k=3), "INVALID_CEREMONY"),
        (_request(custodians=("anna", "anna", "bernd")), "INVALID_CEREMONY"),
        (_request(custodians=("anna", "bernd", "eva")), "NOT_A_CUSTODIAN"),
        (replace(_request(), paper_device_pub=b"\x04" + bytes(64)), "INVALID_CEREMONY"),
    ],
)
async def test_a_malformed_start_is_refused(world, request_, code):
    service = world[0]
    assert await _code(service.start(TENANT, ORG_ADMIN, request_, "corr")) == code


@pytest.mark.asyncio
async def test_the_ceremony_device_may_not_belong_to_a_custodian(world):
    code = await _code(world[0].start(TENANT, "anna", _request(), "corr"))
    assert code == "INVALID_CEREMONY"


@pytest.mark.asyncio
async def test_every_custodian_needs_an_enrolled_key(world):
    service, repository, _, _ = world
    del repository.keys["carla"]
    code = await _code(service.start(TENANT, ORG_ADMIN, _request(), "corr"))
    assert code == "CUSTODIAN_NOT_ENROLLED"


@pytest.mark.asyncio
async def test_studio_unreachable_refuses_rather_than_trusting_stale_names(world):
    service, _, directory, _ = world
    directory.names = None
    with pytest.raises(CeremonyError) as caught:
        await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    assert (caught.value.status, caught.value.code) == (503, "DIRECTORY_UNAVAILABLE")


@pytest.mark.asyncio
async def test_one_ceremony_at_a_time_and_none_once_a_key_exists(world):
    service, repository, _, _ = world
    await service.start(TENANT, ORG_ADMIN, _request(paper=False), "corr")
    second = await _code(service.start(TENANT, ORG_ADMIN, _request(paper=False), "corr"))
    assert second == "CEREMONY_IN_PROGRESS"
    await _confirm_all(service, await _deal_all(service))
    after = await _code(service.start(TENANT, ORG_ADMIN, _request(paper=False), "corr"))
    assert after == "RECOVERY_KEY_EXISTS"


def _forged_proof(submission, snapshot):
    # Signed by the dealer, so only the proof check can catch it.
    forged = (submission.proof_s + 1) % ORDER
    signature = ANNA.dealing_signature(snapshot, submission.commitments, submission.proof_c, forged)
    return replace(submission, proof_s=forged, signature=signature)


def _signed_by_someone_else(submission, snapshot):
    # Bernd's key over Anna's dealing: valid for nobody at Anna's index.
    holder = replace(ANNA, sig_scalar=BERND.sig_scalar)
    return replace(submission, signature=holder.deal(snapshot, POLYNOMIALS["anna"]).signature)


def _missing_subshare(submission, snapshot):
    return replace(submission, subshares={i: s for i, s in submission.subshares.items() if i != 2})


def _wrong_degree(submission, snapshot):
    return replace(submission, commitments=submission.commitments[:1])


def _share_instead_of_subshare(submission, snapshot):
    text = ecies.seal(tags.SHARE, ANNA.enc_pub, bytes(32), ("x",)).to_json()
    return replace(submission, subshares={**submission.subshares, 1: text})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tamper", "code"),
    [
        (_forged_proof, "INVALID_DEALING"),
        (_signed_by_someone_else, "INVALID_DEALING"),
        (_missing_subshare, "INVALID_DEALING"),
        (_wrong_degree, "INVALID_DEALING"),
        (_share_instead_of_subshare, "INVALID_PAYLOAD"),
    ],
)
async def test_a_tampered_dealing_is_refused(world, tamper, code):
    service = world[0]
    snapshot = await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    submission = tamper(ANNA.deal(snapshot, POLYNOMIALS["anna"]), snapshot)
    assert await _code(service.deal(TENANT, "anna", snapshot.ceremony.ceremony_id, submission)) == (
        code
    )


@pytest.mark.asyncio
async def test_only_participants_deal_and_only_once(world):
    service = world[0]
    snapshot = await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    ceremony_id = snapshot.ceremony.ceremony_id
    dealing = ANNA.deal(snapshot, POLYNOMIALS["anna"])
    assert await _code(service.deal(TENANT, ORG_ADMIN, ceremony_id, dealing)) == (
        "NOT_A_PARTICIPANT"
    )
    await service.deal(TENANT, "anna", ceremony_id, dealing)
    assert await _code(service.deal(TENANT, "anna", ceremony_id, dealing)) == "ALREADY_SUBMITTED"


@pytest.mark.asyncio
async def test_sub_shares_are_released_only_after_every_dealing(world):
    service = world[0]
    snapshot = await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    ceremony_id = snapshot.ceremony.ceremony_id
    assert await _code(service.subshares(TENANT, "anna", ceremony_id)) == "CEREMONY_STATE"
    await _deal_all(service)
    assert set(await service.subshares(TENANT, "anna", ceremony_id)) == {1}
    assert set(await service.subshares(TENANT, ORG_ADMIN, ceremony_id)) == {4, 5}
    assert await _code(service.subshares(TENANT, "eva", ceremony_id)) == "NOT_A_PARTICIPANT"


@pytest.mark.asyncio
async def test_the_last_dealing_hands_back_a_ceremony_ready_for_signatures(world):
    service = world[0]
    snapshot = await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    for holder in CUSTODIANS:
        snapshot = await service.deal(
            TENANT,
            holder.sub,
            snapshot.ceremony.ceremony_id,
            holder.deal(snapshot, POLYNOMIALS[holder.sub]),
        )
    assert snapshot.ceremony.status == "confirming"
    assert (
        snapshot.ceremony.transcript_hash
        == (await service.state(TENANT)).ceremony.ceremony.transcript_hash
    )


@pytest.mark.asyncio
async def test_a_failed_activation_leaves_the_last_signature_to_be_sent_again(world, monkeypatch):
    service, repository, _, _ = world
    await service.start(TENANT, ORG_ADMIN, _request(paper=False), "corr")
    snapshot = await _deal_all(service)
    ceremony_id = snapshot.ceremony.ceremony_id
    signed = {}
    for holder in CUSTODIANS:
        index = snapshot.custodian(holder.sub).holder_index
        received = await service.subshares(TENANT, holder.sub, ceremony_id)
        share = holder.share(snapshot, index, received[index])
        signed[holder.sub] = holder.confirmation(
            snapshot, index, share, snapshot.ceremony.transcript_hash
        )
    for holder in (ANNA, BERND):
        assert await service.confirm(TENANT, holder.sub, ceremony_id, *signed[holder.sub]) == (
            "confirming"
        )

    def broken(_snapshot):
        raise RuntimeError("signing failed")

    monkeypatch.setattr(service, "_recovery_key", broken)
    with pytest.raises(RuntimeError):
        await service.confirm(TENANT, "carla", ceremony_id, *signed["carla"])
    assert repository.recovery_key is None
    assert not (await service.state(TENANT)).ceremony.has_confirmed(3)

    monkeypatch.undo()
    assert await service.confirm(TENANT, "carla", ceremony_id, *signed["carla"]) == "active"
    assert repository.recovery_key is not None


@pytest.mark.asyncio
async def test_a_signature_over_another_transcript_is_refused(world):
    service = world[0]
    await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    snapshot = await _deal_all(service)
    received = await service.subshares(TENANT, "anna", snapshot.ceremony.ceremony_id)
    share = ANNA.share(snapshot, 1, received[1])
    signature, sealed = ANNA.confirmation(snapshot, 1, share, bytes(32))
    code = await _code(
        service.confirm(TENANT, "anna", snapshot.ceremony.ceremony_id, signature, sealed)
    )
    assert code == "INVALID_CONFIRMATION"


@pytest.mark.asyncio
async def test_the_device_must_agree_on_the_transcript(world):
    service = world[0]
    await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    snapshot = await _deal_all(service)
    ceremony_id = snapshot.ceremony.ceremony_id
    assert await _code(service.confirm_paper(TENANT, ORG_ADMIN, ceremony_id, bytes(32))) == (
        "TRANSCRIPT_MISMATCH"
    )
    transcript = snapshot.ceremony.transcript_hash
    assert await _code(service.confirm_paper(TENANT, "anna", ceremony_id, transcript)) == (
        "NOT_A_PARTICIPANT"
    )


@pytest.mark.asyncio
async def test_a_participant_aborts_and_the_tenant_may_start_again(world):
    service, repository, _, _ = world
    snapshot = await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    ceremony_id = snapshot.ceremony.ceremony_id
    assert await _code(service.abort(TENANT, "eva", ceremony_id, "cancelled")) == (
        "NOT_A_PARTICIPANT"
    )
    assert await _code(service.abort(TENANT, "anna", ceremony_id, "bored")) == "INVALID_REASON"
    await service.abort(TENANT, "anna", ceremony_id, "proof_invalid")
    state = await service.state(TENANT)
    assert state.ceremony is None
    assert repository.audit[-1].object_ref == f"ceremony:{ceremony_id}:proof_invalid"
    # Everyone learns why it ended, not only the browser whose check failed.
    assert (state.last_failed.ceremony_id, state.last_failed.reason) == (
        ceremony_id,
        "proof_invalid",
    )
    await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    assert (await service.state(TENANT)).last_failed is None


@pytest.mark.asyncio
async def test_an_expired_ceremony_is_over(world):
    service, _, _, clock = world
    snapshot = await service.start(TENANT, ORG_ADMIN, _request(), "corr")
    clock.now = START + timedelta(hours=24)
    state = await service.state(TENANT)
    assert state.ceremony is None
    assert (state.last_failed.reason, state.last_failed.ended_at) == ("expired", clock.now)
    dealing = ANNA.deal(snapshot, POLYNOMIALS["anna"])
    assert await _code(service.deal(TENANT, "anna", snapshot.ceremony.ceremony_id, dealing)) == (
        "NO_CEREMONY"
    )


@pytest.mark.asyncio
async def test_candidates_list_custodians_with_their_enrolment(world):
    service, repository, directory, _ = world
    directory.names = {"anna": "Anna", "zoe": "Zoe"}
    candidates = await service.candidates(TENANT, "corr")
    assert [(c.sub, c.fingerprint is not None) for c in candidates] == [
        ("anna", True),
        ("zoe", False),
    ]
