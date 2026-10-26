"""The recovery-key proof verifiers reject forgeries (spec §20)."""

from __future__ import annotations

from services.api_gateway.recording.crypto.curve import ORDER, decode_point, encode_point
from services.api_gateway.recording.crypto.proofs import (
    verify_dleq,
    verify_schnorr,
    verify_subshare,
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
