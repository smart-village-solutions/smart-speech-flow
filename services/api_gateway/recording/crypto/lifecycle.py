"""Generation-two canonical transcripts shared with Studio and SSF."""

from __future__ import annotations

import hashlib
from typing import Any

from .ecies import Sealed
from .encoding import enc, from_b64url


def digest(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def envelope_bytes(sealed: Sealed) -> bytes:
    return enc(1, sealed.type_tag, sealed.ephemeral, sealed.nonce, sealed.ciphertext)


def organisation_fingerprint(tenant: str, key_id: str, version: int, public: bytes) -> bytes:
    return digest(enc("SSF-ORG-KEY-V1", tenant, key_id, version, public))


def activation_transcript(
    tenant: str,
    actor: str,
    preparation: str,
    key: dict[str, Any],
    expected_active: str | None,
    expiry: str,
) -> bytes:
    return enc(
        "SSF-ORG-ACTIVATE-V1",
        tenant,
        actor,
        preparation,
        key["keyId"],
        key["version"],
        from_b64url(key["publicKey"]),
        from_b64url(key["fingerprint"]),
        expected_active or "",
        expiry,
        "saved",
    )


def scope_digest(keys: list[tuple[str, str, int, Sealed]], organisation: dict[str, Any]) -> bytes:
    members = []
    for conversation, key_id, epoch, source in sorted(keys, key=lambda row: row[:2]):
        members.append(
            digest(
                enc(
                    conversation,
                    key_id,
                    epoch,
                    organisation["keyId"],
                    organisation["version"],
                    digest(envelope_bytes(source)),
                )
            )
        )
    return digest(enc("SSF-TRANSFER-SCOPE-V1", *members))


def wraps_digest(wraps: dict[tuple[str, str], Sealed]) -> bytes:
    members = [enc(cid, kid, digest(envelope_bytes(wraps[cid, kid]))) for cid, kid in sorted(wraps)]
    return digest(enc("SSF-TRANSFER-WRAPS-V1", *members))


def transfer_transcript(
    tenant: str,
    actor: str,
    transfer: str,
    org: dict[str, Any],
    target: dict[str, Any],
    scope: bytes,
    reason: str,
    result: bytes,
    expiry: str,
) -> bytes:
    return enc(
        "SSF-ACCESS-TRANSFER-V1",
        tenant,
        actor,
        transfer,
        org["keyId"],
        org["version"],
        from_b64url(org["fingerprint"]),
        target["userSub"],
        target["version"],
        from_b64url(target["fingerprint"]),
        scope,
        digest(reason.encode()),
        result,
        expiry,
    )
