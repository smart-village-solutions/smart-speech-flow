"""Personal key enrolment and retrieval (spec §8.3).

The browser generates the key pairs and seals the private keys under the
user's passphrase; the gateway only ever sees the sealed blob, which it
checks for shape and minimum work factor, wraps once more in its server
layer, and stores. It cannot open the blob and never tries.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final, Protocol

from .audit import AuditEvent
from .crypto.curve import InvalidPoint, decode_point
from .crypto.encoding import from_b64url
from .crypto.transcript import fingerprint
from .repository import UserKeyRecord
from .secrets import ServerLayer

MAX_BLOB_CHARACTERS: Final[int] = 4096
# The enrolment floor of spec §8.3; a browser may choose more, never less.
MIN_MEMORY_KIB: Final[int] = 65536
MIN_ITERATIONS: Final[int] = 3
MAX_LANES: Final[int] = 4
_SALT_BYTES: Final[int] = 16
_NONCE_BYTES: Final[int] = 12
# A sealed PKCS#8 P-256 key is about 150 bytes; anything far off is not one.
_SEALED_KEY_BYTES: Final[range] = range(100, 513)


class InvalidEnrolment(ValueError):
    """The upload is not a pair of P-256 keys with a well-formed sealed blob."""


class KeyStore(Protocol):
    async def active_user_key(self, tenant_id: str, user_sub: str) -> UserKeyRecord | None: ...

    async def enrol_user_key(self, record: UserKeyRecord, audit: AuditEvent) -> None: ...

    async def record_audit(self, event: AuditEvent) -> None: ...


@dataclass(frozen=True)
class Enrolment:
    enc_pub: bytes
    sig_pub: bytes
    blob: str


@dataclass(frozen=True)
class OwnKey:
    enc_pub: bytes
    sig_pub: bytes
    fingerprint: bytes
    blob: str
    created_at: datetime


def _is_count(value: Any, minimum: int, maximum: int | None = None) -> bool:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        return False
    return maximum is None or value <= maximum


def _decoded_length(value: Any) -> int:
    if not isinstance(value, str):
        return -1
    try:
        return len(from_b64url(value))
    except ValueError:
        return -1


def _kdf_is_valid(kdf: Any) -> bool:
    return (
        isinstance(kdf, dict)
        and kdf.get("alg") == "argon2id"
        and _is_count(kdf.get("m"), MIN_MEMORY_KIB)
        and _is_count(kdf.get("t"), MIN_ITERATIONS)
        and _is_count(kdf.get("p"), 1, MAX_LANES)
        and _decoded_length(kdf.get("salt")) == _SALT_BYTES
    )


def _sealed_key_is_valid(part: Any) -> bool:
    return (
        isinstance(part, dict)
        and _decoded_length(part.get("nonce")) == _NONCE_BYTES
        and _decoded_length(part.get("ct")) in _SEALED_KEY_BYTES
    )


def validate_blob(blob: str) -> None:
    """Shape and work factor only: the gateway cannot, and must not, open it."""
    if len(blob) > MAX_BLOB_CHARACTERS:
        raise InvalidEnrolment("blob too large")
    try:
        body = json.loads(blob)
    except ValueError:
        raise InvalidEnrolment("blob is not JSON") from None
    valid = (
        isinstance(body, dict)
        and body.get("v") == 1
        and _kdf_is_valid(body.get("kdf"))
        and _sealed_key_is_valid(body.get("enc"))
        and _sealed_key_is_valid(body.get("sig"))
    )
    if not valid:
        raise InvalidEnrolment("blob does not have the private-key shape")


def _validate_points(enrolment: Enrolment) -> None:
    try:
        decode_point(enrolment.enc_pub)
        decode_point(enrolment.sig_pub)
    except InvalidPoint:
        raise InvalidEnrolment("public keys must be P-256 points") from None
    if enrolment.enc_pub == enrolment.sig_pub:
        raise InvalidEnrolment("the two key pairs must differ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class KeyEnrolmentService:
    def __init__(
        self,
        *,
        repository: KeyStore,
        server_layer: ServerLayer,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._repository = repository
        self._server_layer = server_layer
        self._clock = clock

    async def enrol(self, tenant_id: str, user_sub: str, enrolment: Enrolment) -> bytes:
        """Returns the key fingerprint. KeyAlreadyEnrolled if a key is active."""
        _validate_points(enrolment)
        validate_blob(enrolment.blob)
        now = self._clock()
        record = UserKeyRecord(
            tenant_id=tenant_id,
            user_sub=user_sub,
            key_version=1,
            enc_pub=enrolment.enc_pub,
            sig_pub=enrolment.sig_pub,
            fingerprint=fingerprint(tenant_id, user_sub, enrolment.enc_pub, enrolment.sig_pub),
            encrypted_private=self._server_layer.seal(
                enrolment.blob.encode("utf-8"), tenant_id=tenant_id, user_sub=user_sub
            ),
            created_at=now,
        )
        audit = AuditEvent(tenant_id, user_sub, "key_enrolled", "user-key:1", now)
        await self._repository.enrol_user_key(record, audit)
        return record.fingerprint

    async def own_key(self, tenant_id: str, user_sub: str) -> OwnKey | None:
        record = await self._repository.active_user_key(tenant_id, user_sub)
        if record is None or record.encrypted_private is None:
            return None
        blob = self._server_layer.open(
            record.encrypted_private, tenant_id=tenant_id, user_sub=user_sub
        ).decode("utf-8")
        # Every blob download is a chance to guess offline, so each is on record.
        await self._repository.record_audit(
            AuditEvent(
                tenant_id,
                user_sub,
                "key_blob_read",
                f"user-key:{record.key_version}",
                self._clock(),
            )
        )
        return OwnKey(record.enc_pub, record.sig_pub, record.fingerprint, blob, record.created_at)
