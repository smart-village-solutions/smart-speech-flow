"""The gateway's recording secrets, read from files outside `.env` (spec §12.5).

backup-production.sh copies `.env` into every backup, so a signing key kept
there would sit in each tarball for a year. Both secrets are mounted read-only
from a directory the operator backs up separately, offline. A gateway without
them still serves conversations; only the recording routes answer 503.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .crypto import aead
from .crypto.curve import point_from_public_key

SIGNING_KEY_FILE_ENV: Final[str] = "SSF_RECORDING_SIGNING_KEY_FILE"
BLOB_KEY_FILE_ENV: Final[str] = "SSF_RECORDING_BLOB_KEY_FILE"
SECRETS_DIRECTORY: Final[str] = "/run/secrets/ssf-recording"


class MissingRecordingSecrets(RuntimeError):
    """A secret file is absent, unreadable or malformed. The message names no path content."""


class ServerLayer:
    """The gateway's second envelope around each private-key blob (spec §8.3, A.5).

    A database dump alone then holds nothing a passphrase guess can be tested
    against: the attacker also needs this key, which no backup of the
    database or of `.env` contains.
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != aead.KEY_BYTES:
            raise MissingRecordingSecrets("the blob key must be 32 bytes")
        self._key = key

    def seal(self, blob: bytes, *, tenant_id: str, user_sub: str) -> bytes:
        return aead.seal(self._key, blob, aead.server_layer_aad(tenant_id, user_sub))

    def open(self, envelope: bytes, *, tenant_id: str, user_sub: str) -> bytes:
        return aead.open_(self._key, envelope, aead.server_layer_aad(tenant_id, user_sub))


def gateway_key_id(public_key: bytes) -> str:
    """Stable per key, so chain entries and wraps can name the key that signed them."""
    return "gk-" + hashlib.sha256(public_key).hexdigest()[:16]


@dataclass(frozen=True)
class RecordingSecrets:
    signing_key: ec.EllipticCurvePrivateKey
    signing_key_id: str
    signing_public_key: bytes
    server_layer: ServerLayer

    @classmethod
    def from_environment(cls) -> "RecordingSecrets":
        signing = os.environ.get(SIGNING_KEY_FILE_ENV) or f"{SECRETS_DIRECTORY}/signing-key.pem"
        blob = os.environ.get(BLOB_KEY_FILE_ENV) or f"{SECRETS_DIRECTORY}/blob-key"
        return cls.from_files(Path(signing), Path(blob))

    @classmethod
    def from_files(cls, signing_path: Path, blob_path: Path) -> "RecordingSecrets":
        signing_key = _load_signing_key(signing_path)
        public_key = point_from_public_key(signing_key.public_key())
        return cls(
            signing_key=signing_key,
            signing_key_id=gateway_key_id(public_key),
            signing_public_key=public_key,
            server_layer=ServerLayer(_load_blob_key(blob_path)),
        )


def _read(path: Path, variable: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise MissingRecordingSecrets(f"{variable} names no readable file") from None


def _load_signing_key(path: Path) -> ec.EllipticCurvePrivateKey:
    raw = _read(path, SIGNING_KEY_FILE_ENV)
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except (ValueError, TypeError):
        raise MissingRecordingSecrets("the signing key is not an unencrypted PEM key") from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise MissingRecordingSecrets("the signing key must be a P-256 key")
    return key


def _load_blob_key(path: Path) -> bytes:
    raw = _read(path, BLOB_KEY_FILE_ENV)
    try:
        return base64.b64decode(raw.strip(), validate=True)
    except ValueError:
        raise MissingRecordingSecrets("the blob key must be base64") from None
