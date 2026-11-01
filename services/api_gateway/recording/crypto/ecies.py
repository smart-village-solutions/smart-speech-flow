"""ECIES payloads on P-256 (spec Appendix A.4).

A sealed payload names its type tag, and opening it requires the caller to
name the type it expects. The tag is also the HKDF `info` and the first
associated-data field, so a share presented as a key wrap fails three ways.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import tags
from .curve import decode_point, point_from_public_key, public_key_from_point
from .encoding import Field, b64url, enc, from_b64url

_NONCE_BYTES: Final[int] = 12


class SealedPayloadError(ValueError):
    """A payload of the wrong type, shape or context, or a failed tag."""


@dataclass(frozen=True)
class Sealed:
    type_tag: str
    ephemeral: bytes
    nonce: bytes
    ciphertext: bytes

    def to_json(self) -> str:
        return json.dumps(
            {
                "v": 1,
                "t": self.type_tag,
                "R": b64url(self.ephemeral),
                "nonce": b64url(self.nonce),
                "ct": b64url(self.ciphertext),
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, text: str, *, expected_type: str) -> "Sealed":
        try:
            body = json.loads(text)
            sealed = cls(
                type_tag=body["t"],
                ephemeral=from_b64url(body["R"]),
                nonce=from_b64url(body["nonce"]),
                ciphertext=from_b64url(body["ct"]),
            )
            version = body["v"]
        except (ValueError, KeyError, TypeError):
            raise SealedPayloadError("malformed sealed payload") from None
        if version != 1 or sealed.type_tag != expected_type:
            raise SealedPayloadError("unexpected sealed payload type")
        decode_point(sealed.ephemeral)
        return sealed


def payload_key(shared_x: bytes, ephemeral: bytes, recipient: bytes, type_tag: str) -> bytes:
    """K = HKDF-SHA256(ikm = Z, salt = R || P, info = T)."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=ephemeral + recipient,
        info=type_tag.encode("ascii"),
    )
    return hkdf.derive(shared_x)


def seal(
    type_tag: str,
    recipient: bytes,
    plaintext: bytes,
    context: tuple[Field, ...],
    *,
    ephemeral_key: ec.EllipticCurvePrivateKey | None = None,
    nonce: bytes | None = None,
) -> Sealed:
    """`ephemeral_key` and `nonce` are for test vectors only."""
    if type_tag not in tags.SEALED_TYPES:
        raise SealedPayloadError("not a sealed payload type")
    recipient_key = public_key_from_point(recipient)
    ephemeral = ephemeral_key or ec.generate_private_key(ec.SECP256R1())
    ephemeral_point = point_from_public_key(ephemeral.public_key())
    shared_x = ephemeral.exchange(ec.ECDH(), recipient_key)
    key = payload_key(shared_x, ephemeral_point, recipient, type_tag)
    iv = os.urandom(_NONCE_BYTES) if nonce is None else nonce
    ciphertext = AESGCM(key).encrypt(iv, plaintext, enc(type_tag, *context))
    return Sealed(type_tag, ephemeral_point, iv, ciphertext)


def open_with_shared_x(
    sealed: Sealed, shared_x: bytes, recipient: bytes, context: tuple[Field, ...]
) -> bytes:
    """Open given Z directly: the recovery path computes Z from partials."""
    key = payload_key(shared_x, sealed.ephemeral, recipient, sealed.type_tag)
    try:
        return AESGCM(key).decrypt(sealed.nonce, sealed.ciphertext, enc(sealed.type_tag, *context))
    except InvalidTag:
        raise SealedPayloadError("sealed payload failed authentication") from None


def open_with_private_key(
    sealed: Sealed, private_key: ec.EllipticCurvePrivateKey, context: tuple[Field, ...]
) -> bytes:
    recipient = point_from_public_key(private_key.public_key())
    shared_x = private_key.exchange(ec.ECDH(), public_key_from_point(sealed.ephemeral))
    return open_with_shared_x(sealed, shared_x, recipient, context)


def ck_wrap_context(
    tenant_id: str, conversation_id: str, key_id: str, recipient_kind: str, recipient_ref: str
) -> tuple[Field, ...]:
    return (tenant_id, conversation_id, key_id, recipient_kind, recipient_ref)


def share_context(
    tenant_id: str, recovery_key_id: str, index: int, holder_ref: str
) -> tuple[Field, ...]:
    return (tenant_id, recovery_key_id, index, holder_ref)


def subshare_context(
    tenant_id: str, ceremony_id: str, dealer_index: int, recipient_index: int
) -> tuple[Field, ...]:
    return (tenant_id, ceremony_id, dealer_index, recipient_index)


def partial_context(
    tenant_id: str,
    request_id: str,
    key_id: str,
    holder_index: int,
    requester_sub: str,
    requester_fingerprint: bytes,
) -> tuple[Field, ...]:
    return (tenant_id, request_id, key_id, holder_index, requester_sub, requester_fingerprint)
