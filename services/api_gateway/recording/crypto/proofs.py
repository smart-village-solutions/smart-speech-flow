"""Verifiers for the recovery-key proofs (spec Appendix A.7, A.8).

Only verification lives here. Proving needs a secret scalar, and secrets are
handled in the custodians' browsers; the gateway re-checks what they publish.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import tags
from .curve import (
    GENERATOR,
    ORDER,
    InvalidPoint,
    Point,
    add,
    decode_point,
    encode_point,
    hash_to_scalar,
    multiply,
)
from .encoding import enc


def _in_range(*scalars: int) -> bool:
    return all(0 <= scalar < ORDER for scalar in scalars)


def _combine(s: int, base: Point, c: int, public: Point) -> bytes | None:
    """s·base + c·public, encoded, or None for the identity."""
    point = add(multiply(s, base), multiply(c, public))
    return None if point is None else encode_point(point)


def schnorr_challenge(
    tenant_id: str, ceremony_id: str, dealer_index: int, commitment: bytes, nonce_point: bytes
) -> int:
    return hash_to_scalar(
        enc(tags.POK, tenant_id, ceremony_id, dealer_index, commitment, nonce_point)
    )


def verify_schnorr(
    tenant_id: str, ceremony_id: str, dealer_index: int, commitment: bytes, c: int, s: int
) -> bool:
    """Proof of knowledge of a_j0 behind C_j0 = a_j0·G."""
    if not _in_range(c, s):
        return False
    try:
        nonce_point = _combine(s, GENERATOR, c, decode_point(commitment))
    except InvalidPoint:
        return False
    if nonce_point is None:
        return False
    return c == schnorr_challenge(tenant_id, ceremony_id, dealer_index, commitment, nonce_point)


def share_proof_challenge(
    tenant_id: str, ceremony_id: str, holder_index: int, public_share: bytes, nonce_point: bytes
) -> int:
    return hash_to_scalar(
        enc(tags.SHARE_POK, tenant_id, ceremony_id, holder_index, public_share, nonce_point)
    )


def verify_share_proof(
    tenant_id: str, ceremony_id: str, holder_index: int, public_share: bytes, c: int, s: int
) -> bool:
    """A resharing's custodian knows x'_j behind X'_j, from the share it sealed (§9.7)."""
    if not _in_range(c, s):
        return False
    try:
        nonce_point = _combine(s, GENERATOR, c, decode_point(public_share))
    except InvalidPoint:
        return False
    if nonce_point is None:
        return False
    expected = share_proof_challenge(
        tenant_id, ceremony_id, holder_index, public_share, nonce_point
    )
    return c == expected


def lagrange_at_zero(index: int, indices: Sequence[int]) -> int:
    """λ_index at 0 over `indices`, mod n; the indices must be distinct and non-zero."""
    if len(set(indices)) != len(indices) or any(i % ORDER == 0 for i in indices):
        raise ValueError("Lagrange indices must be distinct and non-zero")
    numerator, denominator = 1, 1
    for other in indices:
        if other != index:
            numerator = numerator * other % ORDER
            denominator = denominator * (other - index) % ORDER
    return numerator * pow(denominator, ORDER - 2, ORDER) % ORDER


def dleq_challenge(
    tenant_id: str,
    request_id: str,
    key_id: str,
    holder_index: int,
    points: tuple[bytes, bytes, bytes, bytes, bytes],
) -> int:
    """points = (X_i, R, P_i, A, B); G is prepended here."""
    return hash_to_scalar(
        enc(
            tags.DLEQ, tenant_id, request_id, key_id, holder_index, encode_point(GENERATOR), *points
        )
    )


def verify_dleq(
    tenant_id: str,
    request_id: str,
    key_id: str,
    holder_index: int,
    statement: tuple[bytes, bytes, bytes],
    c: int,
    s: int,
) -> bool:
    """statement = (X_i, R, P_i): proves log_G X_i == log_R P_i."""
    if not _in_range(c, s):
        return False
    try:
        holder_share, ephemeral, partial = (decode_point(raw) for raw in statement)
    except InvalidPoint:
        return False
    first = _combine(s, GENERATOR, c, holder_share)
    second = _combine(s, ephemeral, c, partial)
    if first is None or second is None:
        return False
    expected = dleq_challenge(
        tenant_id, request_id, key_id, holder_index, (*statement, first, second)
    )
    return c == expected


def commitment_sum(index: int, commitments: Sequence[bytes]) -> Point | None:
    """Σ_t index^t · C_t, the public image of f(index)."""
    total: Point | None = None
    power = 1
    for raw in commitments:
        total = add(total, multiply(power, decode_point(raw)))
        power = power * index % ORDER
    return total


def verify_subshare(index: int, subshare: int, commitments: Sequence[bytes]) -> bool:
    """f_j(i)·G == Σ_t i^t·C_jt. Holders run this in the browser; tests mirror it."""
    if not 0 < subshare < ORDER:
        return False
    try:
        return multiply(subshare, GENERATOR) == commitment_sum(index, commitments)
    except InvalidPoint:
        return False


def recovery_public_key(dealings: Sequence[Sequence[bytes]]) -> bytes:
    """X = Σ_j C_j0."""
    total: Point | None = None
    for commitments in dealings:
        total = add(total, decode_point(commitments[0]))
    if total is None:
        raise InvalidPoint("the recovery key is the identity")
    return encode_point(total)


def holder_public_share(index: int, dealings: Sequence[Sequence[bytes]]) -> bytes:
    """X_i = Σ_j Σ_t i^t·C_jt."""
    total: Point | None = None
    for commitments in dealings:
        total = add(total, commitment_sum(index, commitments))
    if total is None:
        raise InvalidPoint("a public share is the identity")
    return encode_point(total)
