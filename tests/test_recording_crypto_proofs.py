"""The recovery-key proof verifiers reject forgeries (spec §20)."""

from __future__ import annotations

import pytest

from services.api_gateway.recording.crypto.curve import ORDER, decode_point, encode_point
from services.api_gateway.recording.crypto.proofs import (
    lagrange_at_zero,
    verify_dleq,
    verify_schnorr,
    verify_share_proof,
    verify_subshare,
)
from services.api_gateway.recording.crypto.signatures import (
    participants_digest,
    reshare_dealing_fields,
)
from tests import recording_crypto_reference as ref

TENANT, CEREMONY, REQUEST, KEY = "t1", "c1", "r1", "k1"


def test_a_forged_schnorr_proof_is_rejected():
    c, s = ref.schnorr_prove(TENANT, CEREMONY, 1, secret=5, nonce=9)
    commitment = ref.public_point(5)
    assert verify_schnorr(TENANT, CEREMONY, 1, commitment, c, s)
    assert not verify_schnorr(TENANT, CEREMONY, 1, commitment, c, (s + 1) % ORDER)
    assert not verify_schnorr(TENANT, CEREMONY, 2, commitment, c, s)
    assert not verify_schnorr(TENANT, CEREMONY, 1, ref.public_point(6), c, s)
    assert not verify_schnorr(TENANT, CEREMONY, 1, commitment, c, ORDER)


def test_a_forged_partial_is_rejected():
    ephemeral = decode_point(ref.public_point(13))
    partial, c, s = ref.dleq_prove(TENANT, REQUEST, KEY, 2, share=21, ephemeral=ephemeral, nonce=4)
    statement = (ref.public_point(21), encode_point(ephemeral), partial)
    assert verify_dleq(TENANT, REQUEST, KEY, 2, statement, c, s)
    wrong_partial = (statement[0], statement[1], ref.public_point(99))
    assert not verify_dleq(TENANT, REQUEST, KEY, 2, wrong_partial, c, s)
    assert not verify_dleq(TENANT, REQUEST, KEY, 3, statement, c, s)


def test_a_subshare_inconsistent_with_its_commitments_is_rejected():
    coefficients = [17, 23]
    commitments = ref.commitments(coefficients)
    assert verify_subshare(3, ref.evaluate(coefficients, 3), commitments)
    assert not verify_subshare(3, ref.evaluate(coefficients, 3) + 1, commitments)
    assert not verify_subshare(3, 0, commitments)


def test_fewer_than_k_partials_do_not_recover_the_key():
    # x = 100 shared 2-of-3 by f(i) = 100 + 7i.
    shares = {i: ref.evaluate([100, 7], i) for i in (1, 2, 3)}
    ephemeral = decode_point(ref.public_point(31))
    full = ref.combine_partials(
        [
            (i, decode_point(ref.dleq_prove("t", "r", "k", i, shares[i], ephemeral, 3)[0]))
            for i in (1, 3)
        ]
    )
    expected = decode_point(ref.public_point(100 * 31 % ORDER))[0].to_bytes(32, "big")
    assert full == expected
    one = ref.combine_partials(
        [(1, decode_point(ref.dleq_prove("t", "r", "k", 1, shares[1], ephemeral, 3)[0]))]
    )
    assert one != expected


def test_lagrange_weights_over_any_dealer_set_rebuild_the_secret():
    coefficients = [41, 7, 19]
    for indices in ([1, 2, 3], [2, 4, 5], [1, 3, 9]):
        total = sum(
            lagrange_at_zero(i, indices) * ref.evaluate(coefficients, i) for i in indices
        ) % ORDER
        assert total == 41
    assert lagrange_at_zero(3, [1, 3]) == ref.lagrange_at_zero(3, [1, 3])


def test_lagrange_refuses_repeated_or_zero_indices():
    for indices in ([1, 1], [0, 2]):
        with pytest.raises(ValueError):
            lagrange_at_zero(indices[-1], indices)


def test_a_forged_share_proof_is_rejected():
    c, s = ref.share_proof_prove(TENANT, CEREMONY, 2, share=33, nonce=8)
    public = ref.public_point(33)
    assert verify_share_proof(TENANT, CEREMONY, 2, public, c, s)
    assert not verify_share_proof(TENANT, CEREMONY, 2, public, c, (s + 1) % ORDER)
    assert not verify_share_proof(TENANT, CEREMONY, 3, public, c, s)
    assert not verify_share_proof(TENANT, "c2", 2, public, c, s)
    assert not verify_share_proof(TENANT, CEREMONY, 2, ref.public_point(34), c, s)
    assert not verify_share_proof(TENANT, CEREMONY, 2, public, ORDER, s)
    assert not verify_share_proof(TENANT, CEREMONY, 2, b"\x04" + bytes(64), c, s)


def test_a_share_proof_is_not_a_dealing_proof():
    c, s = ref.schnorr_prove(TENANT, CEREMONY, 2, secret=33, nonce=8)
    assert not verify_share_proof(TENANT, CEREMONY, 2, ref.public_point(33), c, s)


def test_the_participant_digest_binds_every_index_ref_and_fingerprint():
    people = [(1, "carol", bytes([1]) * 32), (2, "dave", bytes([2]) * 32)]
    digest = participants_digest(people)
    assert len(digest) == 32
    assert participants_digest(list(reversed(people))) == digest
    for changed in (
        [(1, "carol", bytes([1]) * 32), (3, "dave", bytes([2]) * 32)],
        [(1, "carol", bytes([1]) * 32), (2, "erin", bytes([2]) * 32)],
        [(1, "carol", bytes([1]) * 32), (2, "dave", bytes([9]) * 32)],
        people[:1],
    ):
        assert participants_digest(changed) != digest


def test_a_resharing_dealer_signs_the_previous_transcript_and_the_new_set():
    commitments = ref.commitments([5, 6])
    previous, digest = bytes([7]) * 32, bytes([8]) * 32
    fields = reshare_dealing_fields(TENANT, CEREMONY, 4, commitments, 1, 2, previous, digest)
    assert fields[:4] == (TENANT, CEREMONY, 4, 2)
    assert fields[-2:] == (previous, digest)
    assert fields[4:6] == commitments
