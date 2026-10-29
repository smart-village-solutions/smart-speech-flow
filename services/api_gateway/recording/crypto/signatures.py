"""ECDSA P-256 signatures over canonical fields (spec Appendix A.6).

The signed message is SHA-256(enc(type_tag, fields...)); ECDSA-SHA256 then
hashes that digest once more, exactly as WebCrypto does when handed the same
32 bytes. Signatures travel as IEEE P1363 `r || s`, the form WebCrypto
produces, so the DER that `cryptography` speaks is converted at this edge.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

from .curve import ORDER, InvalidPoint, public_key_from_point
from .encoding import Field, enc, scalar_to_bytes

SIGNATURE_BYTES: Final[int] = 64


def signed_digest(type_tag: str, *fields: Field) -> bytes:
    return hashlib.sha256(enc(type_tag, *fields)).digest()


def sign_fields(private_key: ec.EllipticCurvePrivateKey, type_tag: str, *fields: Field) -> bytes:
    # RFC 6979: no dependence on the RNG at signing time, and reproducible vectors.
    algorithm = ec.ECDSA(hashes.SHA256(), deterministic_signing=True)
    der = private_key.sign(signed_digest(type_tag, *fields), algorithm)
    r, s = decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verify_fields(public_key: bytes, signature: bytes, type_tag: str, *fields: Field) -> bool:
    if len(signature) != SIGNATURE_BYTES:
        return False
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if not (0 < r < ORDER and 0 < s < ORDER):
        return False
    try:
        key = public_key_from_point(public_key)
        key.verify(
            encode_dss_signature(r, s),
            signed_digest(type_tag, *fields),
            ec.ECDSA(hashes.SHA256()),
        )
    except (InvalidSignature, InvalidPoint, ValueError):
        return False
    return True


def wrap_fields(
    tenant_id: str,
    conversation_id: str,
    key_id: str,
    ephemeral: bytes,
    recipient_kind: str,
    recipient_ref: str,
    recipient_fingerprint: bytes,
) -> tuple[Field, ...]:
    """The fields a wrap signature covers; the browser signs the same tuple."""
    return (
        tenant_id,
        conversation_id,
        key_id,
        ephemeral,
        recipient_kind,
        recipient_ref,
        recipient_fingerprint,
    )


def dealing_fields(
    tenant_id: str,
    ceremony_id: str,
    dealer_index: int,
    commitments: Sequence[bytes],
    proof_c: int,
    proof_s: int,
) -> tuple[Field, ...]:
    """What a dealer signs, so a server cannot swap in a dealing of its own."""
    return (
        tenant_id,
        ceremony_id,
        dealer_index,
        len(commitments),
        *commitments,
        scalar_to_bytes(proof_c),
        scalar_to_bytes(proof_s),
    )


def request_fields(
    tenant_id: str,
    request_id: str,
    kind: str,
    recovery_key_id: str,
    requester_sub: str,
    reason: str,
    scope: Sequence[tuple[str, str]],
) -> tuple[Field, ...]:
    """What a requester signs, so nobody can widen the scope custodians approve (§9.5)."""
    pairs = sorted(scope)
    return (
        tenant_id,
        request_id,
        kind,
        recovery_key_id,
        requester_sub,
        hashlib.sha256(reason.encode("utf-8")).digest(),
        len(pairs),
        *(field for pair in pairs for field in pair),
    )


def partial_hash(blob: str) -> bytes:
    """Over the JSON text exactly as posted and stored, not a re-serialisation."""
    return hashlib.sha256(blob.encode("utf-8")).digest()


def approval_fields(
    tenant_id: str, request_id: str, holder_index: int, attempt: int, partials: Mapping[str, str]
) -> tuple[Field, ...]:
    """What a custodian signs: a bad partial under a good signature is theirs (§9.5)."""
    keys = sorted(partials)
    return (
        tenant_id,
        request_id,
        holder_index,
        attempt,
        len(keys),
        *(field for key_id in keys for field in (key_id, partial_hash(partials[key_id]))),
    )
