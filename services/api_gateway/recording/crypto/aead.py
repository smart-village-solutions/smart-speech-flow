"""AES-256-GCM envelopes: archive objects (A.3) and the server layer (A.5).

Both store `0x01 || nonce || ciphertext || tag`, and both bind the envelope to
where it belongs through the associated data, so a moved or swapped envelope
fails to open rather than opening in the wrong place.
"""

from __future__ import annotations

import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import tags
from .encoding import enc

KEY_BYTES: Final[int] = 32
NONCE_BYTES: Final[int] = 12
_VERSION: Final[int] = 1


class EnvelopeError(ValueError):
    """One message for every failure: which check failed is nobody's business."""


def object_aad(
    tenant_id: str, conversation_id: str, entry_id: str, object_type: str, key_id: str
) -> bytes:
    return enc(tags.OBJECT, tenant_id, conversation_id, entry_id, object_type, key_id)


def server_layer_aad(tenant_id: str, user_sub: str) -> bytes:
    return enc(tags.SERVER_LAYER, tenant_id, user_sub)


def seal(key: bytes, plaintext: bytes, aad: bytes, *, nonce: bytes | None = None) -> bytes:
    """`nonce` is for test vectors only; production always draws a fresh one."""
    if len(key) != KEY_BYTES:
        raise ValueError("an envelope key is 32 bytes")
    iv = os.urandom(NONCE_BYTES) if nonce is None else nonce
    if len(iv) != NONCE_BYTES:
        raise ValueError("a nonce is 12 bytes")
    return bytes([_VERSION]) + iv + AESGCM(key).encrypt(iv, plaintext, aad)


def open_(key: bytes, envelope: bytes, aad: bytes) -> bytes:
    if len(envelope) < 1 + NONCE_BYTES + 16 or envelope[0] != _VERSION:
        raise EnvelopeError("envelope failed authentication")
    iv, sealed = envelope[1 : 1 + NONCE_BYTES], envelope[1 + NONCE_BYTES :]
    try:
        return AESGCM(key).decrypt(iv, sealed, aad)
    except InvalidTag:
        raise EnvelopeError("envelope failed authentication") from None
