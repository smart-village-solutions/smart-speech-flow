"""P-256 point arithmetic on public values (spec Appendix A.1).

`cryptography` does ECDH and ECDSA but exposes no point addition, which the
gateway needs to check the recovery-key ceremony: summing commitments into
`X` and `X_i`, and verifying proofs. This arithmetic is not constant-time, so
it only ever touches public values. Anything secret goes through
`cryptography` (ECDH for wraps, ECDSA for signatures).
"""

from __future__ import annotations

import hashlib
from typing import Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

# Curve parameters from SEC 2, section 2.4.2.
FIELD_PRIME: Final[int] = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A: Final[int] = FIELD_PRIME - 3
_B: Final[int] = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
ORDER: Final[int] = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
GENERATOR: Final[tuple[int, int]] = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)
POINT_BYTES: Final[int] = 65

Point = tuple[int, int]


class InvalidPoint(ValueError):
    """A received point that is malformed, off the curve or the identity."""


def decode_point(raw: bytes) -> Point:
    """SEC1 uncompressed only. The identity has no 65-byte form, so it cannot pass."""
    if len(raw) != POINT_BYTES or raw[0] != 0x04:
        raise InvalidPoint("expected a 65-byte SEC1 uncompressed point")
    point = (int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big"))
    if not is_on_curve(point):
        raise InvalidPoint("point is not on P-256")
    return point


def encode_point(point: Point) -> bytes:
    x, y = point
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def is_on_curve(point: Point) -> bool:
    x, y = point
    in_field = 0 <= x < FIELD_PRIME and 0 <= y < FIELD_PRIME
    return in_field and (y * y - (x * x * x + _A * x + _B)) % FIELD_PRIME == 0


def add(left: Point | None, right: Point | None) -> Point | None:
    """Affine addition; None is the identity."""
    if left is None:
        return right
    if right is None:
        return left
    if left[0] == right[0] and (left[1] + right[1]) % FIELD_PRIME == 0:
        return None
    return _add_distinct_or_double(left, right)


def _add_distinct_or_double(left: Point, right: Point) -> Point:
    (x1, y1), (x2, y2) = left, right
    if left == right:
        slope = (3 * x1 * x1 + _A) * pow(2 * y1, -1, FIELD_PRIME)
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, FIELD_PRIME)
    slope %= FIELD_PRIME
    x3 = (slope * slope - x1 - x2) % FIELD_PRIME
    return x3, (slope * (x1 - x3) - y1) % FIELD_PRIME


def multiply(scalar: int, point: Point | None) -> Point | None:
    result: Point | None = None
    addend = point
    remaining = scalar % ORDER
    while remaining:
        if remaining & 1:
            result = add(result, addend)
        addend = add(addend, addend)
        remaining >>= 1
    return result


def require_point(point: Point | None) -> Point:
    """A computed sum or product that must not be the identity."""
    if point is None:
        raise InvalidPoint("result is the identity")
    return point


def hash_to_scalar(message: bytes) -> int:
    """H_n(m) = int(SHA-512(m)) mod n."""
    return int.from_bytes(hashlib.sha512(message).digest(), "big") % ORDER


def public_key_from_point(raw: bytes) -> ec.EllipticCurvePublicKey:
    decode_point(raw)
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)


def point_from_public_key(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
