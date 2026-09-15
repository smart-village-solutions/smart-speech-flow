"""Authenticated encryption for feedback free text.

Unlike session_pseudonym.py there is deliberately no random per-process key
fallback: a pseudonym that changes across restarts costs comparability, but an
encryption key that changes across restarts costs the data itself. So a
gateway that cannot find its key refuses to accept feedback -- from_environment
raises, the lifespan leaves the service unbuilt, and POST /api/feedback
answers 503. It still starts and still serves conversations: a missing key
must not cost every customer their session.
"""

from __future__ import annotations

import base64
import binascii
import os
from typing import Final
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FEEDBACK_KEY_ENV: Final[str] = "SSF_FEEDBACK_ENCRYPTION_KEY"

_KEY_LENGTH: Final[int] = 32
_NONCE_LENGTH: Final[int] = 12

# Leading byte of every envelope. Rotation adds a version and keeps the old key
# for decryption; without it, rotation means re-encrypting every stored row
# under a lock nobody wants to hold for twelve months of feedback.
_KEY_VERSION: Final[int] = 1


class MissingEncryptionKey(RuntimeError):
    """Raised at startup when no usable key is configured."""


class FeedbackCipher:
    """AES-GCM bound to the row it belongs to."""

    def __init__(self, *, key: bytes) -> None:
        if len(key) != _KEY_LENGTH:
            raise MissingEncryptionKey(f"{FEEDBACK_KEY_ENV} must decode to {_KEY_LENGTH} bytes")
        self._aesgcm = AESGCM(key)

    @classmethod
    def from_environment(cls) -> "FeedbackCipher":
        configured = (os.environ.get(FEEDBACK_KEY_ENV) or "").strip()
        if not configured:
            raise MissingEncryptionKey(
                f"{FEEDBACK_KEY_ENV} is required; feedback cannot be stored " "without it"
            )
        try:
            key = base64.b64decode(configured, validate=True)
        except (ValueError, binascii.Error) as error:
            raise MissingEncryptionKey(f"{FEEDBACK_KEY_ENV} must be base64-encoded") from error
        return cls(key=key)

    def encrypt(self, plaintext: str, *, feedback_id: UUID, tenant_id: str) -> bytes:
        nonce = os.urandom(_NONCE_LENGTH)
        sealed = self._aesgcm.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            _associated_data(feedback_id, tenant_id),
        )
        return bytes([_KEY_VERSION]) + nonce + sealed

    def decrypt(self, envelope: bytes, *, feedback_id: UUID, tenant_id: str) -> str:
        if not envelope or envelope[0] != _KEY_VERSION:
            raise ValueError("unknown feedback envelope version")

        nonce = envelope[1 : 1 + _NONCE_LENGTH]
        sealed = envelope[1 + _NONCE_LENGTH :]
        try:
            plaintext = self._aesgcm.decrypt(
                nonce, sealed, _associated_data(feedback_id, tenant_id)
            )
        except InvalidTag as error:
            # Wrong row, wrong tenant, or a tampered envelope. Deliberately one
            # message for all three: which one it was is not the caller's
            # business and saying so helps an attacker probe the store.
            raise ValueError("feedback envelope failed authentication") from error
        return plaintext.decode("utf-8")


def _associated_data(feedback_id: UUID, tenant_id: str) -> bytes:
    """Bind a ciphertext to its row so it cannot be moved between them."""
    return f"{feedback_id}:{tenant_id}".encode("utf-8")
