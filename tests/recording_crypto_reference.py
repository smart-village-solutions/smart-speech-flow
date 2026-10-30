"""Test-only counterparts of what the browser does with secrets.

Provers, polynomial dealing, Lagrange combination and the passphrase-sealed
private-key blob exist in production only in TypeScript. These Python
versions generate the shared vectors and let gateway tests run a whole
ceremony; no module under services/ imports this file.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from services.api_gateway.recording.crypto import tags
from services.api_gateway.recording.crypto.curve import (
    GENERATOR,
    ORDER,
    Point,
    add,
    encode_point,
    multiply,
    require_point,
)
from services.api_gateway.recording.crypto.encoding import b64url, enc, from_b64url
from services.api_gateway.recording.crypto.proofs import (
    dleq_challenge,
    schnorr_challenge,
    share_proof_challenge,
)


def public_point(scalar: int) -> bytes:
    return encode_point(require_point(multiply(scalar, GENERATOR)))


def private_key(scalar: int) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(scalar, ec.SECP256R1())


def pkcs8(scalar: int) -> bytes:
    return private_key(scalar).private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def evaluate(coefficients: Sequence[int], index: int) -> int:
    result = 0
    for coefficient in reversed(coefficients):
        result = (result * index + coefficient) % ORDER
    return result


def commitments(coefficients: Sequence[int]) -> tuple[bytes, ...]:
    return tuple(public_point(coefficient) for coefficient in coefficients)


def schnorr_prove(
    tenant_id: str, ceremony_id: str, dealer_index: int, secret: int, nonce: int
) -> tuple[int, int]:
    commitment = public_point(secret)
    c = schnorr_challenge(tenant_id, ceremony_id, dealer_index, commitment, public_point(nonce))
    return c, (nonce - c * secret) % ORDER


def dleq_prove(
    tenant_id: str,
    request_id: str,
    key_id: str,
    holder_index: int,
    share: int,
    ephemeral: Point,
    nonce: int,
) -> tuple[bytes, int, int]:
    """Returns (P_i, c, s) for P_i = x_i·R."""
    partial = encode_point(require_point(multiply(share, ephemeral)))
    first = public_point(nonce)
    second = encode_point(require_point(multiply(nonce, ephemeral)))
    statement = (public_point(share), encode_point(ephemeral), partial)
    c = dleq_challenge(tenant_id, request_id, key_id, holder_index, (*statement, first, second))
    return partial, c, (nonce - c * share) % ORDER


def share_proof_prove(
    tenant_id: str, ceremony_id: str, holder_index: int, share: int, nonce: int
) -> tuple[int, int]:
    """Proof of knowledge of x'_j behind X'_j, from the share a custodian re-opened (§9.7)."""
    c = share_proof_challenge(
        tenant_id, ceremony_id, holder_index, public_point(share), public_point(nonce)
    )
    return c, (nonce - c * share) % ORDER


def lagrange_at_zero(index: int, indices: Sequence[int]) -> int:
    numerator, denominator = 1, 1
    for other in indices:
        if other != index:
            numerator = numerator * other % ORDER
            denominator = denominator * (other - index) % ORDER
    return numerator * pow(denominator, -1, ORDER) % ORDER


def combine_partials(partials: Sequence[tuple[int, Point]]) -> bytes:
    """Σ λ_i·P_i = x·R; returns its 32-byte x-coordinate, the wrap's Z."""
    indices = [index for index, _ in partials]
    total: Point | None = None
    for index, partial in partials:
        total = add(total, multiply(lagrange_at_zero(index, indices), partial))
    return require_point(total)[0].to_bytes(32, "big")


def private_key_aad(
    tenant_id: str, user_sub: str, purpose: str, salt: bytes, m: int, t: int, p: int
) -> bytes:
    return enc(tags.PRIVATE_KEY, tenant_id, user_sub, purpose, salt, m, t, p)


def stretch(passphrase: str, salt: bytes, m: int, t: int, p: int) -> bytes:
    kdf = Argon2id(salt=salt, length=32, iterations=t, lanes=p, memory_cost=m)
    return kdf.derive(passphrase.encode("utf-8"))


def seal_private_keys(
    passphrase: str,
    tenant_id: str,
    user_sub: str,
    keys: dict[str, bytes],
    *,
    salt: bytes,
    nonces: dict[str, bytes],
    params: tuple[int, int, int],
) -> str:
    """The blob the browser uploads at enrolment (A.5), for vectors and tests."""
    m, t, p = params
    stretched = AESGCM(stretch(passphrase, salt, m, t, p))
    body: dict[str, object] = {
        "v": 1,
        "kdf": {"alg": "argon2id", "m": m, "t": t, "p": p, "salt": b64url(salt)},
    }
    for purpose in ("enc", "sig"):
        aad = private_key_aad(tenant_id, user_sub, purpose, salt, m, t, p)
        sealed = stretched.encrypt(nonces[purpose], keys[purpose], aad)
        body[purpose] = {"nonce": b64url(nonces[purpose]), "ct": b64url(sealed)}
    return json.dumps(body, separators=(",", ":"))


def open_private_keys(
    blob: str, passphrase: str, tenant_id: str, user_sub: str
) -> dict[str, bytes]:
    body = json.loads(blob)
    kdf = body["kdf"]
    salt, m, t, p = from_b64url(kdf["salt"]), kdf["m"], kdf["t"], kdf["p"]
    stretched = AESGCM(stretch(passphrase, salt, m, t, p))
    opened = {}
    for purpose in ("enc", "sig"):
        aad = private_key_aad(tenant_id, user_sub, purpose, salt, m, t, p)
        part = body[purpose]
        opened[purpose] = stretched.decrypt(
            from_b64url(part["nonce"]), from_b64url(part["ct"]), aad
        )
    return opened
